import asyncio
import json

import frappe
from agents import Agent, ModelSettings, RunConfig, Runner
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI, OpenAI, AuthenticationError, RateLimitError

def get_agent_response(session_name: str, user_message: str, cancel_check=None) -> tuple[str, int, int]:
	"""
	Call the LLM via agent-framework using the provider linked to the chat session.
	Returns (reply_text, input_tokens, output_tokens).
	Raises frappe.ValidationError with a user-friendly message on failure.
	If cancel_check() returns True before or after the API call, raises asyncio.CancelledError.
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

	# Check context limit before making API call
	context_length = provider_doc.context_length or 128000  # Default to 128K
	estimated_tokens = session.estimated_conversation_tokens or 0
	
	# Get max_tokens for this call
	max_tokens = provider_doc.max_output_tokens
	if not max_tokens:
		# Fallback to model-specific defaults
		model_name = (provider_doc.default_model or "").lower()
		if "reasoner" in model_name:
			max_tokens = 32768  # 32K for DeepSeek Reasoner
		else:
			max_tokens = 4096   # 4K for DeepSeek Chat and other models
	
	# Check if this call would exceed context limit
	if estimated_tokens + max_tokens > context_length:
		frappe.throw(
			frappe._(
				"Conversation would exceed context limit. Current: {0:,} tokens, Limit: {1:,} tokens, This call needs: ~{2:,} tokens. "
				"Please summarize the conversation first."
			).format(estimated_tokens, context_length, max_tokens)
		)

	openai_client = AsyncOpenAI(
		api_key=api_key,
		base_url=provider_doc.api_url,
	)

	# Determine temperature: session overrides provider, default to 1.0
	temperature = session.temperature if session.temperature is not None else provider_doc.temperature if provider_doc.temperature is not None else 1.0
	
	# Get max_tokens from provider, use model-specific defaults if not set
	max_tokens = provider_doc.max_output_tokens
	if not max_tokens:
		# Fallback to model-specific defaults
		model_name = (provider_doc.default_model or "").lower()
		if "reasoner" in model_name:
			max_tokens = 32768  # 32K for DeepSeek Reasoner
		else:
			max_tokens = 4096   # 4K for DeepSeek Chat and other models
	
	model = OpenAIChatCompletionsModel(
		model=provider_doc.default_model,
		openai_client=openai_client,
	)

	# Session prompt overrides provider prompt; if both empty, use None (no system prompt)
	system_prompt = session.system_prompt or provider_doc.system_prompt or None

	agent = Agent(
		name="PH Agent",
		instructions=system_prompt,
		model=model,
		model_settings=ModelSettings(temperature=temperature, max_tokens=max_tokens),
	)

	run_config = RunConfig(tracing_disabled=True)

	# Build conversation history for context (only messages after last summary)
	# Get last summary message if exists
	last_summary_message = frappe.db.get_value("Chat Session", session_name, "last_summary_message")
	
	if last_summary_message:
		# Get messages created after the last summary
		prior_messages = frappe.get_all(
			"Chat Message",
			filters={
				"chat_session": session_name,
				"creation": [">", frappe.db.get_value("Chat Message", last_summary_message, "creation")]
			},
			fields=["sender_type", "content"],
			order_by="creation asc",
		)
	else:
		# No summary yet, get all messages
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
		# Check cancellation before starting the expensive API call
		if cancel_check and cancel_check():
			raise asyncio.CancelledError()

		result = asyncio.run(
			Runner.run(
				agent,
				input=history,
				run_config=run_config,
			)
		)

		# Check cancellation after the API call returns — discard result if cancelled
		if cancel_check and cancel_check():
			raise asyncio.CancelledError()

	except asyncio.CancelledError:
		raise
	except AuthenticationError:
		frappe.throw(
			frappe._("Authentication failed for provider {0}. Please check the API key.").format(provider_doc.name)
		)
	except RateLimitError:
		frappe.throw(
			frappe._("Rate limit exceeded for provider {0}. Please try again shortly.").format(provider_doc.name)
		)
	except Exception as e:
		frappe.log_error(
			title=f"Agent call failed for session {session_name}",
			reference_doctype="Chat Session",
			reference_name=session_name
		)
		frappe.throw(frappe._("The AI agent encountered an error: {0}").format(str(e)))

	reply = result.final_output or "No response generated."
	input_tokens = result.raw_responses[-1].usage.input_tokens if result.raw_responses else 0
	output_tokens = result.raw_responses[-1].usage.output_tokens if result.raw_responses else 0

	return reply, input_tokens, output_tokens


def get_agent_response_stream(session_name: str, user_message: str, cancel_check=None):
	"""
	Call the LLM via OpenAI streaming API and yield content chunks.
	Yields (chunk_content, is_final, input_tokens, output_tokens) where is_final is False for content chunks
	and True for the final chunk containing token usage.
	Raises frappe.ValidationError with a user-friendly message on failure.
	If cancel_check() returns True, raises asyncio.CancelledError.
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

	# Check context limit before making API call
	context_length = provider_doc.context_length or 128000  # Default to 128K
	estimated_tokens = session.estimated_conversation_tokens or 0
	
	# Get max_tokens for this call
	max_tokens = provider_doc.max_output_tokens
	if not max_tokens:
		# Fallback to model-specific defaults
		model_name = (provider_doc.default_model or "").lower()
		if "reasoner" in model_name:
			max_tokens = 32768  # 32K for DeepSeek Reasoner
		else:
			max_tokens = 4096   # 4K for DeepSeek Chat and other models
	
	# Check if this call would exceed context limit
	if estimated_tokens + max_tokens > context_length:
		frappe.throw(
			frappe._(
				"Conversation would exceed context limit. Current: {0:,} tokens, Limit: {1:,} tokens, This call needs: ~{2:,} tokens. "
				"Please summarize the conversation first."
			).format(estimated_tokens, context_length, max_tokens)
		)

	openai_client = OpenAI(
		api_key=api_key,
		base_url=provider_doc.api_url,
	)

	# Determine temperature: session overrides provider, default to 1.0
	temperature = session.temperature if session.temperature is not None else provider_doc.temperature if provider_doc.temperature is not None else 1.0
	
	# Session prompt overrides provider prompt; if both empty, use None (no system prompt)
	system_prompt = session.system_prompt or provider_doc.system_prompt or None

	# Build conversation history for context (only messages after last summary)
	# Get last summary message if exists
	last_summary_message = frappe.db.get_value("Chat Session", session_name, "last_summary_message")
	
	if last_summary_message:
		# Get messages created after the last summary
		prior_messages = frappe.get_all(
			"Chat Message",
			filters={
				"chat_session": session_name,
				"creation": [">", frappe.db.get_value("Chat Message", last_summary_message, "creation")]
			},
			fields=["sender_type", "content"],
			order_by="creation asc",
		)
	else:
		# No summary yet, get all messages
		prior_messages = frappe.get_all(
			"Chat Message",
			filters={"chat_session": session_name},
			fields=["sender_type", "content"],
			order_by="creation asc",
		)
	
	messages = [
		{"role": "user" if m.sender_type == "User" else "assistant", "content": m.content or ""}
		for m in prior_messages
	]
	messages.append({"role": "user", "content": user_message})
	
	# Add system prompt if provided
	if system_prompt:
		messages.insert(0, {"role": "system", "content": system_prompt})

	try:
		# Check cancellation before starting the expensive API call
		if cancel_check and cancel_check():
			raise asyncio.CancelledError()

		# Get max_tokens from provider, use model-specific defaults if not set
		max_tokens = provider_doc.max_output_tokens
		if not max_tokens:
			# Fallback to model-specific defaults
			model_name = (provider_doc.default_model or "").lower()
			if "reasoner" in model_name:
				max_tokens = 32768  # 32K for DeepSeek Reasoner
			else:
				max_tokens = 4096   # 4K for DeepSeek Chat and other models
		
		# Use OpenAI's streaming API directly
		stream = openai_client.chat.completions.create(
			model=provider_doc.default_model,
			messages=messages,
			temperature=temperature,
			max_tokens=max_tokens,
			stream=True,
		)

		full_content = ""
		input_tokens = 0
		output_tokens = 0

		for chunk in stream:
			# Check cancellation during streaming
			if cancel_check and cancel_check():
				raise asyncio.CancelledError()

			if chunk.choices and chunk.choices[0].delta.content is not None:
				content_chunk = chunk.choices[0].delta.content
				full_content += content_chunk
				yield content_chunk, False, 0, 0

			# Check for final chunk with token usage
			if chunk.usage:
				input_tokens = chunk.usage.prompt_tokens
				output_tokens = chunk.usage.completion_tokens

		# Yield final chunk with token usage
		yield "", True, input_tokens, output_tokens

	except asyncio.CancelledError:
		raise
	except AuthenticationError:
		frappe.throw(
			frappe._("Authentication failed for provider {0}. Please check the API key.").format(provider_doc.name)
		)
	except RateLimitError:
		frappe.throw(
			frappe._("Rate limit exceeded for provider {0}. Please try again shortly.").format(provider_doc.name)
		)
	except Exception as e:
		frappe.log_error(
			title=f"Agent streaming call failed for session {session_name}",
			reference_doctype="Chat Session",
			reference_name=session_name
		)
		frappe.throw(frappe._("The AI agent encountered an error during streaming: {0}").format(str(e)))


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

	# Use provider temperature for title generation (default to 1.0 if not set)
	title_temperature = provider_doc.temperature if provider_doc.temperature is not None else 1.0
	
	# Get max_tokens from provider, use model-specific defaults if not set
	max_tokens = provider_doc.max_output_tokens
	if not max_tokens:
		# Fallback to model-specific defaults
		model_name = (provider_doc.default_model or "").lower()
		if "reasoner" in model_name:
			max_tokens = 32768  # 32K for DeepSeek Reasoner
		else:
			max_tokens = 4096   # 4K for DeepSeek Chat and other models
	
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
		model_settings=ModelSettings(temperature=title_temperature, max_tokens=max_tokens),
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
		frappe.log_error(
			title=f"Title generation failed for session {session_name}",
			reference_doctype="Chat Session",
			reference_name=session_name
		)
		return ""


def generate_conversation_summary(session_name: str, conversation_history: list) -> str:
	"""
	Generate a concise summary of a conversation.
	Returns the summary text, or an empty string on failure.
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

	# Use provider temperature for summary generation (default to 1.0 if not set)
	summary_temperature = provider_doc.temperature if provider_doc.temperature is not None else 1.0
	
	# Get max_tokens from provider, use model-specific defaults if not set
	max_tokens = provider_doc.max_output_tokens
	if not max_tokens:
		# Fallback to model-specific defaults
		model_name = (provider_doc.default_model or "").lower()
		if "reasoner" in model_name:
			max_tokens = 32768  # 32K for DeepSeek Reasoner
		else:
			max_tokens = 4096   # 4K for DeepSeek Chat and other models
	
	model = OpenAIChatCompletionsModel(
		model=provider_doc.default_model,
		openai_client=openai_client,
	)

	summary_agent = Agent(
		name="Conversation Summarizer",
		instructions=(
			"You are a helpful assistant that summarizes conversations concisely. "
			"Create a clear, concise summary that captures the main points, key decisions, "
			"and important information from the conversation. "
			"Focus on the most important information that would be useful for future reference. "
			"Keep the summary to 3-5 sentences maximum. "
			"Return only the summary text — no introductory phrases, no markdown, no extra text."
		),
		model=model,
		model_settings=ModelSettings(temperature=summary_temperature, max_tokens=max_tokens),
	)

	# Format conversation for summarization
	formatted_conversation = []
	for msg in conversation_history:
		role = msg.get("role", "user")
		content = msg.get("content", "")
		if role == "user":
			formatted_conversation.append(f"User: {content}")
		else:
			formatted_conversation.append(f"Assistant: {content}")
	
	conversation_text = "\n".join(formatted_conversation)

	try:
		result = asyncio.run(
			Runner.run(
				summary_agent,
				input=conversation_text,
				run_config=RunConfig(tracing_disabled=True),
			)
		)
		return (result.final_output or "").strip()
	except Exception:
		frappe.log_error(
			title=f"Conversation summarization failed for session {session_name}",
			reference_doctype="Chat Session",
			reference_name=session_name
		)
		return ""


def generate_followup_suggestions(session_name: str, conversation_history: list) -> list[str]:
	"""
	Ask the LLM to generate 3-5 follow-up question suggestions based on the conversation.
	Returns a list of suggestion strings, or an empty list on failure.
	"""
	session = frappe.get_doc("Chat Session", session_name)
	provider_doc = frappe.get_doc("LLM Provider", session.llm_provider)

	api_key = provider_doc.get_password("api_key")
	if not api_key or not provider_doc.is_enabled:
		return []

	openai_client = AsyncOpenAI(
		api_key=api_key,
		base_url=provider_doc.api_url,
	)

	# Get max_tokens from provider, use model-specific defaults if not set
	max_tokens = provider_doc.max_output_tokens
	if not max_tokens:
		# Fallback to model-specific defaults
		model_name = (provider_doc.default_model or "").lower()
		if "reasoner" in model_name:
			max_tokens = 32768  # 32K for DeepSeek Reasoner
		else:
			max_tokens = 4096   # 4K for DeepSeek Chat and other models
	
	model = OpenAIChatCompletionsModel(
		model=provider_doc.default_model,
		openai_client=openai_client,
	)

	suggestions_agent = Agent(
		name="Suggestions Generator",
		instructions=(
			"You are a helpful assistant that suggests relevant follow-up questions based on the conversation. "
			"Provide exactly 3 to 5 concise questions that the user might want to ask next. "
			"Return only a JSON array of strings — no explanation, no markdown, no extra text. "
			'Example: ["Question one?", "Question two?", "Question three?"]'
		),
		model=model,
		model_settings=ModelSettings(temperature=1.0, max_tokens=max_tokens),
	)

	# Build a short summary of the conversation as context
	context_parts = []
	for msg in conversation_history[-6:]:  # last 6 messages max for context
		role = "User" if msg.get("role") == "user" else "Assistant"
		context_parts.append(f"{role}: {msg.get('content', '')[:500]}")
	context = "\n".join(context_parts)

	try:
		result = asyncio.run(
			Runner.run(
				suggestions_agent,
				input=context,
				run_config=RunConfig(tracing_disabled=True),
			)
		)
		raw = (result.final_output or "").strip()
		suggestions = json.loads(raw)
		if isinstance(suggestions, list):
			return [str(s) for s in suggestions if s][:5]
		return []
	except Exception:
		frappe.log_error(
			title=f"Suggestion generation failed for session {session_name}",
			reference_doctype="Chat Session",
			reference_name=session_name
		)
		return []
