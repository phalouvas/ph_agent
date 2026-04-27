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
		"""Auto-set user and inherit common settings from the LLM Provider."""
		if not self.user:
			self.user = frappe.session.user
		self._inherit_from_provider()

	def validate(self) -> None:
		"""Validate persona configuration."""
		self._validate_temperature()
		self._enforce_single_default()
		self._warn_persona_count()
		# Re-inherit from provider if the linked provider changed on an existing persona
		if not self.is_new() and self.has_value_changed("default_llm_provider"):
			self._inherit_from_provider()

	# ------------------------------------------------------------------
	# Provider inheritance
	# ------------------------------------------------------------------

	def _resolve_provider(self) -> dict | None:
		"""Resolve the LLM Provider to inherit from.

		Uses the persona's ``default_llm_provider`` if set, otherwise falls
		back to the system default provider (``is_default=1, is_enabled=1``).

		Returns:
			A provider document dict, or None if no provider is found.
		"""
		provider_name = self.default_llm_provider
		if not provider_name:
			defaults = frappe.get_all(
				"LLM Provider",
				filters={"is_default": 1, "is_enabled": 1},
				fields=["name", "temperature", "enable_thinking", "supports_streaming", "enable_suggestions", "system_prompt"],
				limit=1,
			)
			if defaults:
				return defaults[0]
			return None

		try:
			doc = frappe.get_doc("LLM Provider", provider_name)
			return {
				"name": doc.name,
				"temperature": doc.temperature,
				"enable_thinking": doc.enable_thinking,
				"supports_streaming": doc.supports_streaming,
				"enable_suggestions": doc.enable_suggestions,
				"system_prompt": doc.system_prompt,
			}
		except frappe.DoesNotExistError:
			return None

	def _inherit_from_provider(self) -> None:
		"""Inherit common LLM settings from the resolved provider.

		Only fields that are currently empty / falsy are overwritten.
		Explicitly user-set values are always preserved.
		"""
		provider = self._resolve_provider()
		if not provider:
			return

		# Link the provider if persona doesn't have one yet
		if not self.default_llm_provider:
			self.default_llm_provider = provider["name"]

		# Temperature — only inherit if empty
		if self.temperature is None or self.temperature == "":
			if provider.get("temperature") is not None:
				self.temperature = provider["temperature"]

		# Thinking mode — only inherit if not explicitly enabled
		if not self.enable_thinking:
			self.enable_thinking = provider.get("enable_thinking", 0)

		# Streaming — only inherit if not explicitly disabled
		if not self.enable_streaming:
			self.enable_streaming = provider.get("supports_streaming", 1)

		# Suggestions — only inherit if not explicitly disabled
		if not self.enable_suggestions:
			self.enable_suggestions = provider.get("enable_suggestions", 1)

		# System prompt — only inherit if empty
		if not self.system_prompt:
			provider_prompt = provider.get("system_prompt")
			if provider_prompt:
				self.system_prompt = provider_prompt

	# ------------------------------------------------------------------
	# Validation helpers
	# ------------------------------------------------------------------

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
