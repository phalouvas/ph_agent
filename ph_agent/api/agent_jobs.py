import asyncio

import frappe
from ph_agent.agent.deepseek_agent import generate_followup_suggestions, generate_session_title, get_agent_response
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

	try:
		reply, input_tokens, output_tokens = get_agent_response(session, agent_content, cancel_check=is_cancelled)
	except asyncio.CancelledError:
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
		failed_msg = frappe.get_doc(
			{
				"doctype": "Chat Message",
				"chat_session": session,
				"sender_type": "Agent",
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

	# If regenerating, delete the old agent message before storing the new one
	if agent_msg_name and frappe.db.exists("Chat Message", agent_msg_name):
		frappe.delete_doc("Chat Message", agent_msg_name, ignore_permissions=True)

	# Store agent response
	agent_msg = frappe.get_doc(
		{
			"doctype": "Chat Message",
			"chat_session": session,
			"sender_type": "Agent",
			"content": reply,
		}
	).insert(ignore_permissions=False)

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
			new_title = generate_session_title(session, agent_content, reply)
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
	frappe.log_error(
		title="[DEBUG] suggestions check",
		message=f"session={session} enable_suggestions={session_doc.enable_suggestions} agent_msg={agent_msg.name}",
	)
	if session_doc.enable_suggestions:
		frappe.log_error(
			title="[DEBUG] suggestions enqueuing",
			message=f"enqueuing _generate_suggestions_background for msg {agent_msg.name}",
		)
		frappe.enqueue(
			"ph_agent.api.agent_jobs._generate_suggestions_background",
			session=session,
			agent_message_id=agent_msg.name,
			enqueued_by=enqueued_by,
			queue="short",
			timeout=30,
		)
	else:
		frappe.log_error(
			title="[DEBUG] suggestions skipped",
			message=f"enable_suggestions is disabled for session {session}",
		)


def _generate_suggestions_background(session, agent_message_id, enqueued_by):
	"""
	Background job: generate follow-up question suggestions for the last agent message
	and publish them via realtime to the user.
	"""
	frappe.log_error(
		title="[DEBUG] suggestions background started",
		message=f"session={session} msg={agent_message_id} user={enqueued_by}",
	)
	try:
		# Fetch conversation history up to and including the agent message
		prior_messages = frappe.get_all(
			"Chat Message",
			filters={"chat_session": session},
			fields=["sender_type", "content"],
			order_by="creation asc",
		)
		frappe.log_error(
			title="[DEBUG] suggestions history",
			message=f"history length: {len(prior_messages)}",
		)
		history = [
			{"role": "user" if m.sender_type == "User" else "assistant", "content": m.content or ""}
			for m in prior_messages
		]

		suggestions = generate_followup_suggestions(session, history)
		frappe.log_error(
			title="[DEBUG] suggestions generated",
			message=f"suggestions={suggestions}",
		)
		if not suggestions:
			frappe.log_error(
				title="[DEBUG] suggestions empty",
				message="LLM returned empty suggestions — not publishing",
			)
			return

		frappe.log_error(
			title="[DEBUG] suggestions publishing",
			message=f"publishing suggestions_ready to user={enqueued_by}",
		)
		frappe.publish_realtime(
			event="suggestions_ready",
			message={
				"session": session,
				"message_id": agent_message_id,
				"suggestions": suggestions,
			},
			user=enqueued_by,
		)
		frappe.log_error(
			title="[DEBUG] suggestions published",
			message="suggestions_ready event published successfully",
		)
	except Exception:
		frappe.log_error(
			title=f"Suggestion background job failed for session {session}",
			reference_doctype="Chat Session",
			reference_name=session,
		)
