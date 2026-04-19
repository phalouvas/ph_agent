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

	# Create placeholder message for streaming or regular message for non-streaming
	if use_streaming:
		# Create placeholder message with loading indicator
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
		
		# Publish placeholder message event
		# If regenerating, delete the old agent message before creating the new one
		if agent_msg_name and frappe.db.exists("Chat Message", agent_msg_name):
			frappe.delete_doc("Chat Message", agent_msg_name, ignore_permissions=True)
			frappe.db.commit()
		
		placeholder_payload = {
			"session": session,
			"name": agent_msg.name,
			"sender_type": "Agent",
			"content": "",
			"creation": str(agent_msg.creation),
			"is_streaming_placeholder": True,
		}
		if agent_msg_name:
			placeholder_payload["old_message_id"] = agent_msg_name
		frappe.publish_realtime(
			event="new_message",
			message=placeholder_payload,
			user=enqueued_by,
		)
	else:
		# If regenerating, delete the old agent message before storing the new one
		if agent_msg_name and frappe.db.exists("Chat Message", agent_msg_name):
			frappe.delete_doc("Chat Message", agent_msg_name, ignore_permissions=True)
			frappe.db.commit()

	try:
		if use_streaming:
			# Streaming path
			full_content = ""
			input_tokens = 0
			output_tokens = 0
			streaming_successful = False
			
			try:
				for chunk, is_final, chunk_input_tokens, chunk_output_tokens in get_agent_response_stream(session, agent_content, cancel_check=is_cancelled):
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
				# Delete placeholder message
				if agent_msg and frappe.db.exists("Chat Message", agent_msg.name):
					frappe.delete_doc("Chat Message", agent_msg.name, ignore_permissions=True)
				# Fall back to non-streaming
				use_streaming = False
				reply, input_tokens, output_tokens = get_agent_response(session, agent_content, cancel_check=is_cancelled)
				# Create regular message with token counts
				agent_msg = frappe.get_doc(
					{
						"doctype": "Chat Message",
						"chat_session": session,
						"sender_type": "Agent",
						"message_type": "Agent",
						"content": reply,
						"input_tokens": input_tokens,
						"output_tokens": output_tokens,
					}
				).insert(ignore_permissions=False)
		else:
			# Non-streaming path
			reply, input_tokens, output_tokens = get_agent_response(session, agent_content, cancel_check=is_cancelled)
			# Store agent response with token counts
			agent_msg = frappe.get_doc(
				{
					"doctype": "Chat Message",
					"chat_session": session,
					"sender_type": "Agent",
					"message_type": "Agent",
					"content": reply,
					"input_tokens": input_tokens,
					"output_tokens": output_tokens,
				}
			).insert(ignore_permissions=False)
			
	except asyncio.CancelledError:
		# Clean up placeholder message if streaming was used
		if use_streaming and agent_msg and frappe.db.exists("Chat Message", agent_msg.name):
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
		# Clean up placeholder message if streaming was used
		if use_streaming and agent_msg and frappe.db.exists("Chat Message", agent_msg.name):
			frappe.delete_doc("Chat Message", agent_msg.name, ignore_permissions=True)
			frappe.db.commit()
			
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
		},
	)
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
		# For non-streaming, publish the complete message
		new_msg_payload = {
			"session": session,
			"name": agent_msg.name,
			"sender_type": "Agent",
			"content": reply,
			"creation": str(agent_msg.creation),
		}
		if agent_msg_name:
			new_msg_payload["old_message_id"] = agent_msg_name
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
			timeout=30,
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
