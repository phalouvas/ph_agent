import asyncio
import json
import time
import traceback

import frappe
from ph_agent.agent.framework_agent import (
	_fix_agent_response_text,
	generate_conversation_summary,
	generate_followup_suggestions,
	generate_session_title,
	get_agent_response,
	get_agent_response_stream,
	run_after_approval,
)
from ph_agent.agent.tools.tool_manager import ToolManager
from ph_agent.ph_agent.doctype.user_token_usage.user_token_usage import UserTokenUsage
from ph_agent.api.token_utils import _atomic_update_chat_session_tokens, _atomic_update_user_token_usage
from ph_agent.utils.debug_logger import debug_log
from ph_agent.utils.file_extractor import extract_file_text



# ---------------------------------------------------------------------------
# Token usage & cost helpers
# ---------------------------------------------------------------------------


def _credit_user_token_usage(session_name: str, input_tokens: int, output_tokens: int, cache_hit_tokens: int = 0) -> None:
	"""Accumulate token counts and cost into the user's User Token Usage record.

	Calculates cost from LLM Provider pricing + per-user overrides using a
	3-tier formula:
	  cost = (cache_miss * eff_input_rate + cache_hit * eff_cache_rate + output * eff_output_rate) / 1_000_000

	Safe to call for both temporary and permanent sessions — the User Token
	Usage record survives temporary session cleanup.

	Args:
		session_name: Chat Session name (used to look up user + provider).
		input_tokens: Input tokens to add.
		output_tokens: Output tokens to add.
		cache_hit_tokens: Input tokens that were cache hits (charged at cache rate).
	"""
	try:
		session_doc = frappe.get_doc("Chat Session", session_name)
		user = session_doc.user
		provider_name = session_doc.llm_provider

		# Get or create the user token usage record (defense-in-depth)
		usage_name = UserTokenUsage.get_or_create_for_user(user)

		# Read provider pricing
		provider = frappe.get_doc("LLM Provider", provider_name)
		provider_input_rate = float(provider.input_cost_per_1m_tokens or 0)
		provider_output_rate = float(provider.output_cost_per_1m_tokens or 0)
		provider_cache_rate = float(provider.cache_hit_cost_per_1m_tokens or 0)

		# Read user overrides (default to 0 if not set)
		usage_doc = frappe.get_doc("User Token Usage", usage_name)
		override_input = float(usage_doc.input_cost_over_per_1m or 0)
		override_output = float(usage_doc.output_cost_over_per_1m or 0)
		override_cache = float(usage_doc.cache_hit_cost_over_per_1m or 0)

		# Effective rates = provider base + user override
		effective_input_rate = provider_input_rate + override_input
		effective_output_rate = provider_output_rate + override_output
		effective_cache_rate = provider_cache_rate + override_cache

		# 3-tier cost calculation
		cache_miss_tokens = max(0, input_tokens - cache_hit_tokens)
		cost = (
			cache_miss_tokens * effective_input_rate
			+ cache_hit_tokens * effective_cache_rate
			+ output_tokens * effective_output_rate
		) / 1_000_000

		# Atomic update — increment counters directly in SQL to avoid races
		_atomic_update_user_token_usage(usage_name, input_tokens, output_tokens, cache_hit_tokens, cost)
	except Exception:
		frappe.log_error(
			title="Failed to credit user token usage",
			message=f"Session: {session_name}, Input: {input_tokens}, Output: {output_tokens}, Cache hit: {cache_hit_tokens}",
		)


def _calculate_message_cost(session_name: str, input_tokens: int, output_tokens: int, cache_hit_tokens: int = 0) -> float:
	"""Calculate the EUR cost of a single message based on provider pricing + user overrides.

	Uses a 3-tier formula:
	  cost = (cache_miss * eff_input_rate + cache_hit * eff_cache_rate + output * eff_output_rate) / 1_000_000

	Args:
		session_name: Chat Session name.
		input_tokens: Input tokens for this message.
		output_tokens: Output tokens for this message.
		cache_hit_tokens: Input tokens that were cache hits (charged at cache rate).

	Returns:
		Cost in EUR.
	"""
	try:
		session_doc = frappe.get_doc("Chat Session", session_name)
		user = session_doc.user
		provider_name = session_doc.llm_provider

		provider = frappe.get_doc("LLM Provider", provider_name)
		provider_input_rate = float(provider.input_cost_per_1m_tokens or 0)
		provider_output_rate = float(provider.output_cost_per_1m_tokens or 0)
		provider_cache_rate = float(provider.cache_hit_cost_per_1m_tokens or 0)

		usage_name = UserTokenUsage.get_or_create_for_user(user)
		usage_doc = frappe.get_doc("User Token Usage", usage_name)
		override_input = float(usage_doc.input_cost_over_per_1m or 0)
		override_output = float(usage_doc.output_cost_over_per_1m or 0)
		override_cache = float(usage_doc.cache_hit_cost_over_per_1m or 0)

		effective_input_rate = provider_input_rate + override_input
		effective_output_rate = provider_output_rate + override_output
		effective_cache_rate = provider_cache_rate + override_cache

		cache_miss_tokens = max(0, input_tokens - cache_hit_tokens)
		return (
			cache_miss_tokens * effective_input_rate
			+ cache_hit_tokens * effective_cache_rate
			+ output_tokens * effective_output_rate
		) / 1_000_000
	except Exception:
		return 0.0


# ---------------------------------------------------------------------------
# Auto-compaction helpers
# ---------------------------------------------------------------------------

def _is_recently_summarized(session: str, min_interval_seconds: int = 60) -> bool:
	"""Check if an auto-summary was created recently to avoid churn."""
	last_summary = frappe.db.get_value("Chat Session", session, "last_summary_message")
	if not last_summary:
		return False
	creation = frappe.db.get_value("Chat Message", last_summary, "creation")
	if not creation:
		return False
	elapsed = (frappe.utils.now_datetime() - creation).total_seconds()
	return elapsed < min_interval_seconds


def _estimate_system_overhead(session_name: str) -> int:
	"""Estimate token overhead from system prompt + tool definitions.

	Returns the estimated token count for static overhead that is not
	accounted for by ``estimated_conversation_tokens`` (which only tracks
	user+assistant API tokens).
	"""
	session_doc = frappe.get_doc("Chat Session", session_name)
	system_prompt = session_doc.system_prompt or ""
	overhead = 0

	# System prompt: ~4 chars per token for English text
	if system_prompt:
		overhead += len(system_prompt) // 4

	# Tool definitions: ~2 chars per token for JSON schemas
	try:
		tools = ToolManager.get_tools(session_name=session_name, persona=session_doc.persona)
		for tool_obj in tools:
			if hasattr(tool_obj, "schema") and tool_obj.schema:
				schema_str = json.dumps(tool_obj.schema, separators=(",", ":"))
				overhead += len(schema_str) // 2
			elif hasattr(tool_obj, "description") and tool_obj.description:
				overhead += len(tool_obj.description) // 4
	except Exception:
		pass  # Best-effort; overhead is a soft estimate

	# Conversation structure overhead (~20 % buffer)
	overhead = int(overhead * 1.2)
	return overhead


def _get_total_estimated_tokens(session: str) -> tuple[int, int]:
	"""Return (total_estimated_tokens, overhead_tokens) for threshold checks."""
	session_doc = frappe.get_doc("Chat Session", session)
	conversation_tokens = session_doc.estimated_conversation_tokens or 0
	overhead = _estimate_system_overhead(session)
	return conversation_tokens + overhead, overhead


def _emergency_prune_messages(session: str, target_percentage: int = 80) -> int:
	"""Delete oldest non-summary messages when auto-summary fails and tokens exceed 95 %.

	Returns the number of messages deleted.
	"""
	from frappe.utils import now_datetime

	session_doc = frappe.get_doc("Chat Session", session)
	provider_doc = frappe.get_doc("LLM Provider", session_doc.llm_provider)
	context_length = provider_doc.context_length or 128000

	total_tokens, _ = _get_total_estimated_tokens(session)
	token_percentage = (total_tokens / context_length) * 100 if context_length > 0 else 0

	if token_percentage < 95:
		return 0  # Not emergency territory

	last_summary = session_doc.last_summary_message
	deleted_count = 0

	while True:
		total_tokens, _ = _get_total_estimated_tokens(session)
		token_percentage = (total_tokens / context_length) * 100 if context_length > 0 else 0

		if token_percentage < target_percentage:
			break

		# Check how many non-summary messages remain
		filters = {"chat_session": session, "message_type": ["!=", "Summary"]}
		if last_summary:
			last_summary_doc = frappe.get_doc("Chat Message", last_summary)
			filters["creation"] = [">", last_summary_doc.creation]

		remaining = frappe.get_all(
			"Chat Message",
			filters=filters,
			fields=["name", "content"],
			order_by="creation asc",
		)

		# Keep at least 2 turns (4 messages) to preserve conversation quality
		if len(remaining) <= 4:
			break

		# Delete the oldest non-summary message
		oldest = remaining[0]
		try:
			frappe.delete_doc("Chat Message", oldest["name"], ignore_permissions=True)
			deleted_count += 1
		except Exception:
			# If one fails, skip it
			pass

	if deleted_count:
		frappe.db.commit()
		# Recompute and publish a token update
		frappe.publish_realtime(
			event="token_update",
			message={
				"session": session,
				"current_tokens": 0,  # Reset view; pruning resets the estimate
				"context_length": context_length,
				"percentage": 0,
			},
room="website",
		)

	return deleted_count


def _perform_auto_summary(session: str, enqueued_by: str | None = None,
						  emit_status: callable | None = None,
						  is_async: bool = False) -> bool:
	"""Summarize conversation since last summary. Returns True if summary was created.

	Args:
		session: Chat Session name.
		enqueued_by: User to notify via real-time events.
		emit_status: Status callback function (optional).
		is_async: If True, skip real-time event emission (for post-response async jobs).

	Returns:
		True if a summary was successfully created, False otherwise.
	"""
	if emit_status is None:
		def _noop(msg):
			pass
		emit_status = _noop

	session_doc = frappe.get_doc("Chat Session", session)
	provider_doc = frappe.get_doc("LLM Provider", session_doc.llm_provider)
	context_length = provider_doc.context_length or 128000

	# Get messages since last summary
	last_summary = session_doc.last_summary_message
	if last_summary:
		last_summary_doc = frappe.get_doc("Chat Message", last_summary)
		messages = frappe.get_all(
			"Chat Message",
			filters={
				"chat_session": session,
				"creation": [">", last_summary_doc.creation],
				"message_type": ["!=", "Summary"],
			},
			fields=["name", "sender_type", "content", "creation"],
			order_by="creation asc",
		)
	else:
		messages = frappe.get_all(
			"Chat Message",
			filters={
				"chat_session": session,
				"message_type": ["!=", "Summary"],
			},
			fields=["name", "sender_type", "content", "creation"],
			order_by="creation asc",
		)

	if not messages:
		return False

	# Format conversation history
	conversation_history = []
	for msg in messages:
		role = "user" if msg.sender_type == "User" else "assistant"
		conversation_history.append({"role": role, "content": msg.content or ""})

	emit_status(frappe._("Summarizing conversation…"))

	# Generate summary
	try:
		summary = generate_conversation_summary(session, conversation_history)
	except Exception as e:
		frappe.log_error(
			title=f"Auto-summarization failed for session {session}",
			message=f"{e}\n{traceback.format_exc()}",
		)
		# Emergency fallback: if tokens exceed 95 %, prune oldest messages
		total_tokens, _ = _get_total_estimated_tokens(session)
		token_percentage = (total_tokens / context_length) * 100 if context_length > 0 else 0
		if token_percentage >= 95:
			emit_status(frappe._("Freeing up context space…"))
			_emergency_prune_messages(session)
		return False

	if not summary:
		return False

	# Create summary message
	summary_msg = frappe.get_doc(
		{
			"doctype": "Chat Message",
			"chat_session": session,
			"sender_type": "Agent",
			"message_type": "Summary",
			"content": "*📋 Summary*\n\n" + summary,
		}
	).insert(ignore_permissions=False)
	frappe.db.commit()

	# Update session with summary reference and reset token count
	frappe.db.set_value(
		"Chat Session",
		session,
		{
			"last_summary_message": summary_msg.name,
			"estimated_conversation_tokens": 0,
			"token_warning_sent": 0,
		},
	)
	frappe.db.commit()

	# Publish real-time events (skip if running asynchronously after user moved on)
	if not is_async:
		frappe.publish_realtime(
			event="token_update",
			message={
				"session": session,
				"current_tokens": 0,
				"context_length": context_length,
				"percentage": 0,
			},
			room="website",
		)

		frappe.publish_realtime(
			event="new_message",
			message={
				"session": session,
				"name": summary_msg.name,
				"sender_type": "Agent",
				"message_type": "Summary",
				"content": "*📋 Summary*\n\n" + summary,
				"creation": str(summary_msg.creation),
			},
			room="website",
		)

	return True


def _call_agent_background(session, content, file_names, enqueued_by, agent_msg_name=None):
	"""
	Background job: optionally extract PDFs, call the LLM agent, store the reply,
	and push realtime events back to the user who enqueued the job.
	"""
	job_start = time.time()
	debug_log(
		"_call_agent_background entry",
		f"Session: {session}, Content length: {len(content)}, Files: {len(file_names) if file_names else 0}, "
		f"Regenerating: {bool(agent_msg_name)}, Enqueued by: {enqueued_by}",
		session=session,
	)

	def emit_status(msg):
		frappe.publish_realtime(
			event="agent_status",
			message={"session": session, "status": msg},
			room="website",
		)

	lock_key = f"ph_agent:lock:{session}"
	cancel_key = f"ph_agent:cancel:{session}"

	def release_lock():
		from frappe.utils.background_jobs import get_redis_conn
		get_redis_conn().delete(lock_key)

	def is_cancelled():
		return bool(frappe.cache().get_value(cancel_key))

	# Check for cancellation before doing any work
	if is_cancelled():
		release_lock()
		frappe.cache().delete_value(cancel_key)
		emit_status("")
		frappe.publish_realtime(
			event="generation_cancelled",
			message={"session": session},
			room="website",
		)
		return

	# Get provider settings early for file size limits
	session_doc = frappe.get_doc("Chat Session", session)
	provider_doc = frappe.get_doc("LLM Provider", session_doc.llm_provider)
	
	# Build enriched content: substitute {{variable}} placeholders with
	# extracted file text, then append file metadata for tools.
	agent_content = content
	if file_names:
		# Store file names in cache keyed by session so tools can auto-attach
		frappe.cache().set_value(
			f"ph_agent:files:{session}",
			list(file_names),
			expires_in_sec=600,
		)
		file_texts = []
		failed_files = []
		emit_status(frappe._("Extracting file contents…"))
		for file_name in file_names:
			if is_cancelled():
				release_lock()
				frappe.cache().delete_value(cancel_key)
				emit_status("")
				frappe.publish_realtime(
					event="generation_cancelled",
					message={"session": session},
					room="website",
				)
				return
			# Get max file size from provider settings
			extract_start = time.time()
			max_size_mb = provider_doc.max_file_size_mb or 50
			text, file_type_label = extract_file_text(file_name, max_size_mb=max_size_mb)
			extract_elapsed = time.time() - extract_start
			if text:
				filename = frappe.db.get_value("File", file_name, "file_name")
				file_texts.append(f"[{file_type_label}: {filename}]\n{text}")
				debug_log(
					"File extraction complete",
					f"Session: {session}, File: {filename}, Type: {file_type_label}, "
					f"Extracted length: {len(text)}, Elapsed: {extract_elapsed:.2f}s",
					session=session,
				)
			else:
				filename = frappe.db.get_value("File", file_name, "file_name")
				failed_files.append(filename)
				debug_log(
					"File extraction returned no text",
					f"Session: {session}, File: {filename}, Elapsed: {extract_elapsed:.2f}s",
					session=session,
					level="WARNING",
				)
		if file_texts:
			# Substitute {{variable}} placeholders in the template with the
			# extracted file text so the LLM sees the actual content instead
			# of literal "{{actual_text}}" markers.
			combined_text = "\n\n".join(file_texts)
			import re
			agent_content = re.sub(
				r"\{\{\w+\}\}",
				combined_text,
				content,
			)
			# If no {{variable}} placeholders were found, append text at end
			if agent_content == content:
				agent_content = content + "\n\n" + combined_text

			# Build a metadata block with File doc names so the agent can use
			# attach_files_to_record to link files to created records.
			# Placed AFTER extracted text so it doesn't interrupt the flow.
			file_meta_lines = []
			for file_name in file_names:
				filename = frappe.db.get_value("File", file_name, "file_name")
				file_meta_lines.append(f"- `{file_name}` ({filename})")
			file_meta_block = (
				"\n\n**Attached Files (use these names with attach_files_to_record):**\n"
				+ "\n".join(file_meta_lines)
			)
			agent_content += file_meta_block

			if failed_files:
				debug_log(
					"Some files could not be extracted",
					f"Session: {session}, Failed: {', '.join(failed_files)}",
					session=session,
					level="WARNING",
				)
		elif failed_files:
			# All attached files failed — create an error message in the
			# chat so the user knows why no response was generated.
			failed_names = ", ".join(failed_files)
			error_content = frappe._(
				"Could not extract text from the attached file(s): **{0}**. "
				"The file may be image-based (scanned), password-protected, or corrupted. "
				"Please try a different file or paste the text directly."
			).format(failed_names)
			error_msg = frappe.get_doc(
				{
					"doctype": "Chat Message",
					"chat_session": session,
					"sender_type": "Agent",
					"message_type": "Agent",
					"content": error_content,
				}
			).insert(ignore_permissions=False)
			frappe.db.commit()
			release_lock()
			frappe.cache().delete_value(cancel_key)
			emit_status("")
			frappe.publish_realtime(
				event="new_message",
				message={
					"session": session,
					"name": error_msg.name,
					"sender_type": "Agent",
					"content": error_content,
					"creation": str(error_msg.creation),
				},
				room="website",
			)
			return

	emit_status(frappe._("Calling AI…"))

	# Check if streaming should be used
	use_streaming = provider_doc.supports_streaming and session_doc.enable_streaming

	# Create placeholder message for both streaming and non-streaming
	# This ensures the frontend shows a spinner immediately
	agent_msg = frappe.get_doc(
		{
			"doctype": "Chat Message",
			"chat_session": session,
			"sender_type": "Agent",
			"message_type": "Agent",
			"content": "⏳ Generating response...",  # Placeholder content
		}
	).insert(ignore_permissions=False)
	frappe.db.commit()
	
	# If regenerating, delete the old agent message before creating the new one
	if agent_msg_name and frappe.db.exists("Chat Message", agent_msg_name):
		# Delete User Memory records linked to this message
		frappe.db.delete("User Memory", {"source_message": agent_msg_name})
		frappe.delete_doc("Chat Message", agent_msg_name, ignore_permissions=True)
		frappe.db.commit()
	
	placeholder_payload = {
		"session": session,
		"name": agent_msg.name,
		"sender_type": "Agent",
		"content": "⏳ Generating response...",  # Show placeholder content in UI
		"creation": str(agent_msg.creation),
		"is_streaming_placeholder": use_streaming,  # True for streaming, False for non-streaming
	}
	if agent_msg_name:
		placeholder_payload["old_message_id"] = agent_msg_name
	
	frappe.publish_realtime(
		event="new_message",
		message=placeholder_payload,
		room="website",
	)
	# Track whether auto-summary ran in pre-call phase
	_auto_summary_performed = False
	
	# Check if we need to auto-summarize before making the API call
	session_doc = frappe.get_doc("Chat Session", session)
	provider_doc = frappe.get_doc("LLM Provider", session_doc.llm_provider)
	
	# Get context length and auto-summary threshold
	context_length = provider_doc.context_length or 128000
	auto_summary_threshold = provider_doc.auto_summary_threshold or 85
	
	# Calculate current percentage
	current_tokens = session_doc.estimated_conversation_tokens or 0
	token_percentage = (current_tokens / context_length) * 100 if context_length > 0 else 0
	
	# Auto-summarize if threshold exceeded and not recently summarized
	if token_percentage > auto_summary_threshold and not _is_recently_summarized(session):
		_auto_summary_performed = _perform_auto_summary(session, enqueued_by, emit_status)
		if _auto_summary_performed:
			emit_status(frappe._("Conversation summarized. Continuing..."))
	try:
		if use_streaming:
			# Streaming path
			full_content = ""
			full_reasoning = ""
			input_tokens = 0
			output_tokens = 0
			cache_hit_tokens = 0
			streaming_successful = False
			_new_message_sent = False
			approval_data = None
			
			debug_log(
				"Starting streaming path",
				f"Session: {session}, Content length: {len(agent_content)}",
				session=session,
			)
			
			try:
				for chunk, is_final, chunk_input_tokens, chunk_output_tokens, chunk_cache_hit_tokens in get_agent_response_stream(session, agent_content, cancel_check=is_cancelled, status_callback=emit_status, skip_session_state=bool(agent_msg_name)):
					if is_cancelled():
						raise asyncio.CancelledError()
						
					if is_final:
						# Check if this is an approval request (chunk is a dict with approval_data)
						if isinstance(chunk, dict) and chunk.get("approval_needed"):
							approval_data = chunk
							streaming_successful = True
						elif isinstance(chunk, tuple):
							# (response_text, reasoning_content) — response_text is empty
							# because content was already streamed via chunks.
							# Only extract reasoning and token counts.
							response_text, reasoning_text = chunk
							full_reasoning = reasoning_text or full_reasoning
							input_tokens = chunk_input_tokens
							output_tokens = chunk_output_tokens
							cache_hit_tokens = chunk_cache_hit_tokens
							streaming_successful = True
						else:
							# Normal final chunk with token usage
							input_tokens = chunk_input_tokens
							output_tokens = chunk_output_tokens
							cache_hit_tokens = chunk_cache_hit_tokens
							streaming_successful = True
					elif isinstance(chunk, tuple) and chunk[0] == "reasoning_chunk":
						# Reasoning content chunk
						reasoning_delta = chunk[1]
						full_reasoning += reasoning_delta
						# Publish reasoning chunk via realtime
						frappe.publish_realtime(
							event="reasoning_chunk",
							message={
								"session": session,
								"message_id": agent_msg.name,
								"chunk": reasoning_delta,
							},
							room="website",
						)
					else:
						# Content chunk
						full_content += chunk
						# Publish chunk via realtime
						frappe.publish_realtime(
							event="message_chunk",
							message={
								"session": session,
								"message_id": agent_msg.name,
								"chunk": chunk,
								"is_final": False
							},
							room="website",
						)
				
				if approval_data:
					# Credit tokens before entering approval flow (otherwise lost on early return)
					_atomic_update_chat_session_tokens(session, input_tokens, output_tokens, cache_hit_tokens)
					_credit_user_token_usage(session, input_tokens, output_tokens, cache_hit_tokens)
					# Handle approval flow
					_handle_tool_approval(session, agent_msg, approval_data, enqueued_by)
					release_lock()
					emit_status("")
					return
				
				if streaming_successful:
					# Build content with reasoning block if reasoning exists
					processed_content = _fix_agent_response_text(full_content)
					if full_reasoning:
						reasoning_html = (
							f'<details class="ph-reasoning-block">\n'
							f'    <summary>\U0001f913 Thinking process</summary>\n'
							f'{full_reasoning}\n'
							f'</details>\n\n'
						)
						agent_msg.content = reasoning_html + processed_content
						agent_msg.reasoning_content = full_reasoning
					else:
						agent_msg.content = processed_content
					agent_msg.input_tokens = input_tokens
					agent_msg.output_tokens = output_tokens
					agent_msg.cache_hit_tokens = cache_hit_tokens
					agent_msg.cost = _calculate_message_cost(session, input_tokens, output_tokens, cache_hit_tokens)
					agent_msg.message_type = "Agent"
					agent_msg.save(ignore_permissions=True)
					frappe.db.commit()
					_new_message_sent = True
					
					# Publish the final message HTML FIRST so the frontend
					# has the correct content (with reasoning block and
					# vue-chat formatting) before clearing the processing
					# state. Order matters: new_message delivers the
					# authoritative content; message_chunk(is_final) only
					# clears the spinner and typing indicator.
					frappe.publish_realtime(
						event="new_message",
						message={
							"session": session,
							"name": agent_msg.name,
							"sender_type": "Agent",
							"content": agent_msg.content,
							"creation": str(agent_msg.creation),
						},
						room="website",
					)
					frappe.publish_realtime(
						event="message_chunk",
						message={
							"session": session,
							"message_id": agent_msg.name,
							"chunk": "",
							"is_final": True,
						},
						room="website",
					)
					
					# Also clear the status indicator via agent_status as a
					# fallback for any frontend state that the chunk event
					# might have missed.
					emit_status("")
				else:
					# Streaming didn't complete successfully, fall back
					raise Exception("Streaming did not complete successfully")
				
			except Exception as stream_error:
				# If streaming fails, fall back to non-streaming
				debug_log(
					"Streaming failed, falling back to non-streaming",
					f"Session: {session}, Error: {stream_error}",
					session=session,
					level="WARNING",
				)
				frappe.log_error(
					title=f"Streaming failed for session {session}, falling back to non-streaming",
					message=f"{stream_error}\n{traceback.format_exc()}"
				)
				# Reload agent_msg to avoid TimestampMismatchError (it was committed earlier)
				agent_msg = frappe.get_doc("Chat Message", agent_msg.name)
				# Fall back to non-streaming - update the existing placeholder
				use_streaming = False
				try:
					reply, input_tokens, output_tokens, cache_hit_tokens, approval_data, reasoning_content = get_agent_response(session, agent_content, cancel_check=is_cancelled, skip_session_state=bool(agent_msg_name))
				except Exception as fallback_error:
					frappe.log_error(
						title=f"Non-streaming fallback also failed for session {session}",
						message=f"{fallback_error}\n{traceback.format_exc()}"
					)
					raise  # Let the outer except Exception handle it
				
				if approval_data:
					# Credit tokens before entering approval flow (otherwise lost on early return)
					_atomic_update_chat_session_tokens(session, input_tokens, output_tokens, cache_hit_tokens)
					_credit_user_token_usage(session, input_tokens, output_tokens, cache_hit_tokens)
					# Handle approval flow
					_handle_tool_approval(session, agent_msg, approval_data, enqueued_by)
					release_lock()
					emit_status("")
					return
				
				# Build content with reasoning block if reasoning exists
				processed_content = _fix_agent_response_text(reply)
				if reasoning_content:
					reasoning_html = (
						f'<details class="ph-reasoning-block">\n'
						f'    <summary>\U0001f913 Thinking process</summary>\n'
						f'{reasoning_content}\n'
						f'</details>\n\n'
					)
					agent_msg.content = reasoning_html + processed_content
					agent_msg.reasoning_content = reasoning_content
				else:
					agent_msg.content = processed_content
				agent_msg.input_tokens = input_tokens
				agent_msg.output_tokens = output_tokens
				agent_msg.cache_hit_tokens = cache_hit_tokens
				agent_msg.cost = _calculate_message_cost(session, input_tokens, output_tokens, cache_hit_tokens)
				agent_msg.save(ignore_permissions=True)
				frappe.db.commit()
				emit_status("")
		else:
			# Non-streaming path - update the existing placeholder message
			debug_log(
				"Starting non-streaming path",
				f"Session: {session}, Content length: {len(agent_content)}",
				session=session,
			)
			# Reload agent_msg to avoid TimestampMismatchError (placeholder was committed)
			agent_msg = frappe.get_doc("Chat Message", agent_msg.name)
			reply, input_tokens, output_tokens, cache_hit_tokens, approval_data, reasoning_content = get_agent_response(session, agent_content, cancel_check=is_cancelled, skip_session_state=bool(agent_msg_name))
			
			if approval_data:
				# Credit tokens before entering approval flow (otherwise lost on early return)
				_atomic_update_chat_session_tokens(session, input_tokens, output_tokens, cache_hit_tokens)
				_credit_user_token_usage(session, input_tokens, output_tokens, cache_hit_tokens)
				# Handle approval flow
				_handle_tool_approval(session, agent_msg, approval_data, enqueued_by)
				release_lock()
				emit_status("")
				return
			
			# Build content with reasoning block if reasoning exists
			processed_content = _fix_agent_response_text(reply)
			if reasoning_content:
				reasoning_html = (
					f'<details class="ph-reasoning-block">\n'
					f'    <summary>\U0001f913 Thinking process</summary>\n'
					f'{reasoning_content}\n'
					f'</details>\n\n'
				)
				agent_msg.content = reasoning_html + processed_content
				agent_msg.reasoning_content = reasoning_content
			else:
				agent_msg.content = processed_content
			agent_msg.input_tokens = input_tokens
			agent_msg.output_tokens = output_tokens
			agent_msg.cache_hit_tokens = cache_hit_tokens
			agent_msg.cost = _calculate_message_cost(session, input_tokens, output_tokens, cache_hit_tokens)
			agent_msg.save(ignore_permissions=True)
			frappe.db.commit()
			emit_status("")
			
	except asyncio.CancelledError:
		# Clean up placeholder message
		if agent_msg and frappe.db.exists("Chat Message", agent_msg.name):
			frappe.delete_doc("Chat Message", agent_msg.name, ignore_permissions=True)
			frappe.db.commit()
			
		release_lock()
		frappe.cache().delete_value(cancel_key)
		emit_status("")
		frappe.publish_realtime(
			event="generation_cancelled",
			message={"session": session},
			room="website",
		)
		return
	except frappe.exceptions.ValidationError as e:
		# Update placeholder message with error
		if agent_msg and frappe.db.exists("Chat Message", agent_msg.name):
			agent_msg.content = "⚠️ " + str(e)
			agent_msg.save(ignore_permissions=True)
			frappe.db.commit()
			
			release_lock()
			emit_status("")
			error_payload = {
				"session": session,
				"name": agent_msg.name,
				"sender_type": "Agent",
				"content": "⚠️ " + str(e),
				"creation": str(agent_msg.creation),
			}
			if agent_msg_name:
				error_payload["old_message_id"] = agent_msg_name
			frappe.publish_realtime(
				event="new_message",
				message=error_payload,
				room="website",
			)
		else:
			# Fallback if placeholder doesn't exist
			failed_msg = frappe.get_doc(
				{
					"doctype": "Chat Message",
					"chat_session": session,
					"sender_type": "Agent",
					"message_type": "Agent",
					"content": str(e),
				}
			).insert(ignore_permissions=False)
			frappe.db.commit()
			release_lock()
			emit_status("")
			error_payload = {
				"session": session,
				"name": failed_msg.name,
				"sender_type": "Agent",
				"content": "⚠️ " + str(e),
				"creation": str(failed_msg.creation),
			}
			if agent_msg_name:
				error_payload["old_message_id"] = agent_msg_name
			frappe.publish_realtime(
				event="new_message",
				message=error_payload,
				room="website",
			)
		return
	except Exception as e:
		# Catch-all: ensure lock is always released and frontend is always
		# unfrozen, regardless of what kind of exception occurs.
		job_elapsed = time.time() - job_start
		debug_log(
			"Agent background job failed",
			f"Session: {session}, Elapsed: {job_elapsed:.1f}s, Error: {e}",
			session=session,
			level="WARNING",
		)
		frappe.log_error(
			title=f"Agent background job failed for session {session}",
			message=f"{e}\n{traceback.format_exc()}",
		)

		# Best-effort update of the placeholder message with error text
		msg_name = agent_msg.name if agent_msg else None
		if msg_name and frappe.db.exists("Chat Message", msg_name):
			try:
				frappe.db.set_value(
					"Chat Message", msg_name, "content",
					"⚠️ " + str(e)
				)
				frappe.db.commit()
				frappe.publish_realtime(
					event="new_message",
					message={
						"session": session,
						"name": msg_name,
						"sender_type": "Agent",
						"content": "⚠️ " + str(e),
						"creation": str(frappe.utils.now_datetime()),
					},
					room="website",
				)
				# Emit a final chunk so streaming frontend state clears
				frappe.publish_realtime(
					event="message_chunk",
					message={
						"session": session,
						"message_id": msg_name,
						"chunk": "",
						"is_final": True,
					},
					room="website",
				)
			except Exception:
				pass  # Last-resort: logging already happened above

		release_lock()
		frappe.cache().delete_value(cancel_key)
		emit_status("")
		return

	job_elapsed = time.time() - job_start
	debug_log(
		"Agent background job completed",
		f"Session: {session}, Elapsed: {job_elapsed:.1f}s, Input tokens: {input_tokens}, Output tokens: {output_tokens}",
		session=session,
	)

	# Release lock and clear the status indicator immediately — BEFORE any
	# follow-up DB reads/realtime publishes — so the "Calling AI…" text
	# disappears and the user can send a new message. This MUST come before
	# token updates: if a token update throws, the lock must still be freed.
	release_lock()
	frappe.cache().delete_value(f"ph_agent:files:{session}")
	emit_status("")

	# Update token counts on the session (non-essential — failures must not
	# re-acquire the lock or block the user)
	try:
		_atomic_update_chat_session_tokens(session, input_tokens, output_tokens, cache_hit_tokens)
		_credit_user_token_usage(session, input_tokens, output_tokens, cache_hit_tokens)
	except Exception:
		debug_log(
			"Token update failed after lock release",
			f"Session: {session}",
			session=session,
			level="WARNING",
		)

	# Get updated token counts for realtime update
	session_doc = frappe.get_doc("Chat Session", session)
	provider_doc = frappe.get_doc("LLM Provider", session_doc.llm_provider)
	
	# Get context length from provider, default to 128000 if not set
	context_length = provider_doc.context_length or 128000
	
	# Calculate current percentage
	current_tokens = frappe.db.get_value("Chat Session", session, "estimated_conversation_tokens")
	token_percentage = (current_tokens / context_length) * 100 if context_length > 0 else 0
	
	# Publish token update event
	frappe.publish_realtime(
		event="token_update",
		message={
			"session": session,
			"current_tokens": current_tokens,
			"context_length": context_length,
			"percentage": round(token_percentage, 1),
		},
		room="website",
	)
	
	# Publish the final message to the frontend (streaming path
	# already published new_message above; non-streaming paths
	# rely on this one).
	if not _new_message_sent:
		frappe.publish_realtime(
			event="new_message",
			message={
				"session": session,
				"name": agent_msg.name,
				"sender_type": "Agent",
				"content": agent_msg.content,
				"creation": str(agent_msg.creation),
			},
			room="website",
		)
	session_doc = frappe.get_doc("Chat Session", session)
	if session_doc.enable_suggestions:
		frappe.enqueue(
			"ph_agent.api.agent_jobs._generate_suggestions_background",
			session=session,
			agent_message_id=agent_msg.name,
			enqueued_by=enqueued_by,
			queue="short",
			timeout=120,
		)
	
	# --- Non-essential post-processing (runs after response is delivered) ---
	
	# Send warning if over 75% and warning hasn't been sent yet
	if token_percentage > 75 and not frappe.db.get_value("Chat Session", session, "token_warning_sent"):
		# Publish warning event
		frappe.publish_realtime(
			event="token_warning",
			message={
				"session": session,
				"current_tokens": current_tokens,
				"context_length": context_length,
				"percentage": round(token_percentage, 1),
				"message": f"Conversation is using {round(token_percentage, 1)}% of context window ({current_tokens:,}/{context_length:,} tokens). Consider summarizing the conversation."
			},
			room="website",
		)
		
		# Mark warning as sent
		frappe.db.set_value("Chat Session", session, "token_warning_sent", 1)
		frappe.db.commit()

	# Post-response auto-compaction check
	# If a single large response pushed us past the threshold, compact now.
	# Only run if no auto-summary ran in the pre-call phase (avoid duplicate).
	auto_summary_threshold = provider_doc.auto_summary_threshold or 85
	if not _auto_summary_performed and token_percentage > auto_summary_threshold and not _is_recently_summarized(session):
		# Enqueue asynchronously — purely preparatory for the next user turn
		frappe.enqueue(
			"ph_agent.api.agent_jobs._perform_auto_summary",
			session=session,
			enqueued_by=enqueued_by,
			emit_status=None,
			is_async=True,
			queue="short",
			timeout=120,
		)

	# Auto-generate a title after the first exchange (title is still default "New Chat")
	current_title = frappe.db.get_value("Chat Session", session, "title")
	if current_title == "New Chat":
		msg_count = frappe.db.count("Chat Message", {"chat_session": session})
		if msg_count == 2:  # exactly 1 user msg + 1 agent msg
			# Strip reasoning HTML before title generation to avoid polluting the title
			import re
			agent_reply = re.sub(
				r'<details class="ph-reasoning-block">.*?</details>\s*',
				"",
				agent_msg.content,
				flags=re.DOTALL,
			)
			new_title = generate_session_title(session, agent_content, agent_reply)
			if new_title:
				frappe.db.set_value("Chat Session", session, "title", new_title)
				frappe.db.commit()
				frappe.publish_realtime(
					event="session_renamed",
					message={"session": session, "title": new_title},
				room="website",
			)


def _generate_suggestions_background(session, agent_message_id, enqueued_by):
	"""
	Background job: generate follow-up question suggestions for the last agent message
	and publish them via realtime to the user.
	"""
	try:
		# Fetch conversation history up to and including the agent message
		prior_messages = frappe.get_all(
			"Chat Message",
			filters={"chat_session": session},
			fields=["sender_type", "content"],
			order_by="creation asc",
		)
		history = [
			{"role": "user" if m.sender_type == "User" else "assistant", "content": m.content or ""}
			for m in prior_messages
		]

		suggestions = generate_followup_suggestions(session, history)
		if not suggestions:
			return

		frappe.publish_realtime(
			event="suggestions_ready",
			message={
				"session": session,
				"message_id": agent_message_id,
				"suggestions": suggestions,
			},
			room="website",
		)
	except Exception:
		frappe.log_error(
			title=f"Suggestion background job failed for session {session}",
			message=traceback.format_exc(),
			reference_doctype="Chat Session",
			reference_name=session,
		)


def _handle_tool_approval(session, agent_msg, approval_data, enqueued_by):
	"""
	Handle a tool approval request from the agent.
	Creates a Tool Approval Request document and notifies the user.
	
	Args:
		session: Chat Session name
		agent_msg: The placeholder Chat Message document
		approval_data: Dict with approval_needed, tool_calls, conversation_state
		enqueued_by: User who enqueued the original job
	"""
	tool_calls = approval_data.get("tool_calls", [])
	conversation_state = approval_data.get("conversation_state", {})
	
	if not tool_calls:
		return
	
	# Use the first tool call for the approval request name/description
	primary_tool = tool_calls[0]
	
	# Find the tool to get its description
	tool_description = ""
	from ph_agent.agent.tools.tool_manager import ToolManager
	tools = ToolManager.get_tools()
	for tool_obj in tools:
		if tool_obj.name == primary_tool["name"]:
			tool_description = tool_obj.description or ""
			break
	
	# Update the placeholder message to show "Waiting for approval"
	agent_msg.content = "🔐 Waiting for approval..."
	agent_msg.message_type = "Agent"
	agent_msg.save(ignore_permissions=True)
	frappe.db.commit()
	
	# Publish updated message
	frappe.publish_realtime(
		event="new_message",
		message={
			"session": session,
			"name": agent_msg.name,
			"sender_type": "Agent",
			"content": "🔐 Waiting for approval...",
			"creation": str(agent_msg.creation),
		},
		room="website",
	)
	
	# Create Tool Approval Request document
	approval_doc = frappe.get_doc(
		{
			"doctype": "Tool Approval Request",
			"tool_name": primary_tool["name"],
			"tool_description": tool_description,
			"tool_arguments": json.dumps(
				{
					tc["name"]: tc.get("arguments", "{}")
					for tc in tool_calls
				},
				indent=2,
			),
			"chat_session": session,
			"chat_message": agent_msg.name,
			"status": "Pending",
			"conversation_state": json.dumps(conversation_state, indent=2),
			"agent_message_saved": 1,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	
	# Publish approval_needed event for the UI
	frappe.publish_realtime(
		event="approval_needed",
		message={
			"session": session,
			"approval_name": approval_doc.name,
			"tool_name": primary_tool["name"],
			"tool_description": tool_description,
			"tool_arguments": json.dumps(
				{
					tc["name"]: tc.get("arguments", "{}")
					for tc in tool_calls
				},
				indent=2,
			),
		},
		room="website",
	)

def _execute_approved_tool(approval_name):
	"""
	Background job: execute an approved tool and resume the conversation.
	Called after an administrator approves a Tool Approval Request.
	
	Args:
		approval_name: Name of the Tool Approval Request document
	"""
	approval_doc = frappe.get_doc("Tool Approval Request", approval_name)
	
	if approval_doc.status != "Approved":
		return
	
	session = approval_doc.chat_session
	conversation_state = json.loads(approval_doc.conversation_state or "{}")
	session_doc = frappe.get_doc("Chat Session", session)
	
	try:
		notify_user = approval_doc.approver or frappe.session.user
		reply, input_tokens, output_tokens, cache_hit_tokens, reasoning_content = run_after_approval(
			session_name=session,
			conversation_state=conversation_state,
			approved=True,
			user=notify_user,
		)
		
		# Build content with reasoning block if reasoning exists
		processed_content = _fix_agent_response_text(reply)
		if reasoning_content:
			reasoning_html = (
				f'<details class="ph-reasoning-block">\n'
				f'    <summary>\U0001f913 Thinking process</summary>\n'
				f'{reasoning_content}\n'
				f'</details>\n\n'
			)
			agent_content = reasoning_html + processed_content
		else:
			agent_content = processed_content

		# Store the agent's response as a Chat Message
		agent_msg = frappe.get_doc(
			{
				"doctype": "Chat Message",
				"chat_session": session,
				"sender_type": "Agent",
				"message_type": "Agent",
				"content": agent_content,
				"reasoning_content": reasoning_content or None,
				"input_tokens": input_tokens,
				"output_tokens": output_tokens,
				"cache_hit_tokens": cache_hit_tokens,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		
		# Update the placeholder message to show it was replaced
		placeholder_msg_name = approval_doc.chat_message
		if placeholder_msg_name and frappe.db.exists("Chat Message", placeholder_msg_name):
			placeholder_msg = frappe.get_doc("Chat Message", placeholder_msg_name)
			placeholder_msg.content = "✅ Tool approved and executed. See below for the response."
			placeholder_msg.save(ignore_permissions=True)
			frappe.db.commit()
			
			# Publish update to placeholder
			frappe.publish_realtime(
				event="new_message",
				message={
					"session": session,
					"name": placeholder_msg_name,
					"sender_type": "Agent",
					"content": "✅ Tool approved and executed. See below for the response.",
					"creation": str(placeholder_msg.creation),
				},
				room="website",
			)
		
		# Publish the new agent message
		frappe.publish_realtime(
			event="new_message",
			message={
				"session": session,
				"name": agent_msg.name,
				"sender_type": "Agent",
				"content": reply,
				"creation": str(agent_msg.creation),
			},
			room="website",
		)
		
		# Publish approval_resolved event
		frappe.publish_realtime(
			event="approval_resolved",
			message={
				"session": session,
				"approval_name": approval_name,
				"status": "Approved",
				"tool_name": approval_doc.tool_name,
			},
			room="website",
		)
		
		# Update token counts on session
		_atomic_update_chat_session_tokens(session, input_tokens, output_tokens, cache_hit_tokens)

		# Credit tokens to user-level aggregate
		_credit_user_token_usage(session, input_tokens, output_tokens, cache_hit_tokens)

		# Post-response auto-compaction check for approved tool execution
		session_doc = frappe.get_doc("Chat Session", session)
		provider_doc = frappe.get_doc("LLM Provider", session_doc.llm_provider)
		context_length = provider_doc.context_length or 128000
		auto_summary_threshold = provider_doc.auto_summary_threshold or 85
		current_tokens = session_doc.estimated_conversation_tokens or 0
		token_percentage = (current_tokens / context_length) * 100 if context_length > 0 else 0
		if token_percentage > auto_summary_threshold and not _is_recently_summarized(session):
			frappe.enqueue(
				"ph_agent.api.agent_jobs._perform_auto_summary",
				session=session,
				enqueued_by=notify_user,
				emit_status=None,
				is_async=True,
				queue="short",
				timeout=120,
			)
		
		# Generate follow-up suggestions if enabled
		if session_doc.enable_suggestions:
			frappe.enqueue(
				"ph_agent.api.agent_jobs._generate_suggestions_background",
				session=session,
				agent_message_id=agent_msg.name,
				enqueued_by=notify_user,
				queue="short",
				timeout=120,
			)
			
	except Exception as e:
		frappe.log_error(
			title=f"Approved tool execution failed for {approval_name}",
			message=f"{e}\n{traceback.format_exc()}",
			reference_doctype="Tool Approval Request",
			reference_name=approval_name,
		)
		# Save a user-visible error message so the user sees a graceful
		# failure instead of a silent hang.
		try:
			error_msg = frappe.get_doc(
				{
					"doctype": "Chat Message",
					"chat_session": session,
					"sender_type": "Agent",
					"message_type": "Agent",
					"content": (
						"⚠️ **Tool execution failed.**\n\n"
						f"The approved tool could not be executed. This may happen when the "
						f"tool is not available for the current persona's configuration.\n\n"
						f"**Error details:** {str(e)[:500]}"
					),
				}
			).insert(ignore_permissions=True)
			frappe.db.commit()

			# Publish the error message
			frappe.publish_realtime(
				event="new_message",
				message={
					"session": session,
					"name": error_msg.name,
					"sender_type": "Agent",
					"content": error_msg.content,
					"creation": str(error_msg.creation),
				},
				room="website",
			)
		except Exception:
			pass  # Best-effort; the log_error above already captured the root cause

		# Publish approval_resolved with error status
		try:
			frappe.publish_realtime(
				event="approval_resolved",
				message={
					"session": session,
					"approval_name": approval_name,
					"status": "Error",
					"tool_name": approval_doc.tool_name,
				},
				room="website",
			)
		except Exception:
			pass


def cancel_approvals_for_session(doc, method):
	"""
	Cascade delete all Tool Approval Requests linked to a Chat Session
	when the session is deleted.
	
	This runs in on_trash, which is called BEFORE Frappe's link validation,
	so we delete the dependent records first to allow the session delete to proceed.
	
	Uses raw DB delete to bypass link validation (the Tool Approval Request
	references the session being deleted, so normal frappe.delete_doc would fail).
	
	Called via doc_events hook: Chat Session > on_trash
	"""
	# Delete User Memory records linked to this session
	frappe.db.delete("User Memory", {"source_session": doc.name})
	
	linked_requests = frappe.get_all(
		"Tool Approval Request",
		filters={"chat_session": doc.name},
		pluck="name",
	)
	for req_name in linked_requests:
		frappe.db.delete("Tool Approval Request", {"name": req_name})
	frappe.db.commit()


def cancel_approvals_for_message(doc, method):
	"""
	Cascade delete all Tool Approval Requests linked to a Chat Message
	when the message is deleted.
	Also delete all File documents attached to the message.
	
	This runs in on_trash, which is called BEFORE Frappe's link validation,
	so we delete the dependent records first to allow the message delete to proceed.
	
	Uses raw DB delete to bypass link validation (the Tool Approval Request
	references the message being deleted, so normal frappe.delete_doc would fail).
	
	Called via doc_events hook: Chat Message > on_trash
	"""
	# Delete User Memory records linked to this message
	frappe.db.delete("User Memory", {"source_message": doc.name})
	
	# If this message is referenced as the session's last_summary_message,
	# clear that reference to avoid LinkExistsError
	if doc.chat_session:
		session_last_summary = frappe.db.get_value(
			"Chat Session", doc.chat_session, "last_summary_message"
		)
		if session_last_summary == doc.name:
			frappe.db.set_value(
				"Chat Session", doc.chat_session, "last_summary_message", None
			)
	
	# Delete Tool Approval Requests
	linked_requests = frappe.get_all(
		"Tool Approval Request",
		filters={"chat_message": doc.name},
		pluck="name",
	)
	for req_name in linked_requests:
		frappe.db.delete("Tool Approval Request", {"name": req_name})
	
	# Delete attached File documents
	file_names = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Chat Message", "attached_to_name": doc.name},
		pluck="name",
	)
	for file_name in file_names:
		try:
			# Check if file still exists (might have been deleted already)
			if frappe.db.exists("File", file_name):
				# Use force=True to bypass link validation (File references Chat Message being deleted)
				frappe.delete_doc("File", file_name, ignore_permissions=True, force=True)
			else:
				# File was already deleted, log for debugging
				frappe.log_error(
					f"File {file_name} attached to message {doc.name} was already deleted",
					"ph_agent_file_deletion"
				)
		except Exception as e:
			# Log error but continue with other files
			frappe.log_error(
				f"Failed to delete file {file_name} attached to message {doc.name}: {str(e)}",
				"ph_agent_file_deletion"
			)
	
	frappe.db.commit()


def cascade_delete_persona(doc, method):
	"""
	Cascade delete all dependent records when a Persona is deleted.

	Deletes:
	- All User Memory records belonging to this persona
	- All Chat Sessions belonging to this persona (which cascade to messages, files, approvals)

	This runs in on_trash, which is called BEFORE Frappe's link validation,
	so we delete the dependent records first to allow the persona delete to proceed.

	Called via doc_events hook: Persona > on_trash
	"""
	# Delete User Memory records for this persona (raw DB delete to bypass link validation)
	frappe.db.delete("User Memory", {"persona": doc.name})

	# Delete Chat Sessions for this persona — use frappe.delete_doc so cascade hooks fire
	sessions = frappe.get_all(
		"Chat Session",
		filters={"persona": doc.name},
		pluck="name",
	)
	for session_name in sessions:
		try:
			frappe.delete_doc("Chat Session", session_name, ignore_permissions=True, force=True)
		except Exception as e:
			frappe.log_error(
				f"Failed to delete session {session_name} during persona cascade: {str(e)}",
				"ph_agent_persona_cascade"
			)

	frappe.db.commit()
