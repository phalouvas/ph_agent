import frappe
from frappe.model.document import Document


class LLMProvider(Document):
	def validate(self):
		if self.is_default:
			# Ensure only one record has is_default checked
			existing = frappe.get_list(
				"LLM Provider",
				filters={"is_default": 1, "name": ("!=", self.name)},
				pluck="name",
			)
			if existing:
				frappe.throw(
					frappe._("Only one LLM Provider can be set as default. Currently default: {0}").format(
						existing[0]
					)
				)
