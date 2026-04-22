import asyncio
import json

import frappe

from openai import AsyncOpenAI, OpenAI, AuthenticationError, RateLimitError

# Import ToolManager for loading tools
from ph_agent.agent.tools.tool_manager import ToolManager

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
	
	# Session prompt only; if empty, use None (no system prompt)
	system_prompt = session.system_prompt or None

	# Load tools from Tool Registry
	tools = ToolManager.get_tools(session_name=session_name, user=frappe.session.user)

	# Build conversation history for context (only messages after last summary, INCLUDING the summary as system message)
	# Get last summary message if exists
	last_summary_message = frappe.db.get_value("Chat Session", session_name, "last_summary_message")
	
	if last_summary_message:
		# Get messages created AFTER the last summary (including the summary itself)
		last_summary_doc = frappe.get_doc("Chat Message", last_summary_message)
		prior_messages = frappe.get_all(
			"Chat Message",
			filters={
				"chat_session": session_name,
				"creation": [">=", last_summary_doc.creation],  # Include the summary
			},
			fields=["name", "sender_type", "content", "message_type", "creation"],
			order_by="creation asc",
		)
	else:
		# No summary yet, get all messages
		prior_messages = frappe.get_all(
			"Chat Message",
			filters={"chat_session": session_name},
			fields=["name", "sender_type", "content", "message_type", "creation"],
			order_by="creation asc",
		)
	
	# Build message history in standard OpenAI format
	messages = []
	user_message_added = False
	for m in prior_messages:
		# Skip placeholder messages
		if m.content and "⏳ Generating response" in m.content:
			continue
		if m.message_type == "Summary":
			# Format summary messages specially
			messages.append({
				"role": "system",
				"content": f"Conversation summary: {m.content or ''}"
			})
		elif m.sender_type == "User":
			messages.append({
				"role": "user",
				"content": m.content or ""
			})
			# Check if this is the user_message we're processing
			if m.content == user_message:
				user_message_added = True
		else:
			messages.append({
				"role": "assistant",
				"content": m.content or ""
			})
	
	# Only add user_message if it wasn't already in prior_messages
	if not user_message_added:
		messages.append({
			"role": "user",
			"content": user_message
		})
	
	# Add system prompt if provided
	if system_prompt:
		messages.insert(0, {
			"role": "system",
			"content": system_prompt
		})
	
	try:
		# Check cancellation before starting the expensive API call
		if cancel_check and cancel_check():
			raise asyncio.CancelledError()

		# Use standard OpenAI client for compatibility with DeepSeek
		# Convert tools to OpenAI format if we have any
		openai_tools = None
		if tools:
			openai_tools = []
			for tool in tools:
				# Convert FunctionTool to OpenAI tool format
				# Note: tool.parameters is a method, need to call it: tool.parameters()
				params = tool.parameters() or {}
				# DeepSeek compatibility: add additionalProperties to avoid empty {} args
				if "properties" in params:
					params["additionalProperties"] = False
				openai_tools.append({
					"type": "function",
					"function": {
						"name": tool.name,
						"description": tool.description or "",
						"parameters": params
					}
				})
		
		# Make the API call
		response = asyncio.run(
			openai_client.chat.completions.create(
				model=provider_doc.default_model,
				messages=messages,
				temperature=temperature,
				max_tokens=max_tokens,
				tools=openai_tools if openai_tools else None,
				tool_choice="auto" if openai_tools else None
			)
		)

		# Check cancellation after the API call returns — discard result if cancelled
		if cancel_check and cancel_check():
			raise asyncio.CancelledError()

		# Handle the response
		message = response.choices[0].message
		reply = message.content or ""
		input_tokens = response.usage.prompt_tokens if response.usage else 0
		output_tokens = response.usage.completion_tokens if response.usage else 0
		
		# Check if tool calls were made
		if message.tool_calls:
			# Execute tool calls and get results
			tool_results = []
			for tool_call in message.tool_calls:
				tool_name = tool_call.function.name
				tool_args = json.loads(tool_call.function.arguments)
				
				# Find the matching tool
				matching_tool = None
				for tool in tools:
					if tool.name == tool_name:
						matching_tool = tool
						break
				
				if matching_tool:
					try:
						# Execute the tool with the provided arguments
						# FunctionTool objects can be called directly with keyword arguments
						result = matching_tool(**tool_args)
						tool_results.append({
							"tool_call_id": tool_call.id,
							"role": "tool",
							"name": tool_name,
							"content": str(result)
						})
					except Exception as e:
						frappe.log_error(
							title=f"Tool execution failed for {tool_name}",
							message=f"Args: {tool_args}, Error: {str(e)}",
							reference_doctype="Chat Session",
							reference_name=session_name
						)
						tool_results.append({
							"tool_call_id": tool_call.id,
							"role": "tool",
							"name": tool_name,
							"content": f"Error: {str(e)}"
						})
				else:
					tool_results.append({
						"tool_call_id": tool_call.id,
						"role": "tool",
						"name": tool_name,
						"content": f"Error: Tool '{tool_name}' not found"
					})
			
			# If we have tool results, make another API call with the results
			if tool_results:
				# Add the assistant's message with tool calls to the conversation
				messages.append({
					"role": "assistant",
					"content": reply,
					"tool_calls": [
						{
							"id": tc.id,
							"type": "function",
							"function": {
								"name": tc.function.name,
								"arguments": tc.function.arguments
							}
						}
						for tc in message.tool_calls
					]
				})
				
				# Add tool results to the conversation
				for result in tool_results:
					messages.append({
						"role": result["role"],
						"content": result["content"],
						"tool_call_id": result["tool_call_id"],
						"name": result["name"]
					})
				
				# Make another API call with the tool results
				response2 = asyncio.run(
					openai_client.chat.completions.create(
						model=provider_doc.default_model,
						messages=messages,
						temperature=temperature,
						max_tokens=max_tokens
					)
				)
				
				# Update with the final response
				message2 = response2.choices[0].message
				reply = message2.content or ""
				if response2.usage:
					input_tokens += response2.usage.prompt_tokens
					output_tokens += response2.usage.completion_tokens

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

	return reply, input_tokens, output_tokens


def _accumulate_tool_calls(stream):
	"""
	Accumulate tool call deltas from an OpenAI streaming response.
	
	OpenAI sends tool calls as fragments across multiple chunks using delta.tool_calls.
	Each fragment has an index that identifies which tool call it belongs to.
	
	Returns (full_content, tool_calls_dict, input_tokens, output_tokens).
	tool_calls_dict is {index: {id, name, arguments}}.
	"""
	full_content = ""
	tool_calls = {}
	input_tokens = 0
	output_tokens = 0

	for chunk in stream:
		if chunk.choices:
			delta = chunk.choices[0].delta
			
			# Accumulate text content
			if delta.content is not None:
				full_content += delta.content
			
			# Accumulate tool call deltas
			if delta.tool_calls:
				for tc_delta in delta.tool_calls:
					idx = tc_delta.index
					if idx not in tool_calls:
						tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
					if tc_delta.id:
						tool_calls[idx]["id"] = tc_delta.id
					if tc_delta.function:
						if tc_delta.function.name:
							tool_calls[idx]["name"] = tc_delta.function.name
						if tc_delta.function.arguments:
							tool_calls[idx]["arguments"] += tc_delta.function.arguments
		
		# Capture usage from final chunk
		if chunk.usage:
			input_tokens = chunk.usage.prompt_tokens
			output_tokens = chunk.usage.completion_tokens

	return full_content, tool_calls, input_tokens, output_tokens


def get_agent_response_stream(session_name: str, user_message: str, cancel_check=None, status_callback=None):
	"""
	Call the LLM via OpenAI streaming API and yield content chunks.
	Supports tool calls: if the model requests tools, they are executed between
	two streaming calls. The second streaming call's content is yielded as chunks.
	
	Yields (chunk_content, is_final, input_tokens, output_tokens) where is_final is False for content chunks
	and True for the final chunk containing token usage.
	
	If status_callback is provided, it is called with status messages for the UI.
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
	
	# Session prompt only; if empty, use None (no system prompt)
	system_prompt = session.system_prompt or None

	# Load tools from Tool Registry
	tools = ToolManager.get_tools(session_name=session_name, user=frappe.session.user)

	# Build conversation history for context (only messages after last summary, INCLUDING the summary as system message)
	# Get last summary message if exists
	last_summary_message = frappe.db.get_value("Chat Session", session_name, "last_summary_message")
	
	if last_summary_message:
		# Get messages created AFTER the last summary (including the summary itself)
		last_summary_doc = frappe.get_doc("Chat Message", last_summary_message)
		prior_messages = frappe.get_all(
			"Chat Message",
			filters={
				"chat_session": session_name,
				"creation": [">=", last_summary_doc.creation],  # Include the summary
			},
			fields=["name", "sender_type", "content", "message_type", "creation"],
			order_by="creation asc",
		)
	else:
		# No summary yet, get all messages
		prior_messages = frappe.get_all(
			"Chat Message",
			filters={"chat_session": session_name},
			fields=["name", "sender_type", "content", "message_type", "creation"],
			order_by="creation asc",
		)
	
	messages = []
	user_message_added = False
	for m in prior_messages:
		# Skip placeholder messages
		if m.content and "⏳ Generating response" in m.content:
			continue
		if m.message_type == "Summary":
			# Format summary messages specially
			messages.append({"role": "system", "content": f"Conversation summary: {m.content or ''}"})
		elif m.sender_type == "User":
			messages.append({"role": "user", "content": m.content or ""})
			# Check if this is the user_message we're processing
			if m.content == user_message:
				user_message_added = True
		else:
			messages.append({"role": "assistant", "content": m.content or ""})
	
	# Only add user_message if it wasn't already in prior_messages
	if not user_message_added:
		messages.append({"role": "user", "content": user_message})
		
	# Add system prompt if provided
	if system_prompt:
		messages.insert(0, {"role": "system", "content": system_prompt})

	try:
		# Check cancellation before starting the expensive API call
		if cancel_check and cancel_check():
			raise asyncio.CancelledError()

		# Convert tools to OpenAI format if we have any
		openai_tools = None
		if tools:
			openai_tools = []
			for tool in tools:
				# Convert FunctionTool to OpenAI tool format
				params = tool.parameters() or {}
				# DeepSeek compatibility: add additionalProperties to avoid empty {} args
				if "properties" in params:
					params["additionalProperties"] = False
				openai_tools.append({
					"type": "function",
					"function": {
						"name": tool.name,
						"description": tool.description or "",
						"parameters": params
					}
				})
		
		# ---- FIRST STREAMING CALL (with tools if available) ----
		stream = openai_client.chat.completions.create(
			model=provider_doc.default_model,
			messages=messages,
			temperature=temperature,
			max_tokens=max_tokens,
			stream=True,
			tools=openai_tools if openai_tools else None,
			tool_choice="auto" if openai_tools else None,
		)

		full_content, tool_calls, input_tokens, output_tokens = _accumulate_tool_calls(stream)

		# Check cancellation after first stream
		if cancel_check and cancel_check():
			raise asyncio.CancelledError()

		# ---- TOOL EXECUTION ----
		if tool_calls:
			if status_callback:
				status_callback(frappe._("Executing tools…"))

			# Sort tool calls by index to maintain order
			sorted_indices = sorted(tool_calls.keys())
			
			# Build the assistant message with tool_calls for the conversation
			assistant_tool_calls = []
			for idx in sorted_indices:
				tc = tool_calls[idx]
				assistant_tool_calls.append({
					"id": tc["id"],
					"type": "function",
					"function": {
						"name": tc["name"],
						"arguments": tc["arguments"]
					}
				})
			
			# Add assistant message with tool calls to conversation
			messages.append({
				"role": "assistant",
				"content": full_content or None,
				"tool_calls": assistant_tool_calls
			})
			
			# Execute each tool and collect results
			for idx in sorted_indices:
				tc = tool_calls[idx]
				tool_name = tc["name"]
				tool_args_raw = tc["arguments"]
				
				try:
					tool_args = json.loads(tool_args_raw) if tool_args_raw else {}
				except json.JSONDecodeError:
					tool_args = {}
				
				# Find matching tool
				matching_tool = None
				for tool in tools:
					if tool.name == tool_name:
						matching_tool = tool
						break
				
				if matching_tool:
					try:
						result = matching_tool(**tool_args)
						messages.append({
							"tool_call_id": tc["id"],
							"role": "tool",
							"name": tool_name,
							"content": str(result)
						})
					except Exception as e:
						frappe.log_error(
							title=f"Tool execution failed for {tool_name}",
							message=f"Args: {tool_args}, Error: {str(e)}",
							reference_doctype="Chat Session",
							reference_name=session_name
						)
						messages.append({
							"tool_call_id": tc["id"],
							"role": "tool",
							"name": tool_name,
							"content": f"Error: {str(e)}"
						})
				else:
					messages.append({
						"tool_call_id": tc["id"],
						"role": "tool",
						"name": tool_name,
						"content": f"Error: Tool '{tool_name}' not found"
					})
			
			# Check cancellation before second call
			if cancel_check and cancel_check():
				raise asyncio.CancelledError()
			
			if status_callback:
				status_callback(frappe._("Calling AI…"))
			
			# ---- SECOND STREAMING CALL (no tools, just the result) ----
			stream2 = openai_client.chat.completions.create(
				model=provider_doc.default_model,
				messages=messages,
				temperature=temperature,
				max_tokens=max_tokens,
				stream=True,
			)
			
			full_content2 = ""
			input_tokens2 = 0
			output_tokens2 = 0
			
			for chunk in stream2:
				if cancel_check and cancel_check():
					raise asyncio.CancelledError()
				
				if chunk.choices and chunk.choices[0].delta.content is not None:
					content_chunk = chunk.choices[0].delta.content
					full_content2 += content_chunk
					yield content_chunk, False, 0, 0
				
				if chunk.usage:
					input_tokens2 = chunk.usage.prompt_tokens
					output_tokens2 = chunk.usage.completion_tokens
			
			# Yield final chunk with accumulated tokens from both calls
			yield "", True, input_tokens + input_tokens2, output_tokens + output_tokens2
		else:
			# No tool calls — just yield the accumulated content from the first stream
			# The content was already captured by _accumulate_tool_calls but not yielded
			# We need to re-stream it. Since we already consumed the stream, we'll
			# yield it here as a single chunk plus final.
			# (In practice, for the no-tool case we could optimize by yielding during
			#  accumulation, but this keeps the flow simpler.)
			# Actually, let's yield the content that was already accumulated.
			if full_content:
				yield full_content, False, 0, 0
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
	
	prompt = f"User: {user_message}\nAssistant: {agent_reply}"

	try:
		# Use standard OpenAI client instead of agent_framework to avoid 404 errors
		response = asyncio.run(
			openai_client.chat.completions.create(
				model=provider_doc.default_model,
				messages=[
					{
						"role": "system",
						"content": "Generate a concise 5-8 word title that summarises the following conversation. Return only the title text — no quotes, no punctuation at the end, no explanation."
					},
					{
						"role": "user",
						"content": prompt
					}
				],
				temperature=title_temperature,
				max_tokens=max_tokens,
			)
		)
		return (response.choices[0].message.content or "").strip()
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
		# Use standard OpenAI client instead of agent_framework to avoid 404 errors
		response = asyncio.run(
			openai_client.chat.completions.create(
				model=provider_doc.default_model,
				messages=[
					{
						"role": "system",
						"content": "You are a conversation summarizer. Your task is to create a concise summary of a chat conversation. Focus on summarizing the FLOW of the conversation - who said what, what questions were asked, what answers were given. DO NOT just repeat factual information from the conversation. Instead, summarize the conversation structure. Example format: 'The user asked about [topic]. I explained [key points]. We discussed [main topics].' Keep the summary to 2-3 sentences maximum. Return only the summary text — no introductory phrases, no markdown, no extra text."
					},
					{
						"role": "user",
						"content": conversation_text
					}
				],
				temperature=summary_temperature,
				max_tokens=max_tokens,
			)
		)
		return (response.choices[0].message.content or "").strip()
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
	
	# Build a short summary of the conversation as context
	context_parts = []
	for msg in conversation_history[-6:]:  # last 6 messages max for context
		role = "User" if msg.get("role") == "user" else "Assistant"
		context_parts.append(f"{role}: {msg.get('content', '')[:500]}")
	context = "\n".join(context_parts)

	try:
		# Use standard OpenAI client instead of agent_framework to avoid 404 errors
		response = asyncio.run(
			openai_client.chat.completions.create(
				model=provider_doc.default_model,
				messages=[
					{
						"role": "system",
						"content": "You are a helpful assistant that suggests relevant follow-up questions based on the conversation. Provide exactly 3 to 5 concise questions that the user might want to ask next. Return only a JSON array of strings — no explanation, no markdown, no extra text. Example: [\"Question one?\", \"Question two?\", \"Question three?\"]"
					},
					{
						"role": "user",
						"content": context
					}
				],
				temperature=1.0,
				max_tokens=max_tokens,
				response_format={"type": "json_object"}
			)
		)
		
		raw = (response.choices[0].message.content or "").strip()
		if raw:
			# Try to parse as JSON
			try:
				data = json.loads(raw)
				# Look for suggestions in the JSON response
				if isinstance(data, dict):
					# Try common keys
					for key in ["suggestions", "questions", "follow_up", "response"]:
						if key in data and isinstance(data[key], list):
							suggestions = data[key]
							return [str(s) for s in suggestions if s][:5]
					# If no specific key found, try to extract any list
					for value in data.values():
						if isinstance(value, list):
							suggestions = value
							return [str(s) for s in suggestions if s][:5]
				elif isinstance(data, list):
					return [str(s) for s in data if s][:5]
			except json.JSONDecodeError:
				# If not valid JSON, try to extract suggestions from text
				pass
		
		return []
	except Exception:
		frappe.log_error(
			title=f"Suggestion generation failed for session {session_name}",
			reference_doctype="Chat Session",
			reference_name=session_name
		)
		return []
