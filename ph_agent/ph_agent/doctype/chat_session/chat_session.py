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
		
		# Set temperature and suggestions from provider if not explicitly set
		if self.llm_provider:
			provider = frappe.get_doc("LLM Provider", self.llm_provider)
			# Use provider temperature, default to 1.0 if provider temperature is not set
			if self.temperature is None or self.temperature == "":
				self.temperature = provider.temperature if provider.temperature is not None else 1.0
			# Inherit enable_suggestions from provider
			self.enable_suggestions = provider.enable_suggestions
			# Inherit enable_streaming from provider's supports_streaming
			self.enable_streaming = provider.supports_streaming
			# Inherit system_prompt from provider if not explicitly set
			if not self.system_prompt:
				self.system_prompt = provider.system_prompt
	
	def validate(self):
		# Validate temperature range
		if self.temperature is not None:
			if self.temperature < 0 or self.temperature > 1.5:
				frappe.throw(frappe._("Temperature must be between 0 and 1.5"))
