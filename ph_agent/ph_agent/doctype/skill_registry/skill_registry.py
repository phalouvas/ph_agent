import re

import frappe
from frappe.model.document import Document


SKILL_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]*[a-z0-9])?$")
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024


class SkillRegistry(Document):
	def validate(self):
		"""Validate Skill Registry document."""
		self._validate_skill_name()
		self._validate_description_length()

	def _validate_skill_name(self):
		"""Validate skill_name format: lowercase letters, numbers, hyphens only."""
		if not self.skill_name:
			return

		if len(self.skill_name) > MAX_NAME_LENGTH:
			frappe.throw(
				frappe._("Skill name must be {0} characters or fewer.").format(MAX_NAME_LENGTH)
			)

		if not SKILL_NAME_RE.match(self.skill_name):
			frappe.throw(
				frappe._(
					"Skill name must use only lowercase letters, numbers, and hyphens, "
					"and must not start or end with a hyphen."
				)
			)

	def _validate_description_length(self):
		"""Validate description does not exceed max length."""
		if self.description and len(self.description) > MAX_DESCRIPTION_LENGTH:
			frappe.throw(
				frappe._("Description must be {0} characters or fewer.").format(MAX_DESCRIPTION_LENGTH)
			)

