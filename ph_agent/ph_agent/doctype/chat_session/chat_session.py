import frappe
from frappe.model.document import Document


class ChatSession(Document):
	def before_insert(self):
		if not self.user:
			self.user = frappe.session.user
		if not self.llm_provider:
			default = frappe.get_list(
				"LLM Provider",
				filters={"is_default": 1, "is_enabled": 1},
				pluck="name",
				limit=1,
			)
			if not default:
				frappe.throw(frappe._("No default LLM Provider configured. Please set up a provider first."))
			self.llm_provider = default[0]
