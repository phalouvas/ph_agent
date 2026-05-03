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
	generate_session_title_and_suggestions,
	get_agent_response,
	get_agent_response_stream,
)
from ph_agent.agent.tools.tool_manager import ToolManager
from ph_agent.api.token_counter import count_tokens, get_model_for_session
from ph_agent.api.token_utils import (
	_atomic_update_chat_session_tokens,
	_atomic_update_user_token_usage,
	_calculate_cost_from_rates,
	_resolve_effective_rates,
)
from ph_agent.utils.debug_logger import debug_log
from ph_agent.utils.file_extractor import extract_file_text

# ---------------------------------------------------------------------------
# Token usage & cost helpers
# ---------------------------------------------------------------------------


def _credit_user_token_usage(
	session_name: str, input_tokens: int, output_tokens: int, cache_hit_tokens: int = 0
) -> None:
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
		rates = _resolve_effective_rates(session_name)
		cost = _calculate_cost_from_rates(input_tokens, output_tokens, cache_hit_tokens, rates)
		_atomic_update_user_token_usage(
			rates["usage_name"], input_tokens, output_tokens, cache_hit_tokens, cost
		)
	except Exception:
		frappe.log_error(
			title="Failed to credit user token usage",
			message=f"Session: {session_name}, Input: {input_tokens}, Output: {output_tokens}, Cache hit: {cache_hit_tokens}",
		)


def _calculate_message_cost(
	session_name: str, input_tokens: int, output_tokens: int, cache_hit_tokens: int = 0
) -> float:
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
		rates = _resolve_effective_rates(session_name)
		return _calculate_cost_from_rates(input_tokens, output_tokens, cache_hit_tokens, rates)
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

	Uses tiktoken for accurate counting when available, falling back to
	character-count heuristics. Unlike the previous implementation, no
	20 % buffer is added — the tiktoken count is accurate, and for
	fallback the buffer just amplifies imprecision.

	Returns the estimated token count for static overhead.
	"""
	session_doc = frappe.get_doc("Chat Session", session_name)
	model = get_model_for_session(session_name)
	system_prompt = session_doc.system_prompt or ""
	overhead = 0

	# System prompt — use tiktoken when available
	if system_prompt:
		overhead += count_tokens(system_prompt, model=model)

	# Tool definitions — serialize schemas and count accurately
	try:
		tools = ToolManager.get_tools(session_name=session_name, persona=session_doc.persona)
		for tool_obj in tools:
			if hasattr(tool_obj, "schema") and tool_obj.schema:
				schema_str = json.dumps(tool_obj.schema, separators=(",", ":"))
				overhead += count_tokens(schema_str, model=model)
			elif hasattr(tool_obj, "description") and tool_obj.description:
				overhead += count_tokens(tool_obj.description, model=model)
	except Exception:
		pass  # Best-effort; overhead is a soft estimate

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
			filters["creation"] = [">=", last_summary_doc.creation]

		remaining = frappe.get_all(
			"Chat Message",
			filters=filters,
			fields=["name", "content"],
			order_by="creation asc, name asc",
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


def _perform_auto_summary(
	session: str, enqueued_by: str | None = None, emit_status: callable | None = None, is_async: bool = False
) -> bool:
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
				"creation": [">=", last_summary_doc.creation],
				"message_type": ["!=", "Summary"],
			},
			fields=["name", "sender_type", "content", "creation"],
			order_by="creation asc, name asc",
		)
	else:
		messages = frappe.get_all(
			"Chat Message",
			filters={
				"chat_session": session,
				"message_type": ["!=", "Summary"],
			},
			fields=["name", "sender_type", "content", "creation"],
			order_by="creation asc, name asc",
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
	_new_message_sent = False

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

			debug_log(
				"Starting streaming path",
				f"Session: {session}, Content length: {len(agent_content)}",
				session=session,
			)

			try:
				for (
					chunk,
					is_final,
					chunk_input_tokens,
					chunk_output_tokens,
					chunk_cache_hit_tokens,
				) in get_agent_response_stream(
					session,
					agent_content,
					cancel_check=is_cancelled,
					status_callback=emit_status,
					skip_session_state=bool(agent_msg_name),
				):
					if is_cancelled():
						raise asyncio.CancelledError()

					if is_final:
						if isinstance(chunk, tuple):
							# (response_text, reasoning_content) — response_text is empty
							# because content was already streamed via chunks.
							# Only extract reasoning and token counts.
							_response_text, reasoning_text = chunk
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
								"is_final": False,
							},
							room="website",
						)

				if streaming_successful:
					# Build content with reasoning block if reasoning exists
					processed_content = _fix_agent_response_text(full_content)
					if full_reasoning:
						reasoning_html = (
							f'<details class="ph-reasoning-block">\n'
							f"    <summary>\U0001f913 Thinking process</summary>\n"
							f"{full_reasoning}\n"
							f"</details>\n\n"
						)
						agent_msg.content = reasoning_html + processed_content
						agent_msg.reasoning_content = full_reasoning
					else:
						agent_msg.content = processed_content
					agent_msg.input_tokens = input_tokens
					agent_msg.output_tokens = output_tokens
					agent_msg.cache_hit_tokens = cache_hit_tokens
					agent_msg.cost = _calculate_message_cost(
						session, input_tokens, output_tokens, cache_hit_tokens
					)
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
					message=f"{stream_error}\n{traceback.format_exc()}",
				)
				# Reload agent_msg to avoid TimestampMismatchError (it was committed earlier)
				agent_msg = frappe.get_doc("Chat Message", agent_msg.name)
				# Fall back to non-streaming - update the existing placeholder
				use_streaming = False
				try:
					reply, input_tokens, output_tokens, cache_hit_tokens, reasoning_content = (
						get_agent_response(
							session,
							agent_content,
							cancel_check=is_cancelled,
							skip_session_state=bool(agent_msg_name),
						)
					)
				except Exception as fallback_error:
					frappe.log_error(
						title=f"Non-streaming fallback also failed for session {session}",
						message=f"{fallback_error}\n{traceback.format_exc()}",
					)
					raise  # Let the outer except Exception handle it

				# Build content with reasoning block if reasoning exists
				processed_content = _fix_agent_response_text(reply)
				if reasoning_content:
					reasoning_html = (
						f'<details class="ph-reasoning-block">\n'
						f"    <summary>\U0001f913 Thinking process</summary>\n"
						f"{reasoning_content}\n"
						f"</details>\n\n"
					)
					agent_msg.content = reasoning_html + processed_content
					agent_msg.reasoning_content = reasoning_content
				else:
					agent_msg.content = processed_content
				agent_msg.input_tokens = input_tokens
				agent_msg.output_tokens = output_tokens
				agent_msg.cache_hit_tokens = cache_hit_tokens
				agent_msg.cost = _calculate_message_cost(
					session, input_tokens, output_tokens, cache_hit_tokens
				)
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
			reply, input_tokens, output_tokens, cache_hit_tokens, reasoning_content = get_agent_response(
				session, agent_content, cancel_check=is_cancelled, skip_session_state=bool(agent_msg_name)
			)

			# Build content with reasoning block if reasoning exists
			processed_content = _fix_agent_response_text(reply)
			if reasoning_content:
				reasoning_html = (
					f'<details class="ph-reasoning-block">\n'
					f"    <summary>\U0001f913 Thinking process</summary>\n"
					f"{reasoning_content}\n"
					f"</details>\n\n"
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
				frappe.db.set_value("Chat Message", msg_name, "content", "⚠️ " + str(e))
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
	emit_status("")
	session_doc = frappe.get_doc("Chat Session", session)

	# --- Title and suggestions (batched on first turn) ---
	current_title = frappe.db.get_value("Chat Session", session, "title")
	msg_count = frappe.db.count("Chat Message", {"chat_session": session})
	is_first_turn = current_title == "New Chat" and msg_count == 2

	if is_first_turn:
		import re

		agent_reply = re.sub(
			r'<details class="ph-reasoning-block">.*?</details>\s*',
			"",
			agent_msg.content,
			flags=re.DOTALL,
		)

		if session_doc.enable_suggestions:
			prior_messages = frappe.get_all(
				"Chat Message",
				filters={"chat_session": session},
				fields=["sender_type", "content"],
				order_by="creation asc, name asc",
			)
			history = [
				{"role": "user" if m.sender_type == "User" else "assistant", "content": m.content or ""}
				for m in prior_messages
			]

			new_title, suggestions = generate_session_title_and_suggestions(
				session, agent_content, agent_reply, history
			)

			if new_title:
				frappe.db.set_value("Chat Session", session, "title", new_title)
				frappe.db.commit()
				frappe.publish_realtime(
					event="session_renamed",
					message={"session": session, "title": new_title},
					room="website",
				)

			if suggestions:
				frappe.publish_realtime(
					event="suggestions_ready",
					message={
						"session": session,
						"message_id": agent_msg.name,
						"suggestions": suggestions,
					},
					room="website",
				)
		else:
			new_title = generate_session_title(session, agent_content, agent_reply)
			if new_title:
				frappe.db.set_value("Chat Session", session, "title", new_title)
				frappe.db.commit()
				frappe.publish_realtime(
					event="session_renamed",
					message={"session": session, "title": new_title},
					room="website",
				)
	elif session_doc.enable_suggestions:
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
				"message": f"Conversation is using {round(token_percentage, 1)}% of context window ({current_tokens:,}/{context_length:,} tokens). Consider summarizing the conversation.",
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
	if (
		not _auto_summary_performed
		and token_percentage > auto_summary_threshold
		and not _is_recently_summarized(session)
	):
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
			order_by="creation asc, name asc",
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


def cascade_delete_persona(doc, method):
	"""
	Cascade delete all dependent records when a Persona is deleted.

	Deletes:
	- All User Memory records belonging to this persona
	- All Chat Sessions belonging to this persona (which cascade to messages and files)

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
				f"Failed to delete session {session_name} during persona cascade: {e!s}",
				"ph_agent_persona_cascade",
			)

	frappe.db.commit()
