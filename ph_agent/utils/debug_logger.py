# Copyright (c) 2026, phalouvas and contributors
# For license information, please see license.txt

import frappe

_LOG_LEVELS = {"DEBUG": 0, "INFO": 1, "WARNING": 2}


def debug_log(title, message, session=None, level="DEBUG"):
	"""Write a debug entry to Frappe's Error Log, gated by PH Agent Settings.

	Args:
		title: Short description of the debug event.
		message: Detailed context (timing, state, etc.).
		session: Optional Chat Session name — set as reference for filtering.
		level: Log level — DEBUG, INFO, or WARNING. Only entries at or above
			the configured threshold are written.
	"""
	settings = frappe.get_single("PH Agent Settings")
	if not settings.enable_debug_logging:
		return

	# Level threshold check
	threshold = _LOG_LEVELS.get(settings.debug_log_level or "INFO", 1)
	if _LOG_LEVELS.get(level, 0) < threshold:
		return

	frappe.log_error(
		title=f"[PH_DEBUG] {title}",
		message=message,
		reference_doctype="Chat Session" if session else None,
		reference_name=session or None,
	)
