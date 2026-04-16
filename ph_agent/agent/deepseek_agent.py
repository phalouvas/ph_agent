import asyncio

import frappe
from agents import Agent, OpenAIProvider, RunConfig, Runner
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI


def get_agent_response(session_name: str, user_message: str) -> tuple[str, int, int]:
	"""
	Call the LLM via agent-framework using the provider linked to the chat session.
	Returns (reply_text, input_tokens, output_tokens).
	"""
	session = frappe.get_doc("Chat Session", session_name)
	provider_doc = frappe.get_doc("LLM Provider", session.llm_provider)

	api_key = provider_doc.get_password("api_key")
	if not api_key:
		frappe.throw(frappe._("API key not configured for provider {0}.").format(provider_doc.name))

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

	result = asyncio.run(
		Runner.run(
			agent,
			input=user_message,
			run_config=run_config,
		)
	)

	reply = result.final_output or ""
	input_tokens = result.raw_responses[-1].usage.input_tokens if result.raw_responses else 0
	output_tokens = result.raw_responses[-1].usage.output_tokens if result.raw_responses else 0

	return reply, input_tokens, output_tokens
