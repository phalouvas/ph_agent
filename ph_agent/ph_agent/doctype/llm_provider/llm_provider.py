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
		
		# Validate temperature range
		if self.temperature is not None:
			if self.temperature < 0 or self.temperature > 1.5:
				frappe.throw(frappe._("Temperature must be between 0 and 1.5"))

		# Validate max_reasoning_turns range
		if self.max_reasoning_turns is not None:
			if self.max_reasoning_turns < 1 or self.max_reasoning_turns > 20:
				frappe.throw(frappe._("Max Reasoning Turns must be between 1 and 20"))
