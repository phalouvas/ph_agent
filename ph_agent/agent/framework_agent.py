import asyncio
import inspect
import json
import logging
import queue
import threading
from collections.abc import Generator, Sequence
from pathlib import Path
from typing import Any

import frappe

from agent_framework import Agent, AgentSession, Content, HistoryProvider, InMemoryHistoryProvider, Message
from agent_framework_openai import OpenAIChatCompletionClient
from agent_framework import SkillsProvider
from openai import AsyncOpenAI
from ph_agent.agent.context.llm_memory_provider import LLMMemoryProvider
from ph_agent.agent.context.user_preference_provider import UserPreferenceProvider
from ph_agent.agent.skills import get_code_skills
from ph_agent.agent.skills.script_runner import run_file_script
from ph_agent.api.token_utils import _atomic_update_chat_session_tokens, _atomic_update_user_token_usage
from ph_agent.agent.tools.tool_manager import ToolManager

logger = logging.getLogger(__name__)
from ph_agent.agent.tools.tool_router_provider import (
    _ROUTER_SYSTEM_PROMPT,
    _ROUTING_THRESHOLD,
    _ROUTER_MAX_TOKENS,
)
from ph_agent.utils.debug_logger import debug_log


# ---------------------------------------------------------------------------
# Patch agent_framework_openai to handle DeepSeek's reasoning_content
# ---------------------------------------------------------------------------
# The library reads ``reasoning_details`` from the OpenAI response object,
# but DeepSeek returns ``reasoning_content``. Since the OpenAI SDK v2.32.0
# models have ``extra="allow"``, ``reasoning_content`` lands in Pydantic's
# ``model_extra`` dict rather than as a named attribute.
#
# We patch the two parsing methods to also extract reasoning from model_extra.

import agent_framework_openai._chat_completion_client as _openai_client_mod


def _extract_reasoning_from_message(msg) -> str | None:
	"""Extract reasoning_content text from an OpenAI message/delta object.
	
	Checks both direct attribute (``reasoning_details``) and Pydantic
	``model_extra`` (``reasoning_content`` from DeepSeek).
	Returns the raw reasoning text string, or None.
	"""
	# Check direct attribute (standard agent_framework_openai path)
	reasoning = getattr(msg, "reasoning_details", None)
	if reasoning is not None:
		return str(reasoning)
	# Check model_extra for DeepSeek's reasoning_content
	if hasattr(msg, "model_extra") and msg.model_extra:
		reasoning = msg.model_extra.get("reasoning_content")
		if reasoning is not None:
			return str(reasoning)
	# Belt-and-suspenders: check reasoning_content as direct attribute
	# (in case a future SDK version promotes it from model_extra).
	reasoning = getattr(msg, "reasoning_content", None)
	if reasoning is not None:
		return str(reasoning)
	return None


_orig_parse_response = _openai_client_mod.OpenAIChatCompletionClient._parse_response_from_openai


def _patched_parse_response(self, response, options):
	"""Patched non-streaming parser: also extracts reasoning from model_extra."""
	result = _orig_parse_response(self, response, options)
	# Check each choice for reasoning_content that the original parser missed
	for choice in getattr(response, "choices", []) or []:
		msg = getattr(choice, "message", None)
		if msg is None:
			continue
		reasoning_text = _extract_reasoning_from_message(msg)
		if reasoning_text:
			# Find the assistant message in the result and add reasoning content
			for m in result.messages:
				if m.role == "assistant":
					# Only add if not already present (avoid duplicates)
					has_reasoning = any(
						getattr(c, 'type', None) == "text_reasoning"
						for c in getattr(m, 'contents', []) or []
					)
					if not has_reasoning:
						# Use protected_data to match how the library serializes
						# text_reasoning Content for the API (see _prepare_message_for_openai).
						m.contents.append(
							Content.from_text_reasoning(
								protected_data=json.dumps(reasoning_text)
							)
						)
					break
	return result


_orig_parse_update = _openai_client_mod.OpenAIChatCompletionClient._parse_response_update_from_openai


def _patched_parse_update(self, chunk):
	"""Patched streaming parser: also extracts reasoning from model_extra."""
	update = _orig_parse_update(self, chunk)
	# Check each choice's delta for reasoning_content
	for choice in getattr(chunk, "choices", []) or []:
		delta = getattr(choice, "delta", None)
		if delta is None:
			continue
		reasoning_text = _extract_reasoning_from_message(delta)
		if reasoning_text:
			# Only add if not already present
			has_reasoning = any(
				getattr(c, 'type', None) == "text_reasoning"
				for c in getattr(update, 'contents', []) or []
			)
			if not has_reasoning:
				# Use protected_data to match how the library serializes
				# text_reasoning Content for the API (see _prepare_message_for_openai).
				update.contents.append(
					Content.from_text_reasoning(
						protected_data=json.dumps(reasoning_text)
					)
				)
			else:
				# Update existing text_reasoning content's protected_data
				# so the latest cumulative reasoning is preserved.
				for c in update.contents:
					if getattr(c, "type", None) == "text_reasoning":
						c.protected_data = json.dumps(reasoning_text)
						break
	return update


# ---------------------------------------------------------------------------
# Patch _prepare_message_for_openai to rename reasoning_details → reasoning_content
# ---------------------------------------------------------------------------
# DeepSeek's API expects ``reasoning_content`` as the top-level field name
# (matching the OpenAI SDK's response field), not ``reasoning_details`` which
# is the internal agent_framework convention.
#
# Also add a belt-and-suspenders fallback: if a text_reasoning Content has
# ``text`` but no ``protected_data``, treat ``text`` as the reasoning.

_orig_prepare_message = _openai_client_mod.OpenAIChatCompletionClient._prepare_message_for_openai


def _patched_prepare_message_for_openai(self, message):
	"""Patched message preparer: renames reasoning_details → reasoning_content,
	with belt-and-suspenders fallback for text_reasoning Content."""
	result = _orig_prepare_message(self, message)
	# Rename reasoning_details → reasoning_content for DeepSeek compatibility
	for msg_dict in result:
		if "reasoning_details" in msg_dict:
			msg_dict["reasoning_content"] = msg_dict.pop("reasoning_details")
	# Fix reasoning_content placement: the upstream serialiser puts
	# reasoning_details on the *last* dict (typically tool_calls-only).
	# DeepSeek requires reasoning_content on EVERY dict for an assistant
	# message — when a tool call is present DeepSeek checks the
	# tool_calls-bearing dict for reasoning_content and returns 400 if
	# it is missing.  Copy (don't move) so all dicts carry it.
	reasoning_value = None
	for msg_dict in result:
		if "reasoning_content" in msg_dict and not msg_dict.get("content"):
			reasoning_value = msg_dict["reasoning_content"]
			break
	if reasoning_value is not None:
		# Ensure the content dict also has reasoning_content
		for msg_dict in result:
			if "content" in msg_dict and "reasoning_content" not in msg_dict:
				msg_dict["reasoning_content"] = reasoning_value
				break

	# Belt-and-suspenders: if the message has text_reasoning Content but
	# no output dict ended up with reasoning_content, extract it directly.
	# This catches cases where the upstream _prepare_message_for_openai
	# fails to serialize text_reasoning (e.g. protected_data is None,
	# or content ordering causes the pending buffer to be dropped).
	if message.role == "assistant" and result:
		if not any("reasoning_content" in md for md in result):
			reasoning_text = None
			for c in getattr(message, "contents", []) or []:
				if getattr(c, "type", None) == "text_reasoning":
					protected = getattr(c, "protected_data", None)
					if protected is not None:
						try:
							reasoning_text = json.loads(protected)
						except (json.JSONDecodeError, TypeError):
							reasoning_text = protected
					else:
						reasoning_text = getattr(c, "text", None)
					if reasoning_text:
						break
			if reasoning_text:
				# Put reasoning_content on EVERY assistant message dict —
				# DeepSeek requires it on every dict when tool calls are present.
				for msg_dict in result:
					if "reasoning_content" not in msg_dict:
						msg_dict["reasoning_content"] = reasoning_text
				logger.warning(
					"Belt-and-suspenders: injected missing reasoning_content "
					"(len=%d) for message role=%s — upstream serialization "
					"did not produce reasoning_details",
					len(reasoning_text), message.role,
				)
	return result


# Apply patches
_openai_client_mod.OpenAIChatCompletionClient._parse_response_from_openai = _patched_parse_response
_openai_client_mod.OpenAIChatCompletionClient._parse_response_update_from_openai = _patched_parse_update
_openai_client_mod.OpenAIChatCompletionClient._prepare_message_for_openai = _patched_prepare_message_for_openai


# ---------------------------------------------------------------------------
# Diagnostic patch: log DeepSeek API request when thinking mode is enabled
# ---------------------------------------------------------------------------
_orig_prepare_options = _openai_client_mod.RawOpenAIChatCompletionClient._prepare_options


def _patched_prepare_options(self, messages, options):
	"""Patched _prepare_options: logs request body for thinking-mode debugging."""
	result = _orig_prepare_options(self, messages, options)

	thinking_cfg = result.get("thinking")
	if isinstance(thinking_cfg, dict) and thinking_cfg.get("type") == "enabled":
		msg_summary = []
		for i, msg in enumerate(result.get("messages", [])):
			has_reasoning = "reasoning_content" in msg
			role = msg.get("role", "?")
			has_content = "content" in msg
			has_tool_calls = "tool_calls" in msg
			content_len = len(str(msg.get("content", ""))) if has_content else 0
			reasoning_len = len(str(msg.get("reasoning_content", ""))) if has_reasoning else 0
			msg_summary.append(
				f"  [{i}] role={role} content={has_content}({content_len}c) "
				f"tool_calls={has_tool_calls} reasoning_content={has_reasoning}({reasoning_len}r)"
			)
		messages_json = json.dumps(
			result.get("messages", []), indent=2, default=str, ensure_ascii=False
		)[:8000]
		debug_log(
			"DeepSeek thinking-mode API request",
			f"model={result.get('model')} messages={len(result.get('messages', []))} "
			f"reasoning_effort={result.get('reasoning_effort')}\n"
			f"{chr(10).join(msg_summary)}\n"
			f"---FULL MESSAGES---\n{messages_json}",
			level="WARNING",
		)

	return result


_openai_client_mod.RawOpenAIChatCompletionClient._prepare_options = _patched_prepare_options


# ---------------------------------------------------------------------------
# Text post-processing helpers
# ---------------------------------------------------------------------------

# Regex: a sentence-ending punctuation (. ! ?) followed by an uppercase letter
# or a common lowercase starter (let, now, the, this, that, it, i, we, they)
# with NO space in between.  Insert a space.
_SENTENCE_GAP_RE = None  # lazy-compiled below


def _fix_missing_sentence_spaces(text: str) -> str:
	"""Insert a missing space after sentence-ending punctuation when the next
	word starts with an uppercase letter or a known sentence starter.

	The LLM sometimes concatenates sentences without a space, e.g.:
		"first.No existing"  →  "first. No existing"
		"system.Now let"    →  "system. Now let"
	"""
	import re

	global _SENTENCE_GAP_RE
	if _SENTENCE_GAP_RE is None:
		# End of sentence characters (. ! ?) followed immediately by
		# an uppercase letter or one of the common lowercase starters.
		_SENTENCE_GAP_RE = re.compile(
			r'([.!?])([A-Z"\'\(]|l(?:et|ook)|n(?:ow|o)|t(?:he|his|hat)|i[tf]|w(?:e|hen|hile|ith)|y(?:ou|es)|s(?:o|ee|ince)|h(?:e|ere|ow|owever)|a(?:fter|nd|s)|b(?:ut|y)|f(?:or|rom)|o(?:n|r)|in|at|that)'
		)

	return _SENTENCE_GAP_RE.sub(r'\1 \2', text)


# ---------------------------------------------------------------------------
# Formatting conversion: Standard Markdown → vue-advanced-chat delimiters
# ---------------------------------------------------------------------------
# vue-advanced-chat uses *text* for bold and _text_ for italic, while the
# LLM emits standard Markdown **text** for bold and *text* for italic.
# Without conversion, "**bold**" is parsed as: open-bold (*), literal "bold",
# close-bold (*), leaving a stray "*" that corrupts adjacent characters.
#
# Compiled at module level; lazy-initialised on first call.
_CODE_SEGMENT_RE = None   # matches fenced blocks and inline code spans
_BOLD_ITALIC_RE = None    # ***text***
_BOLD_RE = None           # **text**
_ITALIC_RE = None         # *text*  (not list bullets, not **bold**)
_HEADING_RE = None        # # heading
_LINK_RE = None           # [text](url)
_IMAGE_RE = None          # ![alt](url)
_BLOCKQUOTE_RE = None     # > quote
_HR_RE = None             # ---, ***, ___
_STRIKE_RE = None         # ~~text~~
_UNDERLINE_RE = None      # °text°


def _convert_formatting_for_vue_chat(text: str) -> str:
	"""Convert standard Markdown to vue-advanced-chat formatting.

	vue-advanced-chat renders:
	  *text*   → bold
	  _text_   → italic
	  ~text~   → strikethrough
	  °text°   → underline
	  `code`   → inline code
	  ```code``` → multiline code

	Standard Markdown (what the LLM outputs):
	  **text**   → bold
	  *text*     → italic
	  ***text*** → bold + italic
	  ~~text~~   → strikethrough
	  # Heading → bold
	  [text](url) → text (url)
	  ![alt](url) → [Image: alt] (url)
	  > quote   → italic
	  ---       → separator line

	Conversion order applied to non-code segments:
	  1. *italic*       → _italic_   (before bold so lone * are handled first)
	  2. ***bold+ital***→ *_bold+ital_*
	  3. **bold**       → *bold*
	  4. ~~strike~~     → ~strike~
	  5. °underline°    → °underline° (passthrough, already correct)
	  6. # Heading      → *Heading*
	  7. [text](url)    → text (url)
	  8. ![alt](url)    → [Image: alt] (url)
	  9. > quote        → _quote_
	  10. ---/***/___   → separator line

	Code spans (``code``) and fenced blocks (```...```) are left untouched.
	List bullets (``* item``) are excluded by requiring the opening ``*``
	not be followed by whitespace.
	"""
	import re

	global _CODE_SEGMENT_RE, _BOLD_ITALIC_RE, _BOLD_RE, _ITALIC_RE
	global _STRIKE_RE, _UNDERLINE_RE, _HEADING_RE, _LINK_RE, _IMAGE_RE, _BLOCKQUOTE_RE, _HR_RE
	if _CODE_SEGMENT_RE is None:
		# Fenced code blocks (``` ... ```) or inline code (`code`).
		# Use [\s\S] for fenced blocks so newlines are included.
		_CODE_SEGMENT_RE = re.compile(r'(```[\s\S]*?```|`[^`\n]+`)')
		# ***bold-italic***: three asterisks on each side
		_BOLD_ITALIC_RE = re.compile(r'\*\*\*(.+?)\*\*\*')
		# **bold**: two asterisks on each side
		_BOLD_RE = re.compile(r'\*\*(.+?)\*\*')
		# *italic*: single asterisk, not adjacent to another *, not followed
		# by whitespace (excludes list bullets like "* item").
		_ITALIC_RE = re.compile(r'(?<!\*)\*(?!\*|\s)(.+?)(?<!\s)\*(?!\*)')
		# ~~strikethrough~~
		_STRIKE_RE = re.compile(r'~~(.+?)~~')
		# °underline° (vue-chat native format, passthrough)
		_UNDERLINE_RE = re.compile(r'°(.+?)°')
		# # Heading (1-6 # characters, must be at start of line)
		_HEADING_RE = re.compile(r'^#{1,6}\s+(.+?)(?:\s*#+\s*)?$', re.MULTILINE)
		# [text](url) — not inside a < or > to avoid false matches
		_LINK_RE = re.compile(r'(?<![<\[!])\[([^\]]+)\]\(([^)]+)\)')
		# ![alt](url)
		_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
		# > blockquote (at start of line, optional leading spaces)
		_BLOCKQUOTE_RE = re.compile(r'^>\s?(.+)$', re.MULTILINE)
		# Horizontal rules: ---, ***, ___ (3+ chars, optionally with spaces, on own line)
		_HR_RE = re.compile(r'^[ \t]*([-*_])[ \t]*\1[ \t]*\1[ \t]*\1*[ \t]*$', re.MULTILINE)

	parts = _CODE_SEGMENT_RE.split(text)
	result = []
	for i, part in enumerate(parts):
		if i % 2 == 1:
			# Odd index → matched by the regex → code segment, leave as-is.
			result.append(part)
		else:
			# 1. Italic first: convert *italic* → _italic_
			#    The italic regex skips ** and *** patterns so they remain
			#    intact for the next steps.
			part = _ITALIC_RE.sub(r'_\1_', part)
			# 2. Bold-italic: ***text*** → *_text_*
			part = _BOLD_ITALIC_RE.sub(r'*_\1_*', part)
			# 3. Bold: **text** → *text*
			part = _BOLD_RE.sub(r'*\1*', part)
			# 4. Strikethrough: ~~text~~ → ~text~
			part = _STRIKE_RE.sub(r'~\1~', part)
			# 5. Underline: °text° → °text° (passthrough, already correct)
			# 6. Headings: # Title → *Title*
			part = _HEADING_RE.sub(r'*\1*', part)
			# 7. Links: [text](url) → text (url)
			part = _LINK_RE.sub(r'\1 (\2)', part)
			# 8. Images: ![alt](url) → [Image: alt] (url)
			part = _IMAGE_RE.sub(r'[Image: \1] (\2)', part)
			# 9. Blockquotes: > text → _text_
			part = _BLOCKQUOTE_RE.sub(r'_\1_', part)
			# 10. Horizontal rules: --- → separator line
			part = _HR_RE.sub(r'⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯', part)
			result.append(part)
	return ''.join(result)


def _fix_agent_response_text(text: str) -> str:
	"""Clean up agent response text by applying known post-processing fixes."""
	if not text:
		return text
	text = _fix_missing_sentence_spaces(text)
	return _convert_formatting_for_vue_chat(text)


# ---------------------------------------------------------------------------
# Per-turn tool routing helpers
# ---------------------------------------------------------------------------


def _extract_text_from_messages(messages) -> str:
	"""Extract the first user text from a Message or list of Messages."""
	msg_list = messages if isinstance(messages, list) else [messages]
	for msg in msg_list:
		for c in (getattr(msg, 'contents', None) or []):
			text = getattr(c, 'text', None)
			if text:
				return str(text)
	return ""


def _get_available_tool_names(agent: Agent) -> set[str]:
	"""Extract the set of tool names from an agent's tool list.

	Handles ``FunctionTool``, ``MCPTool``, and any object with a ``name``
	attribute. Returns an empty set if no tools are configured.
	"""
	names: set[str] = set()
	tools = agent.default_options.get("tools", [])
	for t in tools:
		name = getattr(t, "name", None)
		if name:
			names.add(str(name))
	return names


async def _try_route_tools(agent, session_name: str, user_query: str) -> None:
	"""Filter ``agent.default_options['tools']`` using a cheap router LLM call.

	All tools are treated equally — the router decides per-tool which ones
	are relevant to the current query. No group-based exemptions.

	Only activates when:
	  1. Persona has ``enable_tool_routing=1`` and not ``disable_tools``.
	  2. Tool count > ``_ROUTING_THRESHOLD`` (5).

	On failure or skip, leaves tools unchanged (safety-first).
	"""
	if not session_name or not user_query:
		return

	# Resolve persona and routing flag
	session_doc = frappe.get_doc("Chat Session", session_name)
	if not session_doc.persona:
		return

	persona_doc = frappe.get_doc("Persona", session_doc.persona)
	if not persona_doc.get("enable_tool_routing") or persona_doc.get("disable_tools"):
		return

	tools = agent.default_options.get("tools", [])
	if len(tools) <= _ROUTING_THRESHOLD:
		return

	# Build compact tool menu for ALL tools
	lines = []
	for t in tools:
		name = getattr(t, "name", "unknown")
		desc = (getattr(t, "description", "") or "").split("\n")[0][:120]
		lines.append(f"- {name}: {desc}")
	tool_menu = "\n".join(lines)

	# Call router LLM
	provider_doc = frappe.get_doc("LLM Provider", session_doc.llm_provider)
	api_key = provider_doc.get_password("api_key")
	if not api_key:
		return

	openai_client = AsyncOpenAI(
		api_key=api_key,
		base_url=provider_doc.api_url or "https://api.openai.com/v1",
	)

	import time
	route_start = time.time()
	try:
		user_content = (
			f"User message: {user_query}\n\n"
			f"Available tools:\n{tool_menu}\n\n"
			"Which tools are needed? Respond only with the JSON object."
		)
		response = await openai_client.chat.completions.create(
			model=provider_doc.default_model,
			messages=[
				{"role": "system", "content": _ROUTER_SYSTEM_PROMPT},
				{"role": "user", "content": user_content},
			],
			max_tokens=_ROUTER_MAX_TOKENS,
			temperature=0.0,
		)

		raw = (response.choices[0].message.content or "").strip()
		if raw.startswith("```"):
			raw = raw.split("```")[1]
			if raw.startswith("json"):
				raw = raw[4:]
			raw = raw.strip()

		data = json.loads(raw)
		selected_names = data.get("tool_names", [])
		if not isinstance(selected_names, list):
			selected_names = []

		selected_set = set(str(n) for n in selected_names)
		filtered = [t for t in tools if t.name in selected_set]

		agent.default_options["tools"] = filtered
		route_elapsed = time.time() - route_start
		debug_log(
			"_try_route_tools success",
			f"Session: {session_name}, Tools before: {len(tools)}, After: {len(filtered)}, "
			f"Elapsed: {route_elapsed:.2f}s",
			session=session_name,
		)
	except Exception:
		route_elapsed = time.time() - route_start
		debug_log(
			"_try_route_tools failed",
			f"Session: {session_name}, Elapsed: {route_elapsed:.2f}s — keeping all tools",
			session=session_name,
			level="WARNING",
		)
		pass  # Safety-first: keep all tools on failure



# ---------------------------------------------------------------------------


# Custom instruction template for SkillsProvider.
# Softens the default "follow these steps in exact order: load_skill first" instruction
# so that skills are treated as optional reference material rather than a mandatory
# first step. The agent should follow its primary instructions (system prompt) and
# only load a skill when it needs additional domain-specific guidance.
_CUSTOM_SKILLS_TEMPLATE = """\
You have access to skills containing domain-specific knowledge and capabilities.
Each skill provides specialized instructions, reference documents, and assets for specific tasks.

<available_skills>
{skills}
</available_skills>

If you need additional guidance beyond your primary instructions, you may use the
skills below. When a task aligns with a skill's domain, you can optionally:
- Use `load_skill` to retrieve the skill's instructions.
- Follow the provided guidance.
- Use `read_skill_resource` to read any referenced resources, using the name exactly as listed
   (e.g. `"style-guide"` not `"style-guide.md"`, `"references/FAQ.md"` not `"FAQ.md"`).
{runner_instructions}
Only load what is needed, when it is needed."""


def _build_skills_provider() -> SkillsProvider:
	"""Build a SkillsProvider with both file-based and DocType-based skills.

	File-based skills are auto-discovered from the site's ``private/files/skills/``
	directory. DocType-based skills (code-defined) come from the Skill Registry.

	When a DocType skill has the same name as a file-based skill, DocType
	takes precedence — the file-based skill directory with the matching name
	is excluded.
	"""
	# Get enabled DocType skill names
	code_skills = get_code_skills()
	doctype_skill_names = set(s.name for s in code_skills)

	# Resolve the site's private files path
	site_path = Path(frappe.get_site_path())
	skills_dir = site_path / "private" / "files" / "skills"

	# Determine file-based skill paths. Only exclude file-based skills when a
	# DocType skill with the same name exists AND is enabled, so the DocType
	# version takes precedence.
	skill_paths = None
	if skills_dir.exists():
		all_dirs = [str(d) for d in skills_dir.iterdir() if d.is_dir()]
		filtered_dirs = [
			d for d in all_dirs
			if Path(d).name not in doctype_skill_names
		]
		skill_paths = filtered_dirs if filtered_dirs else None

	debug_log(
		"_build_skills_provider",
		f"DocType skills: {len(code_skills)}, File-based dirs: {len(skill_paths) if skill_paths else 0}",
	)

	return SkillsProvider(
		skill_paths=skill_paths,
		skills=code_skills,
		require_script_approval=True,
		script_runner=run_file_script,
		instruction_template=_CUSTOM_SKILLS_TEMPLATE,
	)


class FrappeMemoryProvider(HistoryProvider):
	"""History provider backed by Chat Message DocType."""

	def __init__(self) -> None:
		super().__init__("frappe_history")

	async def get_messages(
		self,
		session_id: str | None,
		*,
		state: dict[str, Any] | None = None,
		**kwargs: Any,
	) -> list[Message]:
		if not session_id:
			return []

		last_summary_message = frappe.db.get_value("Chat Session", session_id, "last_summary_message")
		if last_summary_message:
			last_summary_doc = frappe.get_doc("Chat Message", last_summary_message)
			prior_messages = frappe.get_all(
				"Chat Message",
				filters={"chat_session": session_id, "creation": [">=", last_summary_doc.creation]},
				fields=["sender_type", "content", "message_type", "reasoning_content"],
				order_by="creation asc",
			)
		else:
			prior_messages = frappe.get_all(
				"Chat Message",
				filters={"chat_session": session_id},
				fields=["sender_type", "content", "message_type", "reasoning_content"],
				order_by="creation asc",
			)

		history: list[Message] = []
		for msg in prior_messages:
			content = msg.content or ""
			if "⏳ Generating response" in content:
				continue
			if msg.message_type == "Summary":
				history.append(Message("system", [f"Conversation summary: {content}"]))
			elif msg.sender_type == "User":
				history.append(Message("user", [content]))
			else:
				assistant_msg = Message("assistant", [content])
				if msg.reasoning_content:
					debug_log(
						"FrappeMemoryProvider: loaded reasoning_content",
						f"Session: {session_id}, Reasoning length: {len(msg.reasoning_content)}",
						session=session_id,
					)
					assistant_msg.contents.append(
						Content.from_text_reasoning(
							protected_data=json.dumps(msg.reasoning_content)
						)
					)
				history.append(assistant_msg)

		# Strip non-text content types from assistant messages in history.
		# Tool call/result pairs (function_call, function_result) exist only
		# in-memory during execution and are not persisted to the DB.
		# Reasoning tokens (text_reasoning) ARE persisted and MUST be preserved
		# because DeepSeek's thinking mode requires reasoning_content to be
		# echoed back in subsequent requests.
		filtered: list[Message] = []
		for msg in history:
			if msg.role == "assistant":
				allowed = [c for c in msg.contents if getattr(c, "type", None) in ("text", "text_reasoning")]
				if allowed:
					msg.contents = allowed
					filtered.append(msg)
				# Drop assistant messages with no text or reasoning content (e.g. tool-only turns)
			else:
				filtered.append(msg)
		return filtered

	async def save_messages(
		self,
		session_id: str | None,
		messages: Sequence[Message],
		*,
		state: dict[str, Any] | None = None,
		**kwargs: Any,
	) -> None:
		# Chat messages are persisted by the existing Frappe API layer.
		return


def _get_usage_tokens(usage_details: dict[str, Any] | None) -> tuple[int, int, int]:
	"""Extract token counts from usage_details.

	Returns:
		tuple of (input_tokens, output_tokens, cache_hit_tokens).
	"""
	if not usage_details:
		return 0, 0, 0
	input_tokens = usage_details.get("input_token_count") or 0
	output_tokens = usage_details.get("output_token_count") or 0
	# agent_framework_openai maps prompt_tokens_details.cached_tokens → "prompt/cached_tokens"
	cache_hit_tokens = usage_details.get("prompt/cached_tokens") or 0
	return int(input_tokens), int(output_tokens), int(cache_hit_tokens)


def _credit_auxiliary_api_tokens(session_name: str, usage, label: str = "auxiliary") -> None:
	"""Credit token usage from auxiliary API calls (title, suggestions, summary).

	These calls bypass the agent framework so tokens must be tracked here.
	Reads provider pricing + user overrides and credits User Token Usage.
	Also updates Chat Session counters.

	Args:
		session_name: Chat Session name.
		usage: OpenAI CompletionUsage object with prompt_tokens,
		       completion_tokens, and prompt_tokens_details.cached_tokens.
		label: Human-readable label for error logging.
	"""
	try:
		input_tokens = usage.prompt_tokens or 0
		output_tokens = usage.completion_tokens or 0
		cache_hit_tokens = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None) or 0
		if not input_tokens and not output_tokens:
			return

		session_doc = frappe.get_doc("Chat Session", session_name)
		user = session_doc.user
		provider_name = session_doc.llm_provider
		provider = frappe.get_doc("LLM Provider", provider_name)

		# Pricing
		provider_input_rate = float(provider.input_cost_per_1m_tokens or 0)
		provider_output_rate = float(provider.output_cost_per_1m_tokens or 0)
		provider_cache_rate = float(provider.cache_hit_cost_per_1m_tokens or 0)

		# User token usage record (get or create)
		from ph_agent.ph_agent.doctype.user_token_usage.user_token_usage import UserTokenUsage
		usage_name = UserTokenUsage.get_or_create_for_user(user)
		usage_doc = frappe.get_doc("User Token Usage", usage_name)
		override_input = float(usage_doc.input_cost_over_per_1m or 0)
		override_output = float(usage_doc.output_cost_over_per_1m or 0)
		override_cache = float(usage_doc.cache_hit_cost_over_per_1m or 0)

		# Effective rates
		eff_input = provider_input_rate + override_input
		eff_output = provider_output_rate + override_output
		eff_cache = provider_cache_rate + override_cache

		# 3-tier cost
		cache_miss = max(0, input_tokens - cache_hit_tokens)
		cost = (cache_miss * eff_input + cache_hit_tokens * eff_cache + output_tokens * eff_output) / 1_000_000

		# Atomic updates — increment counters directly in SQL to avoid races
		_atomic_update_user_token_usage(usage_name, input_tokens, output_tokens, cache_hit_tokens, cost)
		_atomic_update_chat_session_tokens(session_name, input_tokens, output_tokens, cache_hit_tokens)
	except Exception:
		frappe.log_error(
			title=f"Failed to credit auxiliary API tokens ({label})",
			message=f"Session: {session_name}",
		)


def _validate_context_limit(session_doc, provider_doc) -> int:
	context_length = provider_doc.context_length or 128000
	estimated_tokens = session_doc.estimated_conversation_tokens or 0
	max_tokens = provider_doc.max_output_tokens or 32768

	if estimated_tokens + max_tokens > context_length:
		frappe.throw(
			frappe._(
				"Conversation would exceed context limit. Current: {0:,} tokens, Limit: {1:,} tokens, This call needs: ~{2:,} tokens. "
				"Please summarize the conversation first."
			).format(estimated_tokens, context_length, max_tokens)
		)

	return max_tokens


def _reference_enrich_title(session_doc) -> None:
	"""Enrich the session title based on the referenced document.

	If ``reference_doctype`` and ``reference_name`` are set, reads the
	referenced document's ``title_field`` and prepends it to the session
	title (e.g. "Growth Portfolio — New Chat").  Uses ``frappe.db.set_value``
	for a lightweight write without loading the full document.

	Idempotent: if the title already starts with the reference value, no
	change is made (prevents repeated prepends on subsequent calls).
	"""
	ref_doctype = session_doc.get("reference_doctype")
	ref_name = session_doc.get("reference_name")
	if not ref_doctype or not ref_name:
		return

	try:
		# Resolve the title field for this doctype
		meta = frappe.get_meta(ref_doctype)
		title_field = meta.get("title_field") or "name"
		title_value = frappe.db.get_value(ref_doctype, ref_name, title_field)
		if title_value:
			# Idempotency check: skip if title already starts with the reference value
			current_title = session_doc.title or "New Chat"
			if current_title.startswith(f"{title_value} — "):
				return
			new_title = f"{title_value} — {current_title}"
			frappe.db.set_value("Chat Session", session_doc.name, "title", new_title)
			session_doc.title = new_title
	except Exception:
		logger.exception("Failed to enrich title from %s %s", ref_doctype, ref_name)


def _build_instructions(session_doc) -> str | None:
	"""Assemble the agent instructions from system_prompt and cross_session_context.

	The system_prompt holds the clean inherited prompt (provider → persona).
	The cross_session_context holds previous-session summaries injected at session
	creation. These are combined here at build-time so each field stays semantically
	clean in the database.
	"""
	system_prompt = session_doc.system_prompt or ""
	cross_context = session_doc.get("cross_session_context") or ""

	if cross_context and system_prompt:
		return f"{cross_context}\n\n---\n\n{system_prompt}"
	if cross_context:
		return cross_context
	return system_prompt or None


def _build_agent(session_name: str, user: str | None = None) -> Agent:
	debug_log(
		"_build_agent entry",
		f"Session: {session_name}, User: {user or frappe.session.user}, Persona: {frappe.get_doc('Chat Session', session_name).persona}",
		session=session_name,
	)
	session_doc = frappe.get_doc("Chat Session", session_name)
	provider_doc = frappe.get_doc("LLM Provider", session_doc.llm_provider)
	api_key = provider_doc.get_password("api_key")
	if not api_key:
		frappe.throw(
			frappe._("API key not configured for provider {0}. Please update the LLM Provider record.").format(
				provider_doc.name
			)
		)
	if not provider_doc.is_enabled:
		frappe.throw(
			frappe._("LLM Provider {0} is disabled. Please enable it or select a different provider.").format(
				provider_doc.name
			)
		)

	max_tokens = _validate_context_limit(session_doc, provider_doc)

	# Resolve thinking mode: session override (1=force on) takes precedence
	# When session override is 0, inherit from provider setting
	if session_doc.enable_thinking:
		enable_thinking = True
	else:
		enable_thinking = bool(provider_doc.enable_thinking)

	temperature = (
		session_doc.temperature
		if session_doc.temperature is not None
		else provider_doc.temperature
		if provider_doc.temperature is not None
		else 1.0
	)
	tools = ToolManager.get_tools(session_name=session_name, user=user or frappe.session.user, persona=session_doc.persona)

	chat_client = OpenAIChatCompletionClient(
		model=provider_doc.default_model,
		api_key=api_key,
		base_url=provider_doc.api_url,
	)

	# Build default_options — skip temperature when thinking is enabled (ignored by DeepSeek)
	default_options = {"max_tokens": max_tokens}
	if enable_thinking:
		default_options["extra_body"] = {"thinking": {"type": "enabled"}}
		default_options["reasoning_effort"] = provider_doc.reasoning_effort or "high"
	else:
		default_options["temperature"] = temperature
		default_options["extra_body"] = {"thinking": {"type": "disabled"}}

	# Auto-title enrichment: if reference_doctype and reference_name are set,
	# read the document's title field and optionally prefix the session title.
	_reference_enrich_title(session_doc)

	# Build skills provider from both file-based and DocType-based sources
	skills_provider = _build_skills_provider()

	# Build base context providers (always present)
	context_providers: list = [
		# FrappeMemoryProvider handles all conversation history via the
		# Chat Message DocType.  InMemoryHistoryProvider is intentionally
		# omitted — having both would duplicate messages in the context
		# and produce malformed conversations (e.g. orphaned tool_calls
		# without matching tool results), triggering 400 errors from the
		# LLM provider.
		FrappeMemoryProvider(),
		skills_provider,
		UserPreferenceProvider(),
		LLMMemoryProvider(),
	]

	# Load hook-registered context providers from other apps.
	# Each entry in ph_agent_context_providers is a dotted path to a
	# ContextProvider subclass.  The hook receives the session doc so
	# providers can decide whether to activate based on reference fields.
	_hook_providers = frappe.get_hooks("ph_agent_context_providers") or []
	for dotted_path in _hook_providers:
		try:
			cls = frappe.get_attr(dotted_path)
			provider_instance = cls(session_doc=session_doc)
			context_providers.append(provider_instance)
		except Exception:
			logger.exception("Failed to load context provider: %s", dotted_path)

	return Agent(
		client=chat_client,
		instructions=_build_instructions(session_doc),
		tools=tools,
		default_options=default_options,
		context_providers=context_providers,
	)


def _load_session_state(session_name: str) -> dict[str, Any]:
	"""Load session state from Chat Session DocType.

	Uses ``AgentSession.from_dict()`` to properly restore ``SerializationProtocol``
	objects (e.g. ``Message`` instances from ``InMemoryHistoryProvider``) so that
	provider state survives server restarts.
	"""
	try:
		session_doc = frappe.get_doc("Chat Session", session_name)
		if session_doc.session_state:
			data = json.loads(session_doc.session_state)
			state_size = len(session_doc.session_state)
			debug_log(
				"_load_session_state",
				f"Session: {session_name}, State size: {state_size} bytes",
				session=session_name,
			)
			# Restore full AgentSession with proper object deserialization
			restored = AgentSession.from_dict(data)
			return restored.state
		debug_log(
			"_load_session_state",
			f"Session: {session_name}, No session state found",
			session=session_name,
		)
		return {}
	except Exception as e:
		import traceback
		frappe.log_error(
			title="Error loading session state",
			message=f"Session: {session_name}, Error: {e}\n{traceback.format_exc()}"
		)
		return {}



class LoggingEncoder(json.JSONEncoder):
	"""JSON encoder that logs warnings for non-standard types instead of silently stringifying."""

	def default(self, obj):
		if isinstance(obj, (str, int, float, bool, type(None), list, dict)):
			return super().default(obj)
		logger.warning(
			"_save_session_state: non-standard type %s encountered during JSON serialization",
			type(obj).__name__,
		)
		try:
			return super().default(obj)
		except TypeError:
			return str(obj)


def _save_session_state(session_name: str, session: AgentSession) -> None:
	"""Save session state to Chat Session DocType.

	Uses ``AgentSession.to_dict()`` for proper round-trip serialization of all
	provider state (including ``InMemoryHistoryProvider`` messages), then stores
	as JSON in the ``session_state`` field.

	Uses ``frappe.db.set_value`` to avoid TimestampMismatchError from concurrent
	saves (e.g. streaming producer thread vs. main thread updating token counts).
	"""
	try:
		if not session:
			return

		serialized = session.to_dict()
		if not serialized:
			return

		state_json = json.dumps(serialized, indent=2, cls=LoggingEncoder)
		debug_log(
			"_save_session_state",
			f"Session: {session_name}, State size: {len(state_json)} bytes",
			session=session_name,
		)

		frappe.db.set_value(
			"Chat Session",
			session_name,
			{
				"session_state": state_json,
				"last_state_update": frappe.utils.now(),
			},
		)
	except Exception as e:
		import traceback
		frappe.log_error(
			title="Error saving session state",
			message=f"Session: {session_name}, Error: {e}\n{traceback.format_exc()}"
		)


def _extract_approval_data(response, session_name: str | None = None) -> dict[str, Any] | None:
	"""Extract approval data from an agent response.

	If ``session_name`` is provided, validates that each tool being approved
	actually exists in the current session's tool set. Tools not in the set
	are silently skipped (the LLM hallucinated them), preventing spurious
	approval requests for tools the persona cannot use.
	"""
	# Pre-resolve available tool names if session_name is given
	available_tools: set[str] | None = None
	if session_name:
		try:
			temp_agent = _build_agent(session_name=session_name)
			available_tools = _get_available_tool_names(temp_agent)
		except Exception:
			available_tools = None  # Fall back to no filtering

	approval_requests: list[dict[str, str]] = []
	tool_calls: list[dict[str, str]] = []

	for msg in response.messages:
		for content in msg.contents:
			if content.type != "function_approval_request" or not content.function_call:
				continue
			function_call = content.function_call
			tool_name = function_call.name or ""

			# Skip tools that don't exist in the current session's tool set
			if available_tools is not None and tool_name and tool_name not in available_tools:
				logger.warning(
					"Skipping approval request for tool '%s' — not in session's tool set.",
					tool_name,
				)
				continue

			arguments = function_call.arguments
			
			# Handle arguments - they could be dict, string, or string containing JSON
			if isinstance(arguments, dict):
				arguments_str = json.dumps(arguments)
			elif isinstance(arguments, str):
				# Try to parse as JSON first
				try:
					parsed = json.loads(arguments)
					if isinstance(parsed, dict):
						arguments_str = json.dumps(parsed)
					else:
						# Not a dict, store as string
						arguments_str = arguments
				except (json.JSONDecodeError, TypeError):
					# Not valid JSON, store as string
					arguments_str = arguments or "{}"
			else:
				# Convert other types to string
				arguments_str = str(arguments) if arguments is not None else "{}"
			
			approval_requests.append(
				{
					"id": content.id or "",
					"call_id": function_call.call_id or "",
					"name": function_call.name or "",
					"arguments": arguments_str,
				}
			)
			tool_calls.append(
				{
					"id": function_call.call_id or "",
					"name": function_call.name or "",
					"arguments": arguments_str,
				}
			)

	if not approval_requests:
		return None

	return {
		"approval_needed": True,
		"tool_calls": tool_calls,
		"conversation_state": {"approval_requests": approval_requests},
	}


def _run_agent(session_name: str, message: Message | list, user: str | None = None, session_state: dict[str, Any] | None = None) -> tuple[Any, AgentSession]:
	"""Run agent (non-streaming) and return (response, agent_session).

	If ``session_state`` is provided, it is loaded into a fresh ``AgentSession``
	so that provider state (including ``InMemoryHistoryProvider`` messages)
	survives across invocations.
	"""
	user_text = _extract_text_from_messages(message if isinstance(message, list) else [message])
	debug_log(
		"_run_agent entry",
		f"Session: {session_name}, Message length: {len(user_text)}, Has session_state: {session_state is not None}",
		session=session_name,
	)
	agent = _build_agent(session_name=session_name, user=user)
	agent_session = AgentSession(session_id=session_name)
	if session_state:
		agent_session.state.update(session_state)
	messages = message if isinstance(message, list) else [message]

	# Per-turn tool routing — filter before API call
	user_text = _extract_text_from_messages(messages)
	asyncio.run(_try_route_tools(agent, session_name, user_text))

	result = asyncio.run(agent.run(messages, session=agent_session))
	debug_log(
		"_run_agent complete",
		f"Session: {session_name}, Tokens: {_get_usage_tokens(result.usage_details)}",
		session=session_name,
	)
	# Debug-log the raw usage_details keys to confirm cache token field name
	if result.usage_details:
		debug_log(
			"_run_agent usage_details keys",
			f"Session: {session_name}, Keys: {list(result.usage_details.keys())}",
			session=session_name,
		)
	return result, agent_session


async def _run_agent_stream(session_name: str, message: Message | list, user: str | None = None, session_state: dict[str, Any] | None = None) -> tuple[Any, AgentSession]:
	"""Run agent with streaming support and return (stream, agent_session).

	If ``session_state`` is provided, it is loaded into a fresh ``AgentSession``
	so that provider state (including ``InMemoryHistoryProvider`` messages)
	survives across invocations.
	"""
	user_text = _extract_text_from_messages(message if isinstance(message, list) else [message])
	debug_log(
		"_run_agent_stream entry",
		f"Session: {session_name}, Message length: {len(user_text)}, Has session_state: {session_state is not None}",
		session=session_name,
	)
	agent = _build_agent(session_name=session_name, user=user)
	agent_session = AgentSession(session_id=session_name)
	if session_state:
		agent_session.state.update(session_state)
	messages = message if isinstance(message, list) else [message]

	# Per-turn tool routing — filter before API call
	user_text = _extract_text_from_messages(messages)
	await _try_route_tools(agent, session_name, user_text)

	stream = agent.run(messages, session=agent_session, stream=True)
	if inspect.isawaitable(stream):
		stream = await stream
	debug_log(
		"_run_agent_stream complete",
		f"Session: {session_name}, Stream obtained",
		session=session_name,
	)
	return stream, agent_session


def _extract_reasoning_from_response(response) -> str:
	"""Extract reasoning content from a non-streaming agent response."""
	reasoning_parts = []
	for msg in getattr(response, 'messages', []) or []:
		for content in getattr(msg, 'contents', []) or []:
			if getattr(content, 'type', None) == "text_reasoning":
				# Prefer protected_data (JSON-encoded), fall back to text
				if content.protected_data:
					try:
						reasoning_parts.append(json.loads(content.protected_data))
					except (json.JSONDecodeError, TypeError):
						reasoning_parts.append(content.protected_data)
				else:
					reasoning_parts.append(content.text or "")
	return "\n".join(reasoning_parts)


def get_agent_response(session_name: str, user_message: str, cancel_check=None, skip_session_state: bool = False) -> tuple[str, int, int, int, dict | None, str]:
	"""Get agent response (non-streaming).

	Args:
		session_name: Chat Session name.
		user_message: The user message text.
		cancel_check: Optional callable to check for cancellation.
		skip_session_state: If True, skip loading cached session state
			(e.g. InMemoryHistoryProvider messages). Used during regeneration
			to prevent stale messages from leaking into the new context.
	
	Returns:
		tuple of (response_text, input_tokens, output_tokens, cache_hit_tokens, approval_data, reasoning_content)
	"""
	if cancel_check and cancel_check():
		raise asyncio.CancelledError()

	# Load session state before running agent (skip for regeneration)
	stored_state = None if skip_session_state else _load_session_state(session_name)
	
	response, agent_session = _run_agent(session_name, Message("user", [user_message]), session_state=stored_state)

	if cancel_check and cancel_check():
		raise asyncio.CancelledError()

	input_tokens, output_tokens, cache_hit_tokens = _get_usage_tokens(response.usage_details)
	approval_data = _extract_approval_data(response, session_name=session_name)
	reasoning_content = _extract_reasoning_from_response(response)
	
	# Always save session state, regardless of approval flow
	_save_session_state(session_name, agent_session)
	
	if approval_data and agent_session.state:
		# Also store full session dict in approval data for continuation.
		# run_after_approval will reconstruct the AgentSession from this.
		approval_data["conversation_state"]["session_state"] = agent_session.to_dict()
	
	return _fix_agent_response_text(response.text or ""), input_tokens, output_tokens, cache_hit_tokens, approval_data, reasoning_content


def get_agent_response_stream(
	session_name: str,
	user_message: str,
	cancel_check=None,
	status_callback=None,
	skip_session_state: bool = False,
) -> Generator[tuple[Any, bool, int, int, int], None, None]:
	"""Stream agent response.

	Yields:
		tuples of (chunk, is_final, input_tokens, output_tokens, cache_hit_tokens).
	"""
	if status_callback:
		status_callback(frappe._("Calling AI…"))

	site_name = getattr(frappe.local, "site", None)
	active_user = getattr(frappe.session, "user", None)

	result_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
	stop_event = threading.Event()

	def _producer() -> None:
		async def _consume() -> None:
			try:
				# Load session state before running agent (skip for regeneration)
				stored_state = None if skip_session_state else _load_session_state(session_name)
				
				# Use streaming agent runner — returns (stream, AgentSession)
				stream, agent_session = await _run_agent_stream(
					session_name, 
					Message("user", [user_message]), 
					session_state=stored_state
				)

				seen_text = ""
				seen_reasoning = ""
				chunk_count = 0
				reasoning_chunk_count = 0

				async for update in stream:
					if stop_event.is_set():
						break

					if hasattr(update, 'contents') and update.contents:
						for c in update.contents:
							c_type = getattr(c, 'type', 'unknown')
							if c_type == "text_reasoning":
								# Prefer protected_data (JSON-encoded), fall back to text
								if c.protected_data:
									try:
										reasoning_text = json.loads(c.protected_data)
									except (json.JSONDecodeError, TypeError):
										reasoning_text = c.protected_data
								else:
									reasoning_text = c.text or ""
								if reasoning_text.startswith(seen_reasoning):
									reasoning_delta = reasoning_text[len(seen_reasoning):]
									seen_reasoning = reasoning_text
								else:
									reasoning_delta = reasoning_text
									seen_reasoning += reasoning_delta
								if reasoning_delta:
									reasoning_chunk_count += 1
									result_queue.put(("reasoning_chunk", reasoning_delta))
							elif c_type not in ("text", "function_call", "function_result"):
								pass

					chunk = update.text or ""
					if not chunk:
						continue

					# Some providers emit cumulative text in each update; convert to deltas.
					if chunk.startswith(seen_text):
						delta = chunk[len(seen_text) :]
						seen_text = chunk
					else:
						delta = chunk
						seen_text += delta

					if not delta:
						continue

					chunk_count += 1

					# Emit in moderately-sized pieces for smooth UI rendering.
					for idx in range(0, len(delta), 500):
						result_queue.put(("chunk", delta[idx : idx + 500]))

				if stop_event.is_set():
					result_queue.put(("done", ("", 0, 0, 0)))
					return

				debug_log(
					"Stream: awaiting final_response",
					f"Session: {session_name}, Chunks streamed: {chunk_count}, Reasoning chunks: {reasoning_chunk_count}",
					session=session_name,
				)
				final_response = await stream.get_final_response()
				# Debug: dump all usage_details keys to find cache token field
				if final_response.usage_details:
					debug_log(
						"Stream: usage_details keys",
						f"Session: {session_name}, Keys: {list(final_response.usage_details.keys())}",
						session=session_name,
					)
				input_tokens, output_tokens, cache_hit_tokens = _get_usage_tokens(final_response.usage_details)
				debug_log(
					"Stream: final_response received",
					f"Session: {session_name}, Input tokens: {input_tokens}, Output tokens: {output_tokens}, Cache hit tokens: {cache_hit_tokens}",
					session=session_name,
				)
				approval_data = _extract_approval_data(final_response, session_name=session_name)
				
				# Always save session state, regardless of approval flow
				_save_session_state(session_name, agent_session)
				
				if approval_data:
					# Also store full session dict in approval data for continuation.
					# run_after_approval will reconstruct the AgentSession from this.
					approval_data["conversation_state"]["session_state"] = agent_session.to_dict()
					result_queue.put(("approval", (approval_data, input_tokens, output_tokens, cache_hit_tokens)))
				else:
					result_queue.put(("done", ("", input_tokens, output_tokens, cache_hit_tokens)))
			except Exception as exc:
				result_queue.put(("error", exc))

		initialized = False
		try:
			if site_name:
				frappe.init(site=site_name)
				frappe.connect()
				initialized = True
				if active_user:
					frappe.set_user(active_user)
			asyncio.run(_consume())
		except Exception as exc:
			# Catch thread-level crashes (e.g. asyncio.run failure, frappe.init
			# failure) that the inner _consume() except doesn't cover, so the
			# main thread gets the error instead of hanging forever.
			import traceback
			frappe.log_error(
				title="Streaming producer thread crashed",
				message=f"Session: {session_name}, Error: {exc}\n{traceback.format_exc()}",
			)
			result_queue.put(("error", exc))
		finally:
			if initialized:
				# Commit any pending DB operations (e.g., UserPreferenceProvider saves)
				frappe.db.commit()
				frappe.destroy()

	thread = threading.Thread(target=_producer, daemon=True)
	thread.start()

	full_reasoning = ""

	while True:
		if cancel_check and cancel_check():
			stop_event.set()
			raise asyncio.CancelledError()

		# Guard against the producer thread dying silently — if the thread
		# is no longer alive and the queue is empty, something went wrong
		# in the producer that wasn't caught (e.g. a segfault in a C
		# extension, or the thread was killed externally).
		if not thread.is_alive() and result_queue.empty():
			import traceback
			error_msg = (
				f"Streaming producer thread died unexpectedly for session {session_name}. "
				"No error was placed in the result queue."
			)
			frappe.log_error(title="Streaming producer thread died silently", message=error_msg)
			raise RuntimeError(error_msg)

		try:
			event_type, payload = result_queue.get(timeout=0.2)
		except queue.Empty:
			continue

		if event_type == "reasoning_chunk":
			full_reasoning += payload
			yield ("reasoning_chunk", payload), False, 0, 0, 0
			continue
		if event_type == "chunk":
			yield payload, False, 0, 0, 0
			continue
		if event_type == "approval":
			approval_data, input_tokens, output_tokens, cache_hit_tokens = payload
			yield approval_data, True, input_tokens, output_tokens, cache_hit_tokens
			break
		if event_type == "done":
			chunk, input_tokens, output_tokens, cache_hit_tokens = payload
			yield (chunk, full_reasoning), True, input_tokens, output_tokens, cache_hit_tokens
			break
		if event_type == "error":
			raise payload


def run_after_approval(
	session_name: str,
	conversation_state: dict[str, Any],
	approved: bool,
	user: str | None = None,
) -> tuple[str, int, int, int, str]:
	import traceback
	
	approval_requests = (conversation_state or {}).get("approval_requests") or []
	if not approval_requests:
		return "", 0, 0

	approval = approval_requests[0]
	arguments_raw = approval.get("arguments") or "{}"
	try:
		arguments = json.loads(arguments_raw)
	except Exception as e:
		# If we can't parse as JSON, try to handle it as a string
		# Some arguments might be simple strings
		if isinstance(arguments_raw, str) and arguments_raw.strip():
			# Try to parse as JSON one more time with error handling
			try:
				arguments = json.loads(arguments_raw)
			except Exception:
				# If it's not valid JSON, treat it as a string argument
				arguments = {"input": arguments_raw}
		else:
			arguments = {}

	# Ensure arguments is a dictionary
	if not isinstance(arguments, dict):
		arguments = {"input": str(arguments)}

	approval_id = approval.get("id") or ""
	tool_name = approval.get("name") or ""

	try:
		# Recreate the inner function_call Content
		function_call = Content.from_function_call(
			call_id=approval.get("call_id") or "",
			name=tool_name,
			arguments=arguments,
		)
		# Recreate the function_approval_request Content (what was in the original assistant message)
		approval_request_content = Content.from_function_approval_request(
			id=approval_id,
			function_call=function_call,
		)
		# Create the approval response
		approval_response = Content.from_function_approval_response(
			approved=approved,
			id=approval_id,
			function_call=function_call,
		)
	except Exception as e:
		frappe.log_error(
			title=f"Error creating approval Content objects for {session_name}",
			message=f"Error: {str(e)}, Traceback: {traceback.format_exc()}"
		)
		raise

	# Get session state from conversation_state.
	# This is now a full AgentSession.to_dict() output (with "type": "session").
	# Reconstruct the AgentSession to extract the state dict with proper
	# SerializationProtocol objects restored.
	session_data = conversation_state.get("session_state", {})
	if isinstance(session_data, dict) and session_data.get("type") == "session":
		try:
			restored_session = AgentSession.from_dict(session_data)
			session_state = restored_session.state
		except Exception:
			session_state = session_data.get("state", {})
	else:
		session_state = session_data if isinstance(session_data, dict) else {}
	
	try:
		# --- Tool existence validation ---
		# Build a temporary agent to check whether the approved tool is
		# actually available in the current persona's tool set.  If the
		# LLM hallucinated a tool that isn't in the persona's groups, we
		# must NOT send the approval messages to the API — that would
		# produce a malformed conversation (assistant message with
		# tool_calls but no corresponding tool result), triggering a 400
		# "insufficient tool messages" error from the LLM provider.
		temp_agent = _build_agent(session_name=session_name, user=user)
		available_tools = _get_available_tool_names(temp_agent)
		tool_is_available = tool_name in available_tools

		if not tool_is_available:
			logger.warning(
				"Approved tool '%s' is not available in persona's tool set "
				"(session=%s, persona=%s). Injecting synthetic error result.",
				tool_name, session_name,
				getattr(frappe.get_doc("Chat Session", session_name), "persona", "N/A"),
			)
			frappe.log_error(
				title=f"Approved tool '{tool_name}' not available for session {session_name}",
				message=(
					f"Tool '{tool_name}' was approved but is not in the current persona's tool set.\n"
					f"Available tools: {sorted(available_tools)}\n"
					f"Session: {session_name}\n"
					f"Arguments: {json.dumps(arguments, indent=2)}"
				),
			)
			# Build a synthetic function_result with an error message so the
			# LLM can gracefully respond to the failure instead of crashing.
			error_result = Content.from_function_result(
				call_id=approval.get("call_id") or "",
				result=json.dumps({
					"error": True,
					"message": (
						f"The tool '{tool_name}' is not available for this session's persona. "
						f"Please use one of the available tools: {', '.join(sorted(available_tools))}."
					),
				}),
			)
			messages = [
				Message("assistant", [approval_request_content]),
				Message("user", [approval_response]),
				Message("tool", [error_result]),
			]
			response, agent_session = _run_agent(
				session_name,
				messages,
				user=user,
				session_state=session_state,
			)
		else:
			# Per the Microsoft Agent Framework documentation, provide:
			# 1. The assistant message containing the original function_approval_request
			# 2. The user message containing the function_approval_response
			# The original user query is supplied automatically by FrappeMemoryProvider.
			messages = [
				Message("assistant", [approval_request_content]),
				Message("user", [approval_response]),
			]
			response, agent_session = _run_agent(
				session_name, 
				messages,  # Pass both messages
				user=user,
				session_state=session_state,
			)

		input_tokens, output_tokens, cache_hit_tokens = _get_usage_tokens(response.usage_details)
		reasoning_content = _extract_reasoning_from_response(response)
		
		# Save updated session state to Chat Session
		_save_session_state(session_name, agent_session)
		
		return _fix_agent_response_text(response.text or ""), input_tokens, output_tokens, cache_hit_tokens, reasoning_content
	except Exception as e:
		frappe.log_error(
			title=f"Error in _run_agent for {session_name}",
			message=f"Error: {str(e)}, Traceback: {traceback.format_exc()}"
		)
		raise


def _provider_max_tokens(provider_doc) -> int:
	return provider_doc.max_output_tokens or 32768


def generate_session_title(session_name: str, user_message: str, agent_reply: str) -> str:
	"""Generate a concise 5-8 word title for the conversation."""
	session = frappe.get_doc("Chat Session", session_name)
	provider_doc = frappe.get_doc("LLM Provider", session.llm_provider)

	api_key = provider_doc.get_password("api_key")
	if not api_key or not provider_doc.is_enabled:
		return ""

	openai_client = AsyncOpenAI(api_key=api_key, base_url=provider_doc.api_url)
	temperature = provider_doc.temperature if provider_doc.temperature is not None else 1.0
	max_tokens = _provider_max_tokens(provider_doc)
	prompt = f"User: {user_message}\\nAssistant: {agent_reply}"

	try:
		response = asyncio.run(
			openai_client.chat.completions.create(
				model=provider_doc.default_model,
				messages=[
					{
						"role": "system",
						"content": "Generate a concise 5-8 word title that summarises the following conversation. Return only the title text — no quotes, no punctuation at the end, no explanation.",
					},
					{"role": "user", "content": prompt},
				],
				temperature=temperature,
				max_tokens=max_tokens,
			)
		)
		if response.usage:
			_credit_auxiliary_api_tokens(session_name, response.usage, "session_title")
		return (response.choices[0].message.content or "").strip()
	except Exception:
		frappe.log_error(
			title=f"Title generation failed for session {session_name}",
			reference_doctype="Chat Session",
			reference_name=session_name,
		)
		return ""


def generate_conversation_summary(session_name: str, conversation_history: list) -> str:
	"""Generate a concise summary of a conversation."""
	session = frappe.get_doc("Chat Session", session_name)
	provider_doc = frappe.get_doc("LLM Provider", session.llm_provider)

	api_key = provider_doc.get_password("api_key")
	if not api_key or not provider_doc.is_enabled:
		return ""

	openai_client = AsyncOpenAI(api_key=api_key, base_url=provider_doc.api_url)
	temperature = provider_doc.temperature if provider_doc.temperature is not None else 1.0
	max_tokens = _provider_max_tokens(provider_doc)

	formatted_conversation = []
	for msg in conversation_history:
		role = msg.get("role", "user")
		content = msg.get("content", "")
		if role == "user":
			formatted_conversation.append(f"User: {content}")
		else:
			formatted_conversation.append(f"Assistant: {content}")

	try:
		response = asyncio.run(
			openai_client.chat.completions.create(
				model=provider_doc.default_model,
				messages=[
					{
						"role": "system",
						"content": "You are a conversation summarizer. Your task is to create a concise summary of a chat conversation. Focus on summarizing the FLOW of the conversation - who said what, what questions were asked, what answers were given. DO NOT just repeat factual information from the conversation. Instead, summarize the conversation structure. If the conversation already contains previous summaries, build upon them and focus on the new discussion that happened since the last summary point — do not repeat the already-summarized content. Example format: 'The user asked about [topic]. I explained [key points]. We discussed [main topics].' Keep the summary to 2-3 sentences maximum. Return only the summary text — no introductory phrases, no markdown, no extra text.",
					},
					{"role": "user", "content": "\\n".join(formatted_conversation)},
				],
				temperature=temperature,
				max_tokens=max_tokens,
			)
		)
		if response.usage:
			_credit_auxiliary_api_tokens(session_name, response.usage, "conversation_summary")
		return (response.choices[0].message.content or "").strip()
	except Exception:
		frappe.log_error(
			title=f"Conversation summarization failed for session {session_name}",
			reference_doctype="Chat Session",
			reference_name=session_name,
		)
		return ""


def generate_followup_suggestions(session_name: str, conversation_history: list) -> list[str]:
	"""Generate 3-5 follow-up question suggestions for the conversation."""
	session = frappe.get_doc("Chat Session", session_name)
	provider_doc = frappe.get_doc("LLM Provider", session.llm_provider)

	api_key = provider_doc.get_password("api_key")
	if not api_key or not provider_doc.is_enabled:
		return []

	openai_client = AsyncOpenAI(api_key=api_key, base_url=provider_doc.api_url)
	max_tokens = _provider_max_tokens(provider_doc)

	context_parts = []
	for msg in conversation_history[-6:]:
		role = "User" if msg.get("role") == "user" else "Assistant"
		context_parts.append(f"{role}: {msg.get('content', '')[:500]}")

	try:
		response = asyncio.run(
			openai_client.chat.completions.create(
				model=provider_doc.default_model,
				messages=[
					{
						"role": "system",
						"content": 'You are a helpful assistant that suggests relevant follow-up questions based on the conversation. Provide exactly 3 to 5 concise questions that the user might want to ask next. Return only a JSON array of strings - no explanation, no markdown, no extra text. Example: ["Question one?", "Question two?", "Question three?"]',
					},
					{"role": "user", "content": "\\n".join(context_parts)},
				],
				temperature=1.0,
				max_tokens=max_tokens,
				response_format={"type": "json_object"},
			)
		)

		if response.usage:
			_credit_auxiliary_api_tokens(session_name, response.usage, "followup_suggestions")

		raw = (response.choices[0].message.content or "").strip()
		if not raw:
			return []

		try:
			data = json.loads(raw)
		except json.JSONDecodeError:
			return []

		if isinstance(data, dict):
			for key in ["suggestions", "questions", "follow_up", "response"]:
				if key in data and isinstance(data[key], list):
					return [str(item) for item in data[key] if item][:5]
			for value in data.values():
				if isinstance(value, list):
					return [str(item) for item in value if item][:5]
		elif isinstance(data, list):
			return [str(item) for item in data if item][:5]

		return []
	except Exception:
		frappe.log_error(
			title=f"Suggestion generation failed for session {session_name}",
			reference_doctype="Chat Session",
			reference_name=session_name,
		)
		return []
