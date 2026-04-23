import asyncio
import inspect
import json
import queue
import threading
from collections.abc import Generator, Sequence
from typing import Any

import frappe
from agent_framework import Agent, AgentSession, Content, HistoryProvider, Message
from agent_framework_openai import OpenAIChatCompletionClient
from openai import AsyncOpenAI
from ph_agent.agent.tools.tool_manager import ToolManager



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

	return Agent(
		client=chat_client,
		instructions=session_doc.system_prompt or None,
		tools=tools,
		default_options=default_options,
		context_providers=[FrappeMemoryProvider()],
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
			if isinstance(arguments, dict):
				arguments_str = json.dumps(arguments)
			else:
				arguments_str = arguments or "{}"
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


def _run_agent(session_name: str, message: Message, user: str | None = None):
	agent = _build_agent(session_name=session_name, user=user)
	agent_session = AgentSession(session_id=session_name)
	return asyncio.run(agent.run([message], session=agent_session))


def get_agent_response(session_name: str, user_message: str, cancel_check=None) -> tuple[str, int, int, dict | None]:
	if cancel_check and cancel_check():
		raise asyncio.CancelledError()

	response = _run_agent(session_name, Message("user", [user_message]))

	if cancel_check and cancel_check():
		raise asyncio.CancelledError()

	input_tokens, output_tokens = _get_usage_tokens(response.usage_details)
	approval_data = _extract_approval_data(response)
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
				agent = _build_agent(session_name=session_name)
				agent_session = AgentSession(session_id=session_name)
				stream = agent.run([Message("user", [user_message])], session=agent_session, stream=True)
				if inspect.isawaitable(stream):
					stream = await stream

				seen_text = ""

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

					# Emit in smaller pieces for smoother UI rendering.
					for idx in range(0, len(delta), 80):
						result_queue.put(("chunk", delta[idx : idx + 80]))

				if stop_event.is_set():
					result_queue.put(("done", ("", 0, 0)))
					return

				final_response = await stream.get_final_response()
				input_tokens, output_tokens = _get_usage_tokens(final_response.usage_details)
				approval_data = _extract_approval_data(final_response)
				if approval_data:
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
	approval_requests = (conversation_state or {}).get("approval_requests") or []
	if not approval_requests:
		return "", 0, 0

	approval = approval_requests[0]
	arguments_raw = approval.get("arguments") or "{}"
	try:
		arguments = json.loads(arguments_raw)
	except Exception:
		arguments = arguments_raw

	function_call = Content.from_function_call(
		call_id=approval.get("call_id") or "",
		name=approval.get("name") or "",
		arguments=arguments,
	)
	approval_response = Content.from_function_approval_response(
		approved=approved,
		id=approval.get("id") or "",
		function_call=function_call,
	)

	response = _run_agent(session_name, Message("user", [approval_response]), user=user)
	input_tokens, output_tokens = _get_usage_tokens(response.usage_details)
	return response.text or "", input_tokens, output_tokens


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
						"content": "You are a conversation summarizer. Your task is to create a concise summary of a chat conversation. Focus on summarizing the FLOW of the conversation - who said what, what questions were asked, what answers were given. DO NOT just repeat factual information from the conversation. Instead, summarize the conversation structure. Example format: 'The user asked about [topic]. I explained [key points]. We discussed [main topics].' Keep the summary to 2-3 sentences maximum. Return only the summary text — no introductory phrases, no markdown, no extra text.",
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
