import frappe


def _emit_status(session, message):
	"""Push a transient status string to the session owner's browser."""
	frappe.publish_realtime(
		event="agent_status",
		message={"session": session, "status": message},
		room="website",
	)


def _delete_files_attached_to_message(message_id):
	"""
	Delete all File documents attached to a Chat Message.
	This properly deletes both the database record and the physical file from disk.
	"""
	# Get all File documents attached to this message
	file_names = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Chat Message", "attached_to_name": message_id},
		pluck="name",
	)
	
	# Delete each File document properly (triggers on_trash to delete physical file)
	for file_name in file_names:
		try:
			frappe.delete_doc("File", file_name, ignore_permissions=True, force=True)
		except Exception as e:
			# Log error but continue with other files
			frappe.log_error(
				f"Failed to delete file {file_name} attached to message {message_id}: {str(e)}",
				"ph_agent_file_deletion"
			)


def _get_recent_session_context(user: str, persona: str | None = None, limit: int = 3) -> str | None:
	"""Build a grounding context string from the user's recent sessions in the same persona.

	Reads the ``last_summary_message`` content from the most recent sessions
	to provide cross-session continuity when starting a new conversation.

	Args:
		user: The Frappe user to look up sessions for.
		persona: The persona to scope sessions to. If None, loads sessions
			without persona filter (legacy fallback).
		limit: Maximum number of recent sessions to include.

	Returns:
		A formatted string with previous session context, or None if no
		sessions with summaries are found.
	"""
	try:
		filters: dict[str, Any] = {"user": user, "status": ["in", ["Open", "Closed"]]}
		if persona:
			filters["persona"] = persona
		sessions = frappe.get_all(
			"Chat Session",
			filters=filters,
			fields=["name", "title", "last_summary_message"],
			order_by="modified desc",
			limit_page_length=limit,
		)
	except Exception:
		return None

	if not sessions:
		return None

	context_parts: list[str] = []
	for session_doc in sessions:
		title = session_doc.title or "Untitled"
		summary_msg = session_doc.last_summary_message

		if summary_msg:
			# Use the LLM-generated summary
			try:
				summary_content = frappe.db.get_value(
					"Chat Message", summary_msg, "content"
				)
				if summary_content:
					# Strip the "📋 Summary" header if present
					clean = summary_content
					if clean.startswith("*📋 Summary*"):
						clean = clean[len("*📋 Summary*"):].strip()
					context_parts.append(f'In session "{title}": {clean}')
			except Exception:
				pass
		else:
			# Fallback: get the first user message as minimal context
			try:
				first_msg = frappe.get_all(
					"Chat Message",
					filters={"chat_session": session_doc.name, "sender_type": "User"},
					fields=["content"],
					order_by="creation asc",
					limit_page_length=1,
				)
				if first_msg and first_msg[0].content:
					content = first_msg[0].content[:200]
					context_parts.append(f'In session "{title}": user asked about "{content}"')
			except Exception:
				pass

	if not context_parts:
		return None

	return "\n".join(context_parts)


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
def update_session_settings(session, title=None, provider_name=None, enable_thinking=None):
	"""Update title, LLM provider, and/or thinking mode on a Chat Session in a single call."""
	frappe.has_permission("Chat Session", doc=session, throw=True)

	update_dict = {}
	if title is not None:
		update_dict["title"] = title
	if provider_name is not None:
		if not frappe.db.exists("LLM Provider", {"name": provider_name, "is_enabled": 1}):
			frappe.throw(frappe._("LLM Provider {0} not found or is disabled.").format(provider_name))
		update_dict["llm_provider"] = provider_name
	if enable_thinking is not None:
		update_dict["enable_thinking"] = enable_thinking

	if not update_dict:
		return {"status": "ok"}

	frappe.db.set_value("Chat Session", session, update_dict)
	frappe.db.commit()
	return {"status": "ok"}


@frappe.whitelist()
def create_session(provider_name=None, persona=None):
	"""Create a new Chat Session. Uses default LLM Provider if provider_name not specified.

	Args:
		provider_name: Optional LLM Provider name. Uses default if not specified.
		persona: Optional Persona name to associate with this session.
	"""
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

	# Resolve persona — use default if not specified
	if not persona:
		default_persona = frappe.get_all(
			"Persona",
			filters={"user": frappe.session.user, "is_default": 1},
			pluck="name",
			limit=1,
		)
		if default_persona:
			persona = default_persona[0]
		else:
			frappe.throw(frappe._("No persona specified and no default persona found. Please create a persona first."))

	# Validate persona belongs to current user
	if persona:
		persona_user = frappe.db.get_value("Persona", persona, "user")
		if persona_user != frappe.session.user:
			frappe.throw(frappe._("Persona {0} does not belong to you.").format(persona))

	session = frappe.get_doc(
		{
			"doctype": "Chat Session",
			"title": "New Chat",
			"persona": persona,
			"user": frappe.session.user,
			"llm_provider": provider_name,
			"status": "Open",
		}
	)
	session.insert(ignore_permissions=False)
	frappe.db.commit()

	# Inject previous session context for cross-session continuity (scoped to persona)
	previous_context = _get_recent_session_context(frappe.session.user, persona=persona)
	if previous_context:
		current_prompt = session.system_prompt or ""
		context_block = (
			"[Previous conversation context from recent sessions - "
			"use for continuity but do not mention explicitly]\n"
			f"{previous_context}"
		)
		if current_prompt:
			context_block += f"\n\n---\n\n{current_prompt}"
		frappe.db.set_value("Chat Session", session.name, "system_prompt", context_block)
		frappe.db.commit()

	return {"session": session.name, "title": session.title, "llm_provider": session.llm_provider}


@frappe.whitelist()
def send_message(session, content, **kwargs):
	"""Store a user message and enqueue the LLM agent response as a background job."""
	frappe.has_permission("Chat Session", doc=session, throw=True)
	
	# Get file_names from kwargs (might be passed as file_names or files)
	file_names = kwargs.get('file_names') or kwargs.get('files')
	
	# Per-session lock: prevent concurrent processing
	lock_key = f"ph_agent:lock:{session}"
	if frappe.cache().get_value(lock_key):
		frappe.throw(frappe._("Another message is already being processed. Please wait."), frappe.exceptions.ValidationError)
	frappe.cache().set_value(lock_key, "1", expires_in_sec=660)

	# Clear any stale cancel flag from a previous Stop (e.g. if the worker was killed mid-flight)
	frappe.cache().delete_value(f"ph_agent:cancel:{session}")

	# Store user message
	user_msg = frappe.get_doc(
		{
			"doctype": "Chat Message",
			"chat_session": session,
			"sender_type": "User",
			"message_type": "User",
			"content": content,
		}
	).insert(ignore_permissions=False)

	# Link any uploaded files to this message
	# Handle different formats: JSON string, comma-separated string, list, or None
	file_names_list = []
	if file_names is not None:
		if isinstance(file_names, str):
			# Try to parse as JSON first
			try:
				file_names_list = frappe.parse_json(file_names)
			except Exception as e:
				# Try as comma-separated string
				if file_names.strip():
					if ',' in file_names:
						# Comma-separated list
						file_names_list = [name.strip() for name in file_names.split(',') if name.strip()]
					else:
						# Single file name
						file_names_list = [file_names.strip()]
		elif isinstance(file_names, (list, tuple)):
			file_names_list = list(file_names)
		else:
			frappe.log_error(f"DEBUG: Unexpected file_names type: {type(file_names)}, value: {file_names}", "ph_agent_chat")

	# Also check what the actual File documents look like
	if file_names_list:
		for file_name in file_names_list:
			# Check if file exists
			if frappe.db.exists("File", file_name):
				file_doc = frappe.get_doc("File", file_name)
				frappe.db.set_value(
					"File",
					file_name,
					{"attached_to_doctype": "Chat Message", "attached_to_name": user_msg.name},
				)
			else:
				frappe.log_error(f"DEBUG: File {file_name} does not exist in database!", "ph_agent_chat")

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
		now=False
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

	# Release the per-session processing lock
	frappe.cache().delete_value(f"ph_agent:lock:{session}")

	# Set cooperative cancellation flag for in-progress PDF extraction checks
	frappe.cache().set_value(f"ph_agent:cancel:{session}", True, expires_in_sec=60)

	# Clear the status bar and notify the frontend
	_emit_status(session, "")
	frappe.publish_realtime(
		event="generation_cancelled",
		message={"session": session},
		room="website",
	)

	return {"status": "cancelled"}


@frappe.whitelist()
def get_history(session):
	"""Return all messages for a Chat Session, ordered by creation time."""
	frappe.has_permission("Chat Session", doc=session, throw=True)
	messages = frappe.get_all(
		"Chat Message",
		filters={"chat_session": session},
		fields=["name", "sender_type", "content", "creation", "is_edited"],
		order_by="creation asc",
	)
	for msg in messages:
		msg["files"] = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Chat Message", "attached_to_name": msg["name"]},
			fields=["name", "file_name", "file_size", "file_url", "is_private", "file_type"],
		)
	return messages


@frappe.whitelist()
def delete_session(session):
	"""Delete a Chat Session and all its messages."""
	frappe.has_permission("Chat Session", ptype="delete", doc=session, throw=True)
	
	# Get all messages in this session
	messages = frappe.get_all(
		"Chat Message",
		filters={"chat_session": session},
		pluck="name",
	)
	
	# Before deleting messages, clear User Memory references to them
	# to avoid LinkExistsError (User Memory.source_message/source_session
	# link to Chat Message and Chat Session respectively)
	for message_id in messages:
		frappe.db.set_value(
			"User Memory",
			{"source_message": message_id},
			"source_message",
			None,
		)
	# Also clear User Memory source_session references to this session
	frappe.db.set_value(
		"User Memory",
		{"source_session": session},
		"source_session",
		None,
	)
	# Clear the session's last_summary_message reference to prevent link
	# validation from blocking deletion of the referenced Chat Message
	frappe.db.set_value("Chat Session", session, "last_summary_message", None)
	frappe.db.commit()
	
	# Delete each message individually (triggers on_trash hook which deletes attached files)
	for message_id in messages:
		try:
			frappe.delete_doc("Chat Message", message_id, ignore_permissions=True)
		except Exception as e:
			# Log error but continue with other messages
			frappe.log_error(
				f"Failed to delete message {message_id} in session {session}: {str(e)}",
				"ph_agent_session_deletion"
			)
	
	# Delete the session
	frappe.delete_doc("Chat Session", session, ignore_permissions=False)
	frappe.db.commit()
	return {"status": "ok"}


@frappe.whitelist()
def edit_message(message_id, content):
	"""Edit a user message, delete all subsequent messages, and re-run the agent."""
	msg = frappe.get_doc("Chat Message", message_id)
	if msg.sender_type != "User":
		frappe.throw(frappe._("Only user messages can be edited."))
	if msg.owner != frappe.session.user:
		frappe.throw(frappe._("You can only edit your own messages."), frappe.exceptions.PermissionError)
	frappe.has_permission("Chat Session", doc=msg.chat_session, throw=True)

	session = msg.chat_session
	lock_key = f"ph_agent:lock:{session}"
	if frappe.cache().get_value(lock_key):
		frappe.throw(
			frappe._("Another message is already being processed. Please wait."),
			frappe.exceptions.ValidationError,
		)

	# Save the edited content
	msg.content = content
	msg.is_edited = 1
	msg.edited_at = frappe.utils.now_datetime()
	msg.edited_by = frappe.session.user
	msg.save(ignore_permissions=True)

	# Delete ALL messages that came after this one
	subsequent = frappe.get_all(
		"Chat Message",
		filters={"chat_session": session, "creation": [">", msg.creation]},
		fields=["name"],
		order_by="creation asc",
	)
	deleted_ids = []
	for subsequent_msg in subsequent:
		deleted_ids.append(subsequent_msg.name)
		# Clear User Memory references to this message to avoid LinkExistsError
		frappe.db.set_value(
			"User Memory",
			{"source_message": subsequent_msg.name},
			"source_message",
			None,
		)
		# Delete the chat message (on_trash hook will delete attached files)
		frappe.delete_doc("Chat Message", subsequent_msg.name, ignore_permissions=True)

	frappe.db.commit()

	frappe.publish_realtime(
		event="message_edited",
		message={
			"session": session,
			"message_id": message_id,
			"content": content,
			"is_edited": True,
			"deleted_ids": deleted_ids,
		},
		room="website",
	)

	# Re-enqueue the agent with the updated content
	file_names = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Chat Message", "attached_to_name": message_id},
		pluck="name",
	)
	frappe.cache().set_value(lock_key, "1", expires_in_sec=660)
	frappe.cache().delete_value(f"ph_agent:cancel:{session}")
	_emit_status(session, frappe._("Calling AI…"))

	job = frappe.enqueue(
		"ph_agent.api.agent_jobs._call_agent_background",
		session=session,
		user_msg_name=message_id,
		content=content,
		file_names=file_names,
		enqueued_by=frappe.session.user,
		queue="long",
		timeout=600,
		now=False
	)
	frappe.cache().set_value(f"ph_agent:job:{session}", job.id, expires_in_sec=600)

	return {"status": "queued", "deleted_ids": deleted_ids}


@frappe.whitelist()
def summarize_conversation(session, message_ids=None):
	"""
	Summarize a conversation or selected messages.
	
	Args:
		session: Chat Session name
		message_ids: Optional list of message IDs to summarize. If None, summarizes all messages since last summary.
	
	Returns:
		Dictionary with summary message ID
	"""
	frappe.has_permission("Chat Session", doc=session, throw=True)
	
	# Import here to avoid circular imports
	from ph_agent.agent.framework_agent import generate_conversation_summary
	
	# Get session and provider
	session_doc = frappe.get_doc("Chat Session", session)
	provider_doc = frappe.get_doc("LLM Provider", session_doc.llm_provider)
	
	# Get messages to summarize
	if message_ids:
		# Summarize specific messages
		message_ids = frappe.parse_json(message_ids) if isinstance(message_ids, str) else message_ids
		messages = frappe.get_all(
			"Chat Message",
			filters={"name": ["in", message_ids], "chat_session": session},
			fields=["name", "sender_type", "content", "creation"],
			order_by="creation asc",
		)
	else:
		# Summarize all messages since last summary
		last_summary = session_doc.last_summary_message
		if last_summary:
			# Get messages after the last summary
			last_summary_doc = frappe.get_doc("Chat Message", last_summary)
			messages = frappe.get_all(
				"Chat Message",
				filters={
					"chat_session": session,
					"creation": [">", last_summary_doc.creation],
					"message_type": ["!=", "Summary"]  # Don't include other summaries
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
	
	if not messages:
		frappe.throw(frappe._("No messages to summarize"))
	
	# Format conversation history for summarization
	conversation_history = []
	for msg in messages:
		role = "user" if msg.sender_type == "User" else "assistant"
		conversation_history.append({"role": role, "content": msg.content or ""})
	
	# Generate summary
	try:
		summary = generate_conversation_summary(session, conversation_history)
	except Exception as e:
		frappe.log_error(
			title=f"Summarization failed for session {session}",
			message=str(e)
		)
		frappe.throw(frappe._("Failed to generate summary: {0}").format(str(e)))
	
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
			"token_warning_sent": 0,  # Reset warning flag
		}
	)
	frappe.db.commit()
	
	# Get context length for token update
	context_length = provider_doc.context_length or 128000
	
	# Publish token update event (tokens reset to 0)
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
		room="website",
	)
	
	return {"status": "success", "summary_message_id": summary_msg.name}


@frappe.whitelist()
def delete_message(message_id):
	"""Delete a Chat Message. Users can delete their own messages; agent messages can be deleted by anyone with session access."""
	msg = frappe.get_doc("Chat Message", message_id)
	frappe.has_permission("Chat Session", doc=msg.chat_session, throw=True)

	# For user messages, only the owner can delete
	if msg.sender_type == "User" and msg.owner != frappe.session.user:
		frappe.has_permission("Chat Session", ptype="write", doc=msg.chat_session, throw=True)

	session = msg.chat_session
	
	# Check if this is a summary message that's referenced as last_summary_message
	session_doc = frappe.get_doc("Chat Session", session)
	if session_doc.last_summary_message == message_id:
		# Clear the reference before deleting the message
		frappe.db.set_value("Chat Session", session, "last_summary_message", None)
	
	# Clear User Memory references to this message to avoid LinkExistsError
	frappe.db.set_value(
		"User Memory",
		{"source_message": message_id},
		"source_message",
		None,
	)
	frappe.db.commit()
	
	# Delete the chat message (on_trash hook will delete attached files)
	frappe.delete_doc("Chat Message", message_id, ignore_permissions=True)
	frappe.db.commit()

	frappe.publish_realtime(
		event="message_deleted",
		message={"session": session, "message_id": message_id},
		room="website",
	)
	return {"status": "ok"}


@frappe.whitelist()
def delete_messages(message_ids):
	"""Batch delete multiple Chat Messages."""
	ids = frappe.parse_json(message_ids) if isinstance(message_ids, str) else message_ids
	sessions_affected = set()
	deleted_by_session = {}

	for message_id in ids:
		msg = frappe.get_doc("Chat Message", message_id)
		frappe.has_permission("Chat Session", doc=msg.chat_session, throw=True)
		if msg.sender_type == "User" and msg.owner != frappe.session.user:
			frappe.has_permission("Chat Session", ptype="write", doc=msg.chat_session, throw=True)
		
		session = msg.chat_session
		sessions_affected.add(session)
		deleted_by_session.setdefault(session, []).append(message_id)
		
		# Check if this is a summary message that's referenced as last_summary_message
		session_doc = frappe.get_doc("Chat Session", session)
		if session_doc.last_summary_message == message_id:
			# Clear the reference before deleting the message
			frappe.db.set_value("Chat Session", session, "last_summary_message", None)
		
		# Clear User Memory references to this message to avoid LinkExistsError
		frappe.db.set_value(
			"User Memory",
			{"source_message": message_id},
			"source_message",
			None,
		)
		
		# Delete the chat message (on_trash hook will delete attached files)
		frappe.delete_doc("Chat Message", message_id, ignore_permissions=True)

	frappe.db.commit()

	for session in sessions_affected:
		frappe.publish_realtime(
			event="messages_deleted",
			message={"session": session, "message_ids": deleted_by_session[session]},
			room="website",
		)
	return {"status": "ok"}


@frappe.whitelist()
def regenerate_message(message_id):
	"""Delete an agent message and re-run the agent for the preceding user message."""
	msg = frappe.get_doc("Chat Message", message_id)
	if msg.sender_type != "Agent":
		frappe.throw(frappe._("Only agent messages can be regenerated."))
	frappe.has_permission("Chat Session", doc=msg.chat_session, throw=True)

	session = msg.chat_session
	lock_key = f"ph_agent:lock:{session}"
	if frappe.cache().get_value(lock_key):
		frappe.throw(
			frappe._("Another message is already being processed. Please wait."),
			frappe.exceptions.ValidationError,
		)

	# Find the preceding user message
	preceding = frappe.get_all(
		"Chat Message",
		filters={"chat_session": session, "creation": ["<", msg.creation], "sender_type": "User"},
		fields=["name", "content", "creation"],
		order_by="creation desc",
		limit=1,
	)
	if not preceding:
		frappe.throw(frappe._("No preceding user message found to regenerate from."))

	user_msg = preceding[0]
	file_names = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Chat Message", "attached_to_name": user_msg.name},
		pluck="name",
	)

	# Set lock and enqueue agent (the background job will delete the old agent message)
	frappe.cache().set_value(lock_key, "1", expires_in_sec=660)
	frappe.cache().delete_value(f"ph_agent:cancel:{session}")
	_emit_status(session, frappe._("Calling AI…"))

	job = frappe.enqueue(
		"ph_agent.api.agent_jobs._call_agent_background",
		session=session,
		user_msg_name=user_msg.name,
		content=user_msg.content,
		file_names=file_names,
		enqueued_by=frappe.session.user,
		agent_msg_name=message_id,
		queue="long",
		timeout=600,
		now=False
	)
	frappe.cache().set_value(f"ph_agent:job:{session}", job.id, expires_in_sec=600)

	return {"status": "queued"}


# ── Saved Prompts API ──────────────────────────────────────────────


@frappe.whitelist()
def list_saved_prompts(category=None):
	"""List saved prompts for the current user, ordered by favorites first, then usage count."""
	filters = {"user": frappe.session.user}
	if category:
		filters["category"] = category

	prompts = frappe.get_all(
		"Saved Prompt",
		filters=filters,
		fields=["name", "title", "content", "category", "is_favorite", "usage_count", "modified"],
		order_by="is_favorite desc, usage_count desc, modified desc",
	)
	return prompts


@frappe.whitelist()
def save_prompt(title, content, category=None, is_favorite=0, prompt_id=None):
	"""Create or update a saved prompt for the current user."""
	if not title or not title.strip():
		frappe.throw(frappe._("Title is required."))
	if not content or not content.strip():
		frappe.throw(frappe._("Content is required."))

	if prompt_id:
		# Update existing prompt
		prompt = frappe.get_doc("Saved Prompt", prompt_id)
		if prompt.user != frappe.session.user:
			frappe.throw(frappe._("You can only edit your own prompts."), frappe.exceptions.PermissionError)
		prompt.title = title
		prompt.content = content
		prompt.category = category
		prompt.is_favorite = 1 if is_favorite in (1, "1", True) else 0
		prompt.save(ignore_permissions=True)
		frappe.db.commit()
		return {"status": "ok", "name": prompt.name}
	else:
		# Create new prompt
		prompt = frappe.get_doc({
			"doctype": "Saved Prompt",
			"user": frappe.session.user,
			"title": title,
			"content": content,
			"category": category,
			"is_favorite": 1 if is_favorite in (1, "1", True) else 0,
		})
		prompt.insert(ignore_permissions=True)
		frappe.db.commit()
		return {"status": "ok", "name": prompt.name}


@frappe.whitelist()
def delete_prompt(prompt_id):
	"""Delete a saved prompt. Only the owner can delete."""
	prompt = frappe.get_doc("Saved Prompt", prompt_id)
	if prompt.user != frappe.session.user:
		frappe.throw(frappe._("You can only delete your own prompts."), frappe.exceptions.PermissionError)
	frappe.delete_doc("Saved Prompt", prompt_id, ignore_permissions=True)
	frappe.db.commit()
	return {"status": "ok"}


@frappe.whitelist()
def get_prompt(prompt_id):
	"""Get a single saved prompt by ID."""
	prompt = frappe.get_doc("Saved Prompt", prompt_id)
	if prompt.user != frappe.session.user:
		frappe.throw(frappe._("Prompt not found."), frappe.exceptions.PermissionError)
	return {
		"name": prompt.name,
		"title": prompt.title,
		"content": prompt.content,
		"category": prompt.category,
		"is_favorite": prompt.is_favorite,
		"usage_count": prompt.usage_count,
		"modified": str(prompt.modified),
	}


@frappe.whitelist()
def increment_prompt_usage(prompt_id):
	"""Increment the usage count for a saved prompt."""
	prompt = frappe.get_doc("Saved Prompt", prompt_id)
	if prompt.user != frappe.session.user:
		frappe.throw(frappe._("Prompt not found."), frappe.exceptions.PermissionError)
	prompt.db_set("usage_count", (prompt.usage_count or 0) + 1)
	frappe.db.commit()
	return {"status": "ok"}
