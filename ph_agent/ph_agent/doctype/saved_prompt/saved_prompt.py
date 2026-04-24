import frappe
from frappe.model.document import Document


class SavedPrompt(Document):
	"""DocType for storing user-saved prompt templates with {{variable}} placeholders."""

	def validate(self):
		"""Validate the saved prompt."""
		if not self.content or not self.content.strip():
			frappe.throw("Prompt content cannot be empty.")

		if not self.user:
			self.user = frappe.session.user

	def before_insert(self):
		"""Set user before insert."""
		if not self.user:
			self.user = frappe.session.user
