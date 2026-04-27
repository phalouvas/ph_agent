from __future__ import annotations

import frappe
from frappe.model.document import Document

_PERSONA_LIMIT_WARNING = 5


class Persona(Document):
	"""DocType for user-defined personas that partition chats, memories, and preferences.

	Each persona represents a distinct context or "hat" a user wears when
	chatting with the AI (e.g., Business, Development, Personal). Personas
	provide complete isolation of:
	- Chat sessions (sessions belong to one persona)
	- LLM-extracted memories (facts are scoped to a persona)
	- Learned preferences (response style, language, etc.)
	- Cross-session context (summaries from same persona only)

	Persona-level defaults (system prompt, provider, temperature, thinking
	mode) are inherited by new chat sessions and take precedence over
	provider-level defaults.
	"""

	def before_insert(self) -> None:
		"""Auto-set user if not provided."""
		if not self.user:
			self.user = frappe.session.user

	def validate(self) -> None:
		"""Validate persona configuration."""
		self._validate_temperature()
		self._enforce_single_default()
		self._warn_persona_count()

	def _validate_temperature(self) -> None:
		"""Ensure temperature is within valid range (0-1.5)."""
		if self.temperature is not None and self.temperature != "":
			temp = float(self.temperature)
			if temp < 0 or temp > 1.5:
				frappe.throw(
					frappe._("Temperature must be between 0 and 1.5."),
					title=frappe._("Invalid Temperature"),
				)

	def _enforce_single_default(self) -> None:
		"""Ensure only one persona per user is marked as default."""
		if not self.is_default:
			return

		user = self.user or frappe.session.user
		existing = frappe.get_all(
			"Persona",
			filters={"user": user, "is_default": 1, "name": ["!=", self.name or ""]},
			limit=1,
		)
		for doc in existing:
			frappe.db.set_value("Persona", doc.name, "is_default", 0)

	def _warn_persona_count(self) -> None:
		"""Show informational warning if user has many personas.

		This is a soft guidance — it does not block creation. The warning
		encourages users to consolidate related contexts for better memory
		quality, as many personas with few sessions each dilute the
		effectiveness of the LLM memory extraction system.
		"""
		if self.is_new():
			user = self.user or frappe.session.user
			count = frappe.db.count("Persona", {"user": user})
			if count >= _PERSONA_LIMIT_WARNING:
				frappe.msgprint(
					frappe._(
						"You now have {0} personas. Consider grouping related contexts "
						"together for better memory quality."
					).format(count + 1),
					indicator="orange",
					title=frappe._("Tip: Many Personas"),
				)
