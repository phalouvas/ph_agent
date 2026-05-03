"""LLMMemoryProvider — AI-driven memory extraction from conversation turns.

Uses the LLM itself to extract arbitrary facts, preferences, goals, and
other meaningful information from user messages. Extracted memories are
persisted in the **User Memory** Frappe DocType keyed by the Frappe user,
and injected as system instructions in subsequent turns via the
ContextProvider.before_run() hook.

This is complementary to :class:`UserPreferenceProvider` — while that
provider uses regex patterns for structured signals (date format, language,
response style), this provider captures freeform facts via LLM inference.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import frappe
from agent_framework import ContextProvider
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Rate-limit: minimum seconds between extractions for the same user
_EXTRACTION_INTERVAL = 30

# Minimum confidence to inject a memory as a system instruction
_INJECTION_CONFIDENCE_THRESHOLD = 0.6

# Maximum number of memories to inject as system instructions per turn
_MAX_INJECTED_MEMORIES = 15

# Default model to use for extraction if the provider doesn't specify one
_DEFAULT_EXTRACTION_MODEL = "gpt-4o-mini"

# System prompt for the LLM extraction call
_EXTRACTION_SYSTEM_PROMPT = """You are a memory extraction assistant. Extract factual information \
about the user from this conversation turn. Focus on:
- Personal details (name, location, job, preferences)
- Goals, tasks, or projects mentioned
- Preferences (communication style, format preferences)
- Contextual information (tools they use, industry, company)

Return a JSON array of objects with:
- "fact": the extracted fact (concise, specific, one fact per object)
- "category": one of "Fact", "Preference", "Goal", "Context", "Personal", "Other"
- "confidence": a float between 0.0 and 1.0 indicating how certain you are

Skip generic statements. Only extract if there is meaningful information.
Return an empty array if nothing worth extracting is found.

Response format: ONLY valid JSON, nothing else."""


# Template for persona-aware extraction prompt — {persona} is substituted at runtime
_PERSONA_AWARE_EXTRACTION_PROMPT = """You are a memory extraction assistant. Extract factual information \
about the user from this conversation turn, in the context of the "{persona}" persona.
Focus on:
- Personal details (name, location, job, preferences)
- Goals, tasks, or projects mentioned
- Preferences (communication style, format preferences)
- Contextual information (tools they use, industry, company)

Return a JSON array of objects with:
- "fact": the extracted fact (concise, specific, one fact per object)
- "category": one of "Fact", "Preference", "Goal", "Context", "Personal", "Other"
- "confidence": a float between 0.0 and 1.0 indicating how certain you are

Skip generic statements. Only extract if there is meaningful information.
Return an empty array if nothing worth extracting is found.

Response format: ONLY valid JSON, nothing else."""


class LLMMemoryProvider(ContextProvider):
	"""ContextProvider that learns user memories via LLM extraction.

	On each ``before_run()``, loads memories from the **User Memory**
	DocType (confidence >= 0.6) and injects them as system instructions.

	On each ``after_run()``, calls the LLM (using the same provider as
	the session) to extract new memories from the latest conversation
	turn, then persists them with deduplication.

	Memories are scoped to ``(user, persona)`` — each persona has its own
	isolated memory pool.
	"""

	MEMORIES_KEY = "llm_memories"
	LAST_EXTRACTION_KEY = "llm_last_extraction"

	def __init__(self) -> None:
		super().__init__("llm_memory")

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	async def before_run(
		self,
		*,
		agent: Any,
		session: Any,
		context: Any,
		state: dict[str, Any],
	) -> None:
		"""Load high-confidence memories and inject as system instructions.

		Only memories relevant to the current user query are injected, capped
		at ``_MAX_INJECTED_MEMORIES`` to avoid context dilution.
		"""
		user, persona = self._get_user_and_persona(session)
		if not user:
			return

		# Extract the current user query for relevance filtering
		user_message = self._get_latest_user_message(context) or ""

		memories = self._load_memories(
			user, persona=persona, query=user_message, top_k=_MAX_INJECTED_MEMORIES
		)

		# Cache in session state for same-turn access
		state[self.MEMORIES_KEY] = memories

		instructions_text = self._format_memories(memories)
		if instructions_text:
			# Apply token budget — memories have highest priority
			from ph_agent.api.token_counter import consume_context_budget

			instructions_text = consume_context_budget(state, "memories", instructions_text)
			if instructions_text:
				context.extend_instructions(self.source_id, instructions_text)

	async def after_run(
		self,
		*,
		agent: Any,
		session: Any,
		context: Any,
		state: dict[str, Any],
	) -> None:
		"""Extract new memories from the latest conversation turn via LLM."""
		user, persona = self._get_user_and_persona(session)
		if not user:
			logger.debug("LLMMemoryProvider: no user resolved, skipping extraction")
			return

		# Rate-limit extraction (across runs, not within same run)
		last_time = state.get(self.LAST_EXTRACTION_KEY, 0)
		if time.time() - last_time < _EXTRACTION_INTERVAL:
			logger.debug(
				"LLMMemoryProvider: rate-limited (last extraction %.1fs ago)", time.time() - last_time
			)
			return

		# Collect user message + assistant response from this turn
		user_message = self._get_latest_user_message(context)
		assistant_response = self._get_latest_assistant_response(context)

		if not user_message:
			logger.debug("LLMMemoryProvider: no user message found in context.input_messages")
			return

		# Skip extraction for very short messages — unlikely to contain meaningful memories
		if len(user_message.strip()) < 20:
			logger.debug(
				"LLMMemoryProvider: message too short (%d chars), skipping extraction",
				len(user_message.strip()),
			)
			return

		logger.debug(
			"LLMMemoryProvider: extracting memories from turn (user_msg=%s, assistant=%s)",
			user_message[:50] if user_message else "None",
			assistant_response[:50] if assistant_response else "None",
		)

		# Get the LLM client from the session's provider
		client = self._get_llm_client(session)
		if not client:
			logger.warning("LLMMemoryProvider: could not create LLM client")
			return

		# Extract memories via LLM
		session_id = self._get_session_id(session)
		extracted = await self._extract_memories(
			client=client,
			session=session,
			user_message=user_message,
			assistant_response=assistant_response,
			persona=persona,
		)
		if not extracted:
			logger.debug("LLMMemoryProvider: LLM returned no memories")
			return

		logger.info("LLMMemoryProvider: extracted %d memories for user %s", len(extracted), user)

		# Deduplicate and persist
		source_message = self._get_source_message_id(session)
		self._deduplicate_and_merge(extracted, user, persona, session_id, source_message)

		# Commit explicitly — after_run may run in a threading context
		frappe.db.commit()

		# Update state cache
		state[self.MEMORIES_KEY] = self._load_memories(user, persona=persona)
		state[self.LAST_EXTRACTION_KEY] = time.time()

	# ------------------------------------------------------------------
	# Session / user / persona resolution
	# ------------------------------------------------------------------

	@staticmethod
	def _get_user_and_persona(session: Any) -> tuple[str | None, str | None]:
		"""Resolve the Frappe user and persona from the session's Chat Session doc."""
		session_id = getattr(session, "session_id", None)
		if not session_id:
			return None, None
		try:
			vals = frappe.db.get_value("Chat Session", session_id, ["user", "persona"])
			if not vals:
				return None, None
			return vals[0], vals[1]
		except Exception:
			return None, None

	@staticmethod
	def _get_session_id(session: Any) -> str | None:
		"""Get the session ID from an AgentSession."""
		return getattr(session, "session_id", None)

	@staticmethod
	def _get_source_message_id(session: Any) -> str | None:
		"""Try to find the latest Chat Message name for this session.

		This is best-effort — there may be a small window where the message
		hasn't been persisted yet when after_run fires.
		"""
		session_id = getattr(session, "session_id", None)
		if not session_id:
			return None
		try:
			last_msg = frappe.get_all(
				"Chat Message",
				filters={"chat_session": session_id},
				fields=["name"],
				order_by="creation desc, name desc",
				limit_page_length=1,
			)
			return last_msg[0].name if last_msg else None
		except Exception:
			return None

	# ------------------------------------------------------------------
	# LLM client
	# ------------------------------------------------------------------

	@staticmethod
	def _get_llm_client(session: Any) -> AsyncOpenAI | None:
		"""Resolve the LLM provider from the session and create an AsyncOpenAI client.

		Uses the same provider (API key, URL, model) as the chat session itself.
		"""
		session_id = getattr(session, "session_id", None)
		if not session_id:
			return None
		try:
			provider_name = frappe.db.get_value("Chat Session", session_id, "llm_provider")
			if not provider_name:
				return None

			provider_doc = frappe.get_doc("LLM Provider", provider_name)
			api_key = provider_doc.get_password("api_key")
			if not api_key or not provider_doc.is_enabled:
				return None

			return AsyncOpenAI(api_key=api_key, base_url=provider_doc.api_url)
		except Exception as e:
			logger.exception("Failed to create LLM client for memory extraction: %s", e)
			return None

	@staticmethod
	def _get_extraction_model(session: Any) -> str:
		"""Return a cheap model appropriate for the session's provider.

		Uses a provider-aware cheap model so extraction works across
		different LLM backends (OpenAI, DeepSeek, etc.).
		"""
		session_id = getattr(session, "session_id", None)
		if session_id:
			try:
				provider_name = frappe.db.get_value("Chat Session", session_id, "llm_provider")
				if provider_name:
					provider_doc = frappe.get_doc("LLM Provider", provider_name)
					api_url = (provider_doc.api_url or "").lower()

					# DeepSeek — use their chat model
					if "deepseek" in api_url:
						return "deepseek-chat"
					# Anthropic — Mesa optimization; can't use OpenAI models
					if "anthropic" in api_url:
						return provider_doc.default_model or _DEFAULT_EXTRACTION_MODEL
					# OpenAI-compatible — use the cheap model
					if "openai" in api_url or not api_url:
						return _DEFAULT_EXTRACTION_MODEL

					# Unknown provider — fall back to the provider's own model
					return provider_doc.default_model or _DEFAULT_EXTRACTION_MODEL
			except Exception:
				pass
		return _DEFAULT_EXTRACTION_MODEL

	# ------------------------------------------------------------------
	# Memory extraction via LLM
	# ------------------------------------------------------------------

	@staticmethod
	async def _extract_memories(
		client: AsyncOpenAI,
		session: Any,
		user_message: str,
		assistant_response: str,
		persona: str | None = None,
	) -> list[dict[str, Any]]:
		"""Call the LLM to extract memories from a conversation turn.

		Args:
			client: The OpenAI-compatible client.
			session: The agent session.
			user_message: The user's message text.
			assistant_response: The assistant's response text.
			persona: Optional persona name for context-aware extraction.

		Returns:
			A list of dicts with keys ``fact``, ``category``, ``confidence``,
			or an empty list on failure.
		"""
		model = LLMMemoryProvider._get_extraction_model(session)
		prompt = f"User message: {user_message}\nAssistant response: {assistant_response}"

		# Use persona-aware prompt if persona is known
		system_prompt = _EXTRACTION_SYSTEM_PROMPT
		if persona:
			system_prompt = _PERSONA_AWARE_EXTRACTION_PROMPT.format(persona=persona)

		try:
			response = await client.chat.completions.create(
				model=model,
				messages=[
					{"role": "system", "content": system_prompt},
					{"role": "user", "content": prompt},
				],
				temperature=0.3,
				max_tokens=1000,
			)
		except Exception as e:
			logger.exception("LLM memory extraction call failed: %s", e)
			return []

		content = (response.choices[0].message.content or "").strip()
		if not content:
			return []

		return LLMMemoryProvider._parse_extraction_response(content)

	@staticmethod
	def _parse_extraction_response(content: str) -> list[dict[str, Any]]:
		"""Parse the LLM response into a list of memory dicts.

		Handles JSON wrapped in markdown code blocks and other common
		LLM output inconsistencies.
		"""
		# Strip markdown code fences if present
		cleaned = content.strip()
		if cleaned.startswith("```"):
			# Find the first { or [ after the opening ```
			start = cleaned.find("\n")
			if start != -1:
				cleaned = cleaned[start:].strip()
			# Strip trailing ```
			if cleaned.endswith("```"):
				cleaned = cleaned[:-3].strip()
			if cleaned.endswith("```"):
				cleaned = cleaned[:-3].strip()

		try:
			data = json.loads(cleaned)
		except json.JSONDecodeError, TypeError:
			# Try to find a JSON array in the response
			try:
				start_idx = cleaned.index("[")
				end_idx = cleaned.rindex("]")
				data = json.loads(cleaned[start_idx : end_idx + 1])
			except ValueError, json.JSONDecodeError, TypeError:
				logger.warning("Failed to parse LLM extraction response: %s", content[:200])
				return []

		if not isinstance(data, list):
			data = [data]

		# Validate and normalize each entry
		valid: list[dict[str, Any]] = []
		for item in data:
			if not isinstance(item, dict):
				continue
			fact = (item.get("fact") or "").strip()
			if not fact:
				continue
			valid.append(
				{
					"fact": fact,
					"category": str(item.get("category", "Fact")),
					"confidence": float(item.get("confidence", 0.5)),
				}
			)

		return valid

	# ------------------------------------------------------------------
	# DB persistence — load / deduplicate / merge
	# ------------------------------------------------------------------

	@staticmethod
	def _load_memories(
		user: str, persona: str | None = None, query: str = "", top_k: int = 15
	) -> list[dict[str, Any]]:
		"""Load memories for a user and persona, filtered by relevance to the current query.

		When ``query`` is non-empty, memories are scored by word overlap with
		the query and only the top-K most relevant are returned. This prevents
		context dilution as the memory store grows over time.

		When ``query`` is empty, falls back to top-K by confidence.

		Args:
			user: The Frappe user to load memories for.
			persona: The persona to scope memories to.
			query: The current user message text for relevance scoring.
			top_k: Maximum number of memories to return.

		Returns:
			List of dicts with keys ``fact``, ``category``, ``confidence``.
		"""
		if not user:
			return []
		try:
			filters: dict[str, Any] = {"user": user, "confidence": (">=", _INJECTION_CONFIDENCE_THRESHOLD)}
			if persona:
				filters["persona"] = persona
			records = frappe.get_all(
				"User Memory",
				filters=filters,
				fields=["fact", "category", "confidence"],
				order_by="confidence desc",
			)
		except Exception:
			return []

		if not records:
			return []

		# Build result dicts
		all_memories = [
			{
				"fact": r.fact,
				"category": r.category,
				"confidence": r.confidence,
			}
			for r in records
		]

		# If no query, return top-K by confidence (existing behavior with cap)
		query = (query or "").strip()
		if not query:
			return all_memories[:top_k]

		# Relevance scoring: count overlapping words between query and fact
		query_words = set(re.findall(r"\b\w+\b", query.lower()))
		if not query_words:
			return all_memories[:top_k]

		scored: list[tuple[int, dict[str, Any]]] = []
		for mem in all_memories:
			fact_words = set(re.findall(r"\b\w+\b", mem["fact"].lower()))
			overlap = len(query_words & fact_words)
			if overlap > 0:
				scored.append((overlap, mem))

		# Sort by overlap score DESC, then confidence DESC
		scored.sort(key=lambda x: (x[0], x[1].get("confidence", 0)), reverse=True)

		result = [mem for _, mem in scored[:top_k]]

		logger.debug(
			"LLMMemoryProvider: relevance-filtered %d/%d memories for user %s (query=%s)",
			len(result),
			len(all_memories),
			user,
			query[:60],
		)

		return result

	@staticmethod
	def _deduplicate_and_merge(
		memories: list[dict[str, Any]],
		user: str,
		persona: str | None = None,
		session_id: str | None = None,
		source_message: str | None = None,
	) -> None:
		"""Insert new memories or update existing ones.

		For each extracted memory:
		- If a similar fact (case-insensitive) already exists for this (user, persona) → increment
		  ``encounter_count``, boost ``confidence`` slightly, update
		  ``last_encountered_at``.
		- If new → insert with the given confidence, source info, and
		  ``encounter_count = 1``.
		"""
		if not user or not memories:
			return

		for mem in memories:
			fact = mem["fact"]
			category = mem.get("category", "Fact")
			confidence = float(mem.get("confidence", 0.5))

			# Check for existing entry by exact case-insensitive match within this persona
			filters: dict[str, Any] = {"user": user, "fact": fact}
			if persona:
				filters["persona"] = persona
			existing_name = frappe.db.get_value(
				"User Memory",
				filters,
				"name",
			)

			if existing_name:
				# Update existing — boost confidence, increment count
				try:
					doc = frappe.get_doc("User Memory", existing_name)
					new_confidence = min(float(doc.confidence or 0) + 0.05, 1.0)
					doc.db_set(
						{
							"confidence": new_confidence,
							"encounter_count": (doc.encounter_count or 1) + 1,
							"last_encountered_at": frappe.utils.now(),
							"category": category,  # Allow category to be refined
						}
					)
				except Exception as e:
					logger.warning("Failed to update User Memory %s: %s", existing_name, e)
			else:
				# Insert new
				try:
					doc = frappe.get_doc(
						{
							"doctype": "User Memory",
							"user": user,
							"persona": persona,
							"fact": fact,
							"category": category,
							"confidence": confidence,
							"source_session": session_id,
							"source_message": source_message,
							"last_encountered_at": frappe.utils.now(),
							"encounter_count": 1,
						}
					)
					doc.insert(ignore_permissions=True)
				except frappe.DuplicateEntryError:
					# Race condition — entry was created between our check and insert.
					# Do a lightweight update instead.
					try:
						dup_filters: dict[str, Any] = {"user": user, "fact": fact}
						if persona:
							dup_filters["persona"] = persona
						dup_name = frappe.db.get_value(
							"User Memory",
							dup_filters,
							"name",
						)
						if dup_name:
							dup_doc = frappe.get_doc("User Memory", dup_name)
							new_confidence = min(float(dup_doc.confidence or 0) + 0.05, 1.0)
							dup_doc.db_set(
								{
									"confidence": new_confidence,
									"encounter_count": (dup_doc.encounter_count or 1) + 1,
									"last_encountered_at": frappe.utils.now(),
								}
							)
					except Exception:
						pass
				except Exception as e:
					logger.warning("Failed to insert User Memory for user %s: %s", user, e)

	# ------------------------------------------------------------------
	# Message extraction from context
	# ------------------------------------------------------------------

	@staticmethod
	def _get_latest_user_message(context: Any) -> str | None:
		"""Extract the latest user message text from context input messages."""
		if not hasattr(context, "input_messages") or not context.input_messages:
			return None

		for msg in reversed(context.input_messages):
			if msg.role == "user":
				parts: list[str] = []
				for c in msg.contents or []:
					if hasattr(c, "text") and c.text:
						parts.append(c.text)
					elif isinstance(c, str):
						parts.append(c)
				text = " ".join(parts)
				if text:
					return text
		return None

	@staticmethod
	def _get_latest_assistant_response(context: Any) -> str | None:
		"""Extract the latest assistant response text from context response.

		``context.response`` is an ``AgentResponse`` object with a
		``.messages`` attribute (list of ``Message``).
		"""
		if not hasattr(context, "response") or not context.response:
			return None

		response = context.response
		# AgentResponse has .messages attribute
		messages = getattr(response, "messages", None)
		if not messages:
			return None

		for msg in reversed(messages):
			if msg.role == "assistant":
				parts: list[str] = []
				for c in msg.contents or []:
					if hasattr(c, "text") and c.text:
						parts.append(c.text)
					elif isinstance(c, str):
						parts.append(c)
				text = " ".join(parts)
				if text:
					return text

		return None

	# ------------------------------------------------------------------
	# Formatting for instruction injection
	# ------------------------------------------------------------------

	@staticmethod
	def _format_memories(memories: list[dict[str, Any]]) -> str:
		"""Format memories into a human-readable instruction string.

		Only includes memories with confidence >= ``_INJECTION_CONFIDENCE_THRESHOLD``.
		Capped at ``_MAX_INJECTED_MEMORIES`` as defense-in-depth.
		"""
		if not memories:
			return ""

		# Defense-in-depth cap
		memories = memories[:_MAX_INJECTED_MEMORIES]

		lines = [
			"The following information about the user has been learned from past conversations:",
		]
		for mem in memories:
			confidence = float(mem.get("confidence", 0))
			if confidence < _INJECTION_CONFIDENCE_THRESHOLD:
				continue
			category = mem.get("category", "Fact")
			fact = mem.get("fact", "")
			if not fact:
				continue
			lines.append(f"- [{category}]: {fact}")

		if len(lines) == 1:
			# Only the header was added — no valid memories
			return ""

		lines.append(
			"Use this information to personalize your responses, but do not mention "
			"the source of this information unless directly asked."
		)
		return "\n".join(lines)
