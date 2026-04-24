from __future__ import annotations

import frappe
from frappe.model.document import Document


class UserMemory(Document):
	"""DocType for storing individual LLM-extracted facts about users.

	Each entry represents a single fact, preference, goal, or other
	piece of information learned about a user. Entries are uniquely
	identified by the ``(user, fact)`` pair — re-detecting the same
	fact increments ``encounter_count`` rather than creating duplicates.
	"""

	def before_save(self) -> None:
		"""Auto-set last_encountered_at and normalize the fact field."""
		self.fact = (self.fact or "").strip()
		self.last_encountered_at = frappe.utils.now()
		if self.is_new() and not self.encounter_count:
			self.encounter_count = 1
