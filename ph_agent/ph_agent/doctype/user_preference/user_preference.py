from __future__ import annotations

import json

import frappe
from frappe.model.document import Document


class UserPreference(Document):
	"""DocType for persisting learned user preferences across sessions.

	Each user has exactly one UserPreference document (autoname = field:user).
	Preferences are stored as a JSON dict in the ``preferences`` field.
	"""

	def before_insert(self) -> None:
		"""Auto-set user to the logged-in user."""
		if not self.user:
			self.user = frappe.session.user

	def before_save(self) -> None:
		"""Ensure preferences is valid JSON on save."""
		if self.preferences and isinstance(self.preferences, str):
			try:
				frappe.parse_json(self.preferences)
			except (json.JSONDecodeError, TypeError):
				frappe.throw("Preferences must be valid JSON.")
