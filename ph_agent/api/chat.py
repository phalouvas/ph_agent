import frappe


def _emit_status(session, message):
	"""Push a transient status string to the session owner's browser."""
	frappe.publish_realtime(
		event="agent_status",
		message={"session": session, "status": message},
		user=frappe.session.user,
	)


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
def send_message(session, content, file_names=None):
	"""Store a user message and enqueue the LLM agent response as a background job."""
	frappe.has_permission("Chat Session", doc=session, throw=True)

	# Store user message
	user_msg = frappe.get_doc(
		{
			"doctype": "Chat Message",
			"chat_session": session,
			"sender_type": "User",
			"content": content,
		}
	).insert(ignore_permissions=False)

	# Link any uploaded files to this message
	file_names_list = frappe.parse_json(file_names) if isinstance(file_names, str) else (file_names or [])
	for file_name in file_names_list:
		frappe.db.set_value(
			"File",
			file_name,
			{"attached_to_doctype": "Chat Message", "attached_to_name": user_msg.name},
		)

	frappe.db.commit()

	# Show initial status immediately; the background job will update it further
	_emit_status(session, frappe._("Calling AI…"))

	# Enqueue the agent call in the background
	job = frappe.enqueue(
		"ph_agent.api.agent_jobs._call_agent_background",
		session=session,
		user_msg_name=user_msg.name,
		content=content,
		file_names=file_names_list,
		enqueued_by=frappe.session.user,
		queue="long",
		timeout=600,
	)

	# Persist the job ID so cancel_generation can stop it
	frappe.cache().set_value(f"ph_agent:job:{session}", job.id, expires_in_sec=600)

	return {"status": "queued", "user_message": user_msg.name}


@frappe.whitelist()
def cancel_generation(session):
	"""Cancel an ongoing LLM generation for the given session."""
	frappe.has_permission("Chat Session", doc=session, throw=True)

	# Attempt to stop the running RQ job
	job_id = frappe.cache().get_value(f"ph_agent:job:{session}")
	if job_id:
		try:
			from frappe.utils.background_jobs import get_redis_conn
			from rq.command import send_stop_job_command

			jid = job_id.decode() if isinstance(job_id, bytes) else job_id
			send_stop_job_command(connection=get_redis_conn(), job_id=jid)
		except Exception:
			pass  # Best-effort; the cooperative flag below acts as fallback
		frappe.cache().delete_value(f"ph_agent:job:{session}")

	# Set cooperative cancellation flag for in-progress PDF extraction checks
	frappe.cache().set_value(f"ph_agent:cancel:{session}", True, expires_in_sec=60)

	# Clear the status bar and notify the frontend
	_emit_status(session, "")
	frappe.publish_realtime(
		event="generation_cancelled",
		message={"session": session},
		user=frappe.session.user,
	)

	return {"status": "cancelled"}


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
	for msg in messages:
		msg["files"] = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Chat Message", "attached_to_name": msg["name"]},
			fields=["name", "file_name", "file_size", "file_url", "is_private"],
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
