import asyncio

import frappe
from ph_agent.agent.deepseek_agent import generate_session_title, get_agent_response
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
