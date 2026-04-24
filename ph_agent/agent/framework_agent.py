import asyncio
import inspect
import json
import queue
import threading
from collections.abc import Generator, Sequence
from pathlib import Path
from typing import Any

import frappe
from agent_framework import Agent, AgentSession, Content, HistoryProvider, InMemoryHistoryProvider, Message
from agent_framework_openai import OpenAIChatCompletionClient
from agent_framework._skills import SkillsProvider
from openai import AsyncOpenAI
from ph_agent.agent.context.llm_memory_provider import LLMMemoryProvider
from ph_agent.agent.context.user_preference_provider import UserPreferenceProvider
from ph_agent.agent.skills import get_code_skills, invalidate_skill_cache
from ph_agent.agent.skills.script_runner import run_file_script
from ph_agent.agent.tools.tool_manager import ToolManager



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

	return SkillsProvider(
		skill_paths=skill_paths,
		skills=code_skills,
		require_script_approval=True,
		script_runner=run_file_script,
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
				fields=["sender_type", "content", "message_type"],
				order_by="creation asc",
			)
		else:
			prior_messages = frappe.get_all(
				"Chat Message",
				filters={"chat_session": session_id},
				fields=["sender_type", "content", "message_type"],
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
				history.append(Message("assistant", [content]))
		return history

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


def _get_usage_tokens(usage_details: dict[str, Any] | None) -> tuple[int, int]:
	if not usage_details:
		return 0, 0
	input_tokens = usage_details.get("input_token_count") or 0
	output_tokens = usage_details.get("output_token_count") or 0
	return int(input_tokens), int(output_tokens)


def _validate_context_limit(session_doc, provider_doc) -> int:
	context_length = provider_doc.context_length or 128000
	estimated_tokens = session_doc.estimated_conversation_tokens or 0
	max_tokens = provider_doc.max_output_tokens
	if not max_tokens:
		model_name = (provider_doc.default_model or "").lower()
		max_tokens = 32768 if "reasoner" in model_name else 4096

	if estimated_tokens + max_tokens > context_length:
		frappe.throw(
			frappe._(
				"Conversation would exceed context limit. Current: {0:,} tokens, Limit: {1:,} tokens, This call needs: ~{2:,} tokens. "
				"Please summarize the conversation first."
			).format(estimated_tokens, context_length, max_tokens)
		)

	return max_tokens


def _build_agent(session_name: str, user: str | None = None) -> Agent:
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
	temperature = (
		session_doc.temperature
		if session_doc.temperature is not None
		else provider_doc.temperature
		if provider_doc.temperature is not None
		else 1.0
	)
	tools = ToolManager.get_tools(session_name=session_name, user=user or frappe.session.user)

	chat_client = OpenAIChatCompletionClient(
		model=provider_doc.default_model,
		api_key=api_key,
		base_url=provider_doc.api_url,
	)
	default_options = {"temperature": temperature, "max_tokens": max_tokens}

	# Build skills provider from both file-based and DocType-based sources
	skills_provider = _build_skills_provider()

	return Agent(
		client=chat_client,
		instructions=session_doc.system_prompt or None,
		tools=tools,
		default_options=default_options,
		context_providers=[
			InMemoryHistoryProvider(),
			FrappeMemoryProvider(),
			skills_provider,
			UserPreferenceProvider(),
			LLMMemoryProvider(),
		],
	)


def _make_json_serializable(obj: Any) -> Any:
	"""Convert an object to JSON-serializable form, handling common non-serializable types."""
	try:
		# First try to serialize directly
		json.dumps(obj)
		return obj
	except (TypeError, ValueError):
		# If direct serialization fails, convert recursively
		if obj is None:
			return None
		elif isinstance(obj, (str, int, float, bool)):
			return obj
		elif isinstance(obj, dict):
			return {k: _make_json_serializable(v) for k, v in obj.items()}
		elif isinstance(obj, (list, tuple, set)):
			return [_make_json_serializable(item) for item in obj]
		elif hasattr(obj, 'to_dict'):
			# Try to use to_dict() method if available
			try:
				return _make_json_serializable(obj.to_dict())
			except Exception:
				return str(obj)
		elif hasattr(obj, '__dict__'):
			# Convert object to dict
			return _make_json_serializable(obj.__dict__)
		else:
			# For other types, convert to string representation
			return str(obj)


def _filter_session_state(state: dict[str, Any] | None) -> dict[str, Any]:
	"""Filter session state to remove non-serializable data."""
	if not state:
		return {}
	
	filtered_state = {}
	for key, value in state.items():
		if key != "in_memory":  # Remove in_memory provider data
			filtered_state[key] = _make_json_serializable(value)
	return filtered_state


def _load_session_state(session_name: str) -> dict[str, Any]:
	"""Load session state from Chat Session DocType."""
	try:
		session_doc = frappe.get_doc("Chat Session", session_name)
		if session_doc.session_state:
			state = json.loads(session_doc.session_state)
			return state
		return {}
	except Exception as e:
		frappe.log_error(
			title="Error loading session state",
			message=f"Session: {session_name}, Error: {e}"
		)
		return {}


def _save_session_state(session_name: str, state: dict[str, Any]) -> None:
	"""Save session state to Chat Session DocType."""
	try:
		if not state:
			return
		
		filtered_state = _filter_session_state(state)
		if not filtered_state:
			return
		
		session_doc = frappe.get_doc("Chat Session", session_name)
		session_doc.session_state = json.dumps(filtered_state, indent=2)
		session_doc.last_state_update = frappe.utils.now()
		session_doc.save(ignore_permissions=True)
	except Exception as e:
		frappe.log_error(
			title="Error saving session state",
			message=f"Session: {session_name}, Error: {e}"
		)


def _extract_approval_data(response) -> dict[str, Any] | None:
	approval_requests: list[dict[str, str]] = []
	tool_calls: list[dict[str, str]] = []

	for msg in response.messages:
		for content in msg.contents:
			if content.type != "function_approval_request" or not content.function_call:
				continue
			function_call = content.function_call
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


def _run_agent(session_name: str, message: Message | list, user: str | None = None, session_state: dict[str, Any] | None = None):
	agent = _build_agent(session_name=session_name, user=user)
	agent_session = AgentSession(session_id=session_name)
	if session_state:
		agent_session.state.update(session_state)
	messages = message if isinstance(message, list) else [message]
	result = asyncio.run(agent.run(messages, session=agent_session))
	return result, agent_session.state


async def _run_agent_stream(session_name: str, message: Message | list, user: str | None = None, session_state: dict[str, Any] | None = None):
	"""Run agent with streaming support."""
	agent = _build_agent(session_name=session_name, user=user)
	agent_session = AgentSession(session_id=session_name)
	if session_state:
		agent_session.state.update(session_state)
	messages = message if isinstance(message, list) else [message]
	stream = agent.run(messages, session=agent_session, stream=True)
	if inspect.isawaitable(stream):
		stream = await stream
	return stream, agent_session.state


def get_agent_response(session_name: str, user_message: str, cancel_check=None) -> tuple[str, int, int, dict | None]:
	if cancel_check and cancel_check():
		raise asyncio.CancelledError()

	# Load session state before running agent
	stored_state = _load_session_state(session_name)
	
	response, session_state = _run_agent(session_name, Message("user", [user_message]), session_state=stored_state)

	if cancel_check and cancel_check():
		raise asyncio.CancelledError()

	input_tokens, output_tokens = _get_usage_tokens(response.usage_details)
	approval_data = _extract_approval_data(response)
	
	# Always save session state, regardless of approval flow
	_save_session_state(session_name, session_state)
	
	if approval_data and session_state:
		# Also store session state in approval data for continuation
		approval_data["conversation_state"]["session_state"] = _filter_session_state(session_state)
	
	return response.text or "", input_tokens, output_tokens, approval_data


def get_agent_response_stream(
	session_name: str,
	user_message: str,
	cancel_check=None,
	status_callback=None,
) -> Generator[tuple[Any, bool, int, int], None, None]:
	if status_callback:
		status_callback(frappe._("Calling AI…"))

	site_name = getattr(frappe.local, "site", None)
	active_user = getattr(frappe.session, "user", None)

	result_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
	stop_event = threading.Event()

	def _producer() -> None:
		async def _consume() -> None:
			try:
				# Load session state before running agent
				stored_state = _load_session_state(session_name)
				
				# Use streaming agent runner
				stream, agent_session_state = await _run_agent_stream(
					session_name, 
					Message("user", [user_message]), 
					session_state=stored_state
				)

				seen_text = ""
				chunk_count = 0

				async for update in stream:
					if stop_event.is_set():
						break

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

					# Emit in smaller pieces for smoother UI rendering.
					for idx in range(0, len(delta), 80):
						result_queue.put(("chunk", delta[idx : idx + 80]))

				if stop_event.is_set():
					result_queue.put(("done", ("", 0, 0)))
					return

				final_response = await stream.get_final_response()
				input_tokens, output_tokens = _get_usage_tokens(final_response.usage_details)
				approval_data = _extract_approval_data(final_response)
				
				# Always save session state, regardless of approval flow
				_save_session_state(session_name, agent_session_state)
				
				if approval_data:
					# Also store session state in approval data for continuation
					approval_data["conversation_state"]["session_state"] = _filter_session_state(agent_session_state)
					result_queue.put(("approval", (approval_data, input_tokens, output_tokens)))
				else:
					result_queue.put(("done", ("", input_tokens, output_tokens)))
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
		finally:
			if initialized:
				# Commit any pending DB operations (e.g., UserPreferenceProvider saves)
				frappe.db.commit()
				frappe.destroy()

	thread = threading.Thread(target=_producer, daemon=True)
	thread.start()

	while True:
		if cancel_check and cancel_check():
			stop_event.set()
			raise asyncio.CancelledError()

		try:
			event_type, payload = result_queue.get(timeout=0.2)
		except queue.Empty:
			continue

		if event_type == "chunk":
			yield payload, False, 0, 0
			continue
		if event_type == "approval":
			approval_data, input_tokens, output_tokens = payload
			yield approval_data, True, input_tokens, output_tokens
			break
		if event_type == "done":
			chunk, input_tokens, output_tokens = payload
			yield chunk, True, input_tokens, output_tokens
			break
		if event_type == "error":
			raise payload


def run_after_approval(
	session_name: str,
	conversation_state: dict[str, Any],
	approved: bool,
	user: str | None = None,
) -> tuple[str, int, int]:
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

	# Get session state from conversation_state
	session_state = conversation_state.get("session_state", {})
	
	try:
		# Per the Microsoft Agent Framework documentation, provide:
		# 1. The assistant message containing the original function_approval_request
		# 2. The user message containing the function_approval_response
		# The original user query is supplied automatically by FrappeMemoryProvider.
		messages = [
			Message("assistant", [approval_request_content]),
			Message("user", [approval_response]),
		]
		
		response, updated_state = _run_agent(
			session_name, 
			messages,  # Pass both messages
			user=user,
			session_state=session_state
		)
		input_tokens, output_tokens = _get_usage_tokens(response.usage_details)
		
		# Save updated session state to Chat Session
		_save_session_state(session_name, updated_state)
		
		return response.text or "", input_tokens, output_tokens
	except Exception as e:
		frappe.log_error(
			title=f"Error in _run_agent for {session_name}",
			message=f"Error: {str(e)}, Traceback: {traceback.format_exc()}"
		)
		raise


def _provider_max_tokens(provider_doc) -> int:
	max_tokens = provider_doc.max_output_tokens
	if not max_tokens:
		model_name = (provider_doc.default_model or "").lower()
		max_tokens = 32768 if "reasoner" in model_name else 4096
	return max_tokens


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
