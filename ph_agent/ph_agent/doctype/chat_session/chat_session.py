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

		# Resolve persona defaults — persona-level values take precedence over provider defaults
		persona = None
		if self.persona:
			try:
				persona = frappe.get_doc("Persona", self.persona)
			except frappe.DoesNotExistError:
				pass

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
			# Inherit enable_thinking from provider (only if session override is not set)
			if not self.enable_thinking:
				self.enable_thinking = provider.enable_thinking
			# Inherit system_prompt from provider if not explicitly set
			if not self.system_prompt:
				self.system_prompt = provider.system_prompt

		# Persona-level overrides — these take precedence over provider defaults
		if persona:
			if persona.default_llm_provider:
				self.llm_provider = persona.default_llm_provider
			if persona.temperature is not None and persona.temperature != "":
				self.temperature = persona.temperature
			if persona.enable_thinking:
				self.enable_thinking = 1
			if persona.system_prompt:
				# Prepend persona system prompt to any existing prompt
				if self.system_prompt:
					self.system_prompt = f"{persona.system_prompt}\n\n---\n\n{self.system_prompt}"
				else:
					self.system_prompt = persona.system_prompt
			# Persona streaming/suggestions override provider defaults
			self.enable_streaming = persona.enable_streaming
			self.enable_suggestions = persona.enable_suggestions
	
	def validate(self):
		# Validate temperature range
		if self.temperature is not None:
			if self.temperature < 0 or self.temperature > 1.5:
				frappe.throw(frappe._("Temperature must be between 0 and 1.5"))
	
	def before_save(self):
		"""Clear session state when session is closed or archived."""
		if self.has_value_changed("status"):
			if self.status in ["Closed", "Archived"]:
				# Clear session state when closing or archiving
				self.session_state = None
				self.last_state_update = None
			elif self.status == "Open" and self._doc_before_save:
				# If reopening a previously closed/archived session, keep state cleared
				# (state would need to be rebuilt from conversation history)
				pass
