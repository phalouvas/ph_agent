import frappe
from ph_agent.agent.deepseek_agent import get_agent_response


@frappe.whitelist()
def update_session_provider(session, provider_name):
	"""Change the LLM Provider on an existing Chat Session."""
	frappe.has_permission("Chat Session", doc=session, throw=True)
	if not frappe.db.exists("LLM Provider", {"name": provider_name, "is_enabled": 1}):
		frappe.throw(frappe._("LLM Provider {0} not found or is disabled.").format(provider_name))
	frappe.db.set_value("Chat Session", session, "llm_provider", provider_name)
	frappe.db.commit()
	return {"status": "ok"}


@frappe.whitelist()
def create_session(provider_name=None):
	"""Create a new Chat Session. Uses default LLM Provider if provider_name not specified."""
	if not provider_name:
		default = frappe.get_list(
			"LLM Provider",
			filters={"is_default": 1, "is_enabled": 1},
			pluck="name",
			limit=1,
		)
		if not default:
			frappe.throw(frappe._("No default LLM Provider configured. Please set up a provider first."))
		provider_name = default[0]
	else:
		if not frappe.db.exists("LLM Provider", {"name": provider_name, "is_enabled": 1}):
			frappe.throw(frappe._("LLM Provider {0} not found or is disabled.").format(provider_name))

	session = frappe.get_doc(
		{
			"doctype": "Chat Session",
			"title": "New Chat",
			"user": frappe.session.user,
			"llm_provider": provider_name,
			"status": "Open",
		}
	)
	session.insert(ignore_permissions=False)
	frappe.db.commit()
	return {"session": session.name, "title": session.title, "llm_provider": session.llm_provider}


@frappe.whitelist()
def send_message(session, content):
	"""Store a user message, call the LLM agent, and store the response."""
	frappe.has_permission("Chat Session", doc=session, throw=True)

	# Store user message
	frappe.get_doc(
		{
			"doctype": "Chat Message",
			"chat_session": session,
			"sender_type": "User",
			"content": content,
		}
	).insert(ignore_permissions=False)
	frappe.db.commit()

	# Call agent
	try:
		reply, input_tokens, output_tokens = get_agent_response(session, content)
	except frappe.exceptions.ValidationError as e:
		# Return error as a failed agent message so the UI can show the failure indicator
		failed_msg = frappe.get_doc(
			{
				"doctype": "Chat Message",
				"chat_session": session,
				"sender_type": "Agent",
				"content": str(e),
			}
		).insert(ignore_permissions=False)
		frappe.db.commit()
		return {"status": "error", "error": str(e), "agent_message": failed_msg.name}

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

	# Emit real-time event to the current user
	frappe.publish_realtime(
		event="new_message",
		message={
			"session": session,
			"name": agent_msg.name,
			"sender_type": "Agent",
			"content": reply,
			"creation": str(agent_msg.creation),
		},
		user=frappe.session.user,
		after_commit=True,
	)

	return {"status": "ok", "agent_message": agent_msg.name, "reply": reply}


@frappe.whitelist()
def get_history(session):
	"""Return all messages for a Chat Session, ordered by creation time."""
	frappe.has_permission("Chat Session", doc=session, throw=True)
	messages = frappe.get_all(
		"Chat Message",
		filters={"chat_session": session},
		fields=["name", "sender_type", "content", "creation"],
		order_by="creation asc",
	)
	return messages


@frappe.whitelist()
def delete_session(session):
	"""Delete a Chat Session and all its messages."""
	frappe.has_permission("Chat Session", ptype="delete", doc=session, throw=True)
	frappe.db.delete("Chat Message", {"chat_session": session})
	frappe.delete_doc("Chat Session", session, ignore_permissions=False)
	frappe.db.commit()
	return {"status": "ok"}
