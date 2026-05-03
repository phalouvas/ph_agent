"""Scheduled tasks for PH Agent.

Tasks registered in ``hooks.py`` under ``scheduler_events``.
"""

import frappe


def cleanup_temporary_sessions():
	"""Delete temporary Chat Sessions that are older than 1 hour.

	This is a safety net for temporary sessions that were not cleaned up
	when the user navigated away (e.g. browser crash, network failure,
	or the ``beforeunload`` ``sendBeacon`` call did not reach the server).

	Runs hourly via the Frappe scheduler.
	"""
	cutoff = frappe.utils.add_to_date(frappe.utils.now(), hours=-1)
	stale_sessions = frappe.get_all(
		"Chat Session",
		filters={
			"is_temporary": 1,
			"modified": ["<", cutoff],
		},
		pluck="name",
	)

	if not stale_sessions:
		return

	for session_name in stale_sessions:
		try:
			# Get all messages in this session
			messages = frappe.get_all(
				"Chat Message",
				filters={"chat_session": session_name},
				pluck="name",
			)

			# Delete User Memory records linked to this session or its messages
			for message_id in messages:
				frappe.db.delete("User Memory", {"source_message": message_id})
			frappe.db.delete("User Memory", {"source_session": session_name})

			# Clear last_summary_message link
			frappe.db.set_value("Chat Session", session_name, "last_summary_message", None)
			frappe.db.commit()

			# Delete each message
			for message_id in messages:
				try:
					frappe.delete_doc("Chat Message", message_id, ignore_permissions=True)
				except Exception:
					pass

			# Delete the session
			frappe.delete_doc("Chat Session", session_name, ignore_permissions=True)
			frappe.db.commit()
		except Exception as e:
			frappe.log_error(
				title="Temporary session cleanup failed",
				message=f"Session: {session_name}, Error: {e}",
			)
