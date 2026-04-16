import asyncio
import logging

import frappe
from agents import Agent, RunConfig, Runner
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI, AuthenticationError, RateLimitError

logger = logging.getLogger(__name__)


def get_agent_response(session_name: str, user_message: str) -> tuple[str, int, int]:
	"""
	Call the LLM via agent-framework using the provider linked to the chat session.
	Returns (reply_text, input_tokens, output_tokens).
	Raises frappe.ValidationError with a user-friendly message on failure.
	"""
	session = frappe.get_doc("Chat Session", session_name)
	provider_doc = frappe.get_doc("LLM Provider", session.llm_provider)

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

	openai_client = AsyncOpenAI(
		api_key=api_key,
		base_url=provider_doc.api_url,
	)

	model = OpenAIChatCompletionsModel(
		model=provider_doc.default_model,
		openai_client=openai_client,
	)

	agent = Agent(
		name="PH Agent",
		instructions="You are a helpful assistant integrated into an ERPNext business system. Answer clearly and concisely.",
		model=model,
	)

	run_config = RunConfig(tracing_disabled=True)

	# Build full conversation history for context
	prior_messages = frappe.get_all(
		"Chat Message",
		filters={"chat_session": session_name},
		fields=["sender_type", "content"],
		order_by="creation asc",
	)
	history = [
		{"role": "user" if m.sender_type == "User" else "assistant", "content": m.content or ""}
		for m in prior_messages
	]
	history.append({"role": "user", "content": user_message})

	try:
		result = asyncio.run(
			Runner.run(
				agent,
				input=history,
				run_config=run_config,
			)
		)
	except AuthenticationError:
		frappe.throw(
			frappe._("Authentication failed for provider {0}. Please check the API key.").format(provider_doc.name)
		)
	except RateLimitError:
		frappe.throw(
			frappe._("Rate limit exceeded for provider {0}. Please try again shortly.").format(provider_doc.name)
		)
	except Exception as e:
		logger.exception("Agent call failed for session %s", session_name)
		frappe.throw(frappe._("The AI agent encountered an error: {0}").format(str(e)))

	reply = result.final_output or ""
	input_tokens = result.raw_responses[-1].usage.input_tokens if result.raw_responses else 0
	output_tokens = result.raw_responses[-1].usage.output_tokens if result.raw_responses else 0

	return reply, input_tokens, output_tokens


def generate_session_title(session_name: str, user_message: str, agent_reply: str) -> str:
	"""
	Ask the LLM to generate a short 5-8 word title that summarises the conversation.
	Returns the title string, or an empty string on failure.
	"""
	session = frappe.get_doc("Chat Session", session_name)
	provider_doc = frappe.get_doc("LLM Provider", session.llm_provider)

	api_key = provider_doc.get_password("api_key")
	if not api_key or not provider_doc.is_enabled:
		return ""

	openai_client = AsyncOpenAI(
		api_key=api_key,
		base_url=provider_doc.api_url,
	)

	model = OpenAIChatCompletionsModel(
		model=provider_doc.default_model,
		openai_client=openai_client,
	)

	title_agent = Agent(
		name="Title Generator",
		instructions=(
			"Generate a concise 5-8 word title that summarises the following conversation. "
			"Return only the title text — no quotes, no punctuation at the end, no explanation."
		),
		model=model,
	)

	prompt = f"User: {user_message}\nAssistant: {agent_reply}"

	try:
		result = asyncio.run(
			Runner.run(
				title_agent,
				input=prompt,
				run_config=RunConfig(tracing_disabled=True),
			)
		)
		return (result.final_output or "").strip()
	except Exception:
		logger.exception("Title generation failed for session %s", session_name)
		return ""
