import asyncio

import frappe
from ph_agent.agent.deepseek_agent import generate_followup_suggestions, generate_session_title, get_agent_response, get_agent_response_stream
from ph_agent.utils.pdf import extract_pdf_text


def _call_agent_background(session, user_msg_name, content, file_names, enqueued_by, agent_msg_name=None):
	"""
	Background job: optionally extract PDFs, call the LLM agent, store the reply,
	and push realtime events back to the user who enqueued the job.
	"""

	def emit_status(msg):
		frappe.publish_realtime(
			event="agent_status",
			message={"session": session, "status": msg},
			user=enqueued_by,
		)

	lock_key = f"ph_agent:lock:{session}"
	cancel_key = f"ph_agent:cancel:{session}"

	def release_lock():
		frappe.cache().delete_value(lock_key)

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
			user=enqueued_by,
		)
		return

	# Build enriched content: append extracted PDF text from attachments
	agent_content = content
	if file_names:
		pdf_texts = []
		emit_status(frappe._("Extracting PDF text…"))
		for file_name in file_names:
			if is_cancelled():
				release_lock()
				frappe.cache().delete_value(cancel_key)
				emit_status("")
				frappe.publish_realtime(
					event="generation_cancelled",
					message={"session": session},
					user=enqueued_by,
				)
				return
			text = extract_pdf_text(file_name)
			if text:
				pdf_texts.append(f"[PDF: {frappe.db.get_value('File', file_name, 'file_name')}]\n{text}")
		if pdf_texts:
			agent_content = content + "\n\n" + "\n\n".join(pdf_texts)

	emit_status(frappe._("Calling AI…"))

	# Check if streaming should be used
	session_doc = frappe.get_doc("Chat Session", session)
	provider_doc = frappe.get_doc("LLM Provider", session_doc.llm_provider)
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
		user=enqueued_by,
	)
	# Check if we need to auto-summarize before making the API call
	session_doc = frappe.get_doc("Chat Session", session)
	provider_doc = frappe.get_doc("LLM Provider", session_doc.llm_provider)
	
	# Get context length and auto-summary threshold
	context_length = provider_doc.context_length or 128000
	auto_summary_threshold = provider_doc.auto_summary_threshold or 85
	
	# Calculate current percentage
	current_tokens = session_doc.estimated_conversation_tokens or 0
	token_percentage = (current_tokens / context_length) * 100 if context_length > 0 else 0
	
	# Auto-summarize if threshold exceeded
	if token_percentage > auto_summary_threshold:
		emit_status(frappe._("Summarizing conversation..."))
		
		# Get messages since last summary
		last_summary = session_doc.last_summary_message
		if last_summary:
			last_summary_doc = frappe.get_doc("Chat Message", last_summary)
			messages = frappe.get_all(
				"Chat Message",
				filters={
					"chat_session": session,
					"creation": [">", last_summary_doc.creation],
					"message_type": ["!=", "Summary"]
				},
				fields=["name", "sender_type", "content", "creation"],
				order_by="creation asc",
			)
		else:
			# No previous summary, get all non-summary messages
			messages = frappe.get_all(
				"Chat Message",
				filters={
					"chat_session": session,
					"message_type": ["!=", "Summary"]
				},
				fields=["name", "sender_type", "content", "creation"],
				order_by="creation asc",
			)
		
		if messages:
			# Format conversation history
			conversation_history = []
			for msg in messages:
				role = "user" if msg.sender_type == "User" else "assistant"
				conversation_history.append({"role": role, "content": msg.content or ""})
			
			# Generate summary
			from ph_agent.agent.deepseek_agent import generate_conversation_summary
			try:
				summary = generate_conversation_summary(session, conversation_history)
				if summary:
					# Create summary message with *📋 Summary* prefix
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
						}
					)
					frappe.db.commit()
					
					# Publish token update event (tokens reset to 0)
					frappe.publish_realtime(
						event="token_update",
						message={
							"session": session,
							"current_tokens": 0,
							"context_length": context_length,
							"percentage": 0,
						},
						user=enqueued_by,
					)
					
					# Publish realtime event for new summary message
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
						user=enqueued_by,
					)
					
					emit_status(frappe._("Conversation summarized. Continuing..."))
			except Exception as e:
				frappe.log_error(
					title=f"Auto-summarization failed for session {session}",
					message=str(e)
				)
				# Continue without summary if generation fails
	try:
		if use_streaming:
			# Streaming path
			full_content = ""
			input_tokens = 0
			output_tokens = 0
			streaming_successful = False
			
			try:
				for chunk, is_final, chunk_input_tokens, chunk_output_tokens in get_agent_response_stream(session, agent_content, cancel_check=is_cancelled, status_callback=emit_status):
					if is_cancelled():
						raise asyncio.CancelledError()
						
					if is_final:
						# Final chunk with token usage
						input_tokens = chunk_input_tokens
						output_tokens = chunk_output_tokens
						streaming_successful = True
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
							user=enqueued_by,
						)
				
				if streaming_successful:
					# Update the placeholder message with full content and token counts
					agent_msg.content = full_content
					agent_msg.input_tokens = input_tokens
					agent_msg.output_tokens = output_tokens
					agent_msg.message_type = "Agent"
					agent_msg.save(ignore_permissions=True)
					frappe.db.commit()
				else:
					# Streaming didn't complete successfully, fall back
					raise Exception("Streaming did not complete successfully")
				
			except Exception as stream_error:
				# If streaming fails, fall back to non-streaming
				frappe.log_error(
					title=f"Streaming failed for session {session}, falling back to non-streaming",
					message=str(stream_error)
				)
				# Fall back to non-streaming - update the existing placeholder
				use_streaming = False
				reply, input_tokens, output_tokens = get_agent_response(session, agent_content, cancel_check=is_cancelled)
				# Update placeholder message with actual content and token counts
				agent_msg.content = reply
				agent_msg.input_tokens = input_tokens
				agent_msg.output_tokens = output_tokens
				agent_msg.save(ignore_permissions=True)
				frappe.db.commit()
		else:
			# Non-streaming path - update the existing placeholder message
			reply, input_tokens, output_tokens = get_agent_response(session, agent_content, cancel_check=is_cancelled)
			# Update the placeholder message with actual content and token counts
			agent_msg.content = reply
			agent_msg.input_tokens = input_tokens
			agent_msg.output_tokens = output_tokens
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
			user=enqueued_by,
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
				user=enqueued_by,
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
				user=enqueued_by,
			)
		return

	# Update token counts on the session
	frappe.db.set_value(
		"Chat Session",
		session,
		{
			"input_tokens": frappe.db.get_value("Chat Session", session, "input_tokens") + input_tokens,
			"output_tokens": frappe.db.get_value("Chat Session", session, "output_tokens") + output_tokens,
			"estimated_conversation_tokens": frappe.db.get_value("Chat Session", session, "estimated_conversation_tokens") + input_tokens + output_tokens,
		},
	)
	frappe.db.commit()

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
		user=enqueued_by,
	)
	
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
			user=enqueued_by,
		)
		
		# Mark warning as sent
		frappe.db.set_value("Chat Session", session, "token_warning_sent", 1)
		frappe.db.commit()

	# Auto-generate a title after the first exchange (title is still default "New Chat")
	current_title = frappe.db.get_value("Chat Session", session, "title")
	if current_title == "New Chat":
		msg_count = frappe.db.count("Chat Message", {"chat_session": session})
		if msg_count == 2:  # exactly 1 user msg + 1 agent msg
			# Use agent_msg.content which contains either streaming or non-streaming content
			agent_reply = agent_msg.content
			new_title = generate_session_title(session, agent_content, agent_reply)
			if new_title:
				frappe.db.set_value("Chat Session", session, "title", new_title)
				frappe.db.commit()
				frappe.publish_realtime(
					event="session_renamed",
					message={"session": session, "title": new_title},
					user=enqueued_by,
				)

	# Release lock, clear the status indicator and deliver the reply
	release_lock()
	emit_status("")
	
	if use_streaming:
		# For streaming, publish final chunk event
		frappe.publish_realtime(
			event="message_chunk",
			message={
				"session": session,
				"message_id": agent_msg.name,
				"chunk": "",
				"is_final": True
			},
			user=enqueued_by,
		)
	else:
		# For non-streaming, publish the updated message
		# The placeholder was already published, now we need to update it
		# We publish a new_message event with the same ID to trigger an update
		new_msg_payload = {
			"session": session,
			"name": agent_msg.name,
			"sender_type": "Agent",
			"content": reply,
			"creation": str(agent_msg.creation),
		}
		# Don't include old_message_id in final response - only placeholder needs it
		# The final response updates the placeholder message (same ID)
		
		frappe.publish_realtime(
			event="new_message",
			message=new_msg_payload,
			user=enqueued_by,
		)

	# Enqueue follow-up suggestions if enabled for this session
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
			user=enqueued_by,
		)
	except Exception:
		frappe.log_error(
			title=f"Suggestion background job failed for session {session}",
			reference_doctype="Chat Session",
			reference_name=session,
		)
