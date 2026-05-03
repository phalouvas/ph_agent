"""UserPreferenceProvider — learns user preferences from conversation.

Extracts user preferences (name, date format, response style, language,
preferred doctypes) via regex pattern matching on user messages, then
injects them as system instructions in subsequent turns via the
ContextProvider.before_run() hook.

Preferences are stored in the **Persona** DocType's ``preferences`` JSON
field, scoped to ``(user, persona)``. This means preferences are isolated
per persona — the Business persona learns different preferences than the
Personal persona.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import frappe
from agent_framework import ContextProvider, Message


def _infer_date_format(match: re.Match) -> str:
	"""Infer the date format string from a matched date-like string."""
	date_str = match.group(1)
	# YYYY-MM-DD or YYYY/MM/DD
	if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$", date_str):
		return "YYYY-MM-DD"
	# Try to parse and determine format
	parts = re.split(r"[-/.]", date_str)
	if len(parts) == 3:
		# If first part > 12, it's likely DD
		if int(parts[0]) > 12:
			return "DD-MM-YYYY"
		# If second part > 12, it's likely MM/DD/YYYY
		if int(parts[1]) > 12:
			return "MM-DD-YYYY"
		# Ambiguous — return the raw format as seen
		sep = "/" if "/" in date_str else ("-" if "-" in date_str else ".")
		return f"DD{sep}MM{sep}YYYY"
	return "YYYY-MM-DD"


_LANGUAGE_MAP: dict[str, str] = {
	"hablo español": "es",
	"spanish": "es",
	"habla": "es",
	"español": "es",
	"je parle français": "fr",
	"french": "fr",
	"français": "fr",
	"ich spreche deutsch": "de",
	"german": "de",
	"deutsch": "de",
}


def _infer_language(match: re.Match) -> str:
	"""Map a matched language keyword to an ISO language code."""
	return _LANGUAGE_MAP.get(match.group(1).lower(), match.group(1))


# Default preference definitions with extraction patterns and metadata.
# Each entry defines: key name, regex patterns to detect, and how to
# extract the value from a match.
_PREFERENCE_PATTERNS: list[dict[str, Any]] = [
	{
		"key": "user_name",
		"patterns": [
			r"(?:my name is|I'm|c?all me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
			r"(?:I am|I'm)\s+called\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
		],
		"group": 1,
		"confidence": 0.8,
	},
	{
		"key": "date_format",
		"patterns": [
			r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})",  # YYYY-MM-DD or YYYY/MM/DD
			r"(\d{1,2}[-/]\d{1,2}[-/]\d{4})",  # MM/DD/YYYY or DD/MM/YYYY
			r"(\d{1,2}\.\d{1,2}\.\d{4})",  # DD.MM.YYYY
		],
		"group": 1,
		"confidence": 0.6,
		"transform": _infer_date_format,
	},
	{
		"key": "language",
		"patterns": [
			r"\b(hablo español|spanish|habla|español)\b",
			r"\b(je parle français|french|français)\b",
			r"\b(ich spreche deutsch|german|deutsch)\b",
		],
		"group": 1,
		"confidence": 0.7,
		"transform": _infer_language,
	},
	{
		"key": "response_style",
		"patterns": [
			r"(?:please )?(?:be\s+)?(concise|brief|short)\b",
			r"(?:in\s+)?(detail|detailed|comprehensive|thorough)\b",
			r"(?:explain\s+)?(simply|simple|basic|easy)\b",
			r"(?:keep it\s+)?(professional|formal|casual|informal)\b",
		],
		"group": 1,
		"confidence": 0.7,
	},
	{
		"key": "common_doctypes",
		"patterns": [
			r"(?:show|list|get|find|fetch|query)\s+(\w+(?:\s+\w+)?)\s+(?:for|in|from)",
			r"(?:in|of|for)\s+the\s+(\w+(?:\s+\w+)?)\s+(?:doctype|document|record)",
		],
		"group": 1,
		"confidence": 0.4,  # Lower confidence — could be false positive
	},
	{
		"key": "timezone",
		"patterns": [
			r"(?:time zone|timezone|tz)\s+(?:is\s+)?([A-Za-z]+/[A-Za-z_]+)",
			r"(?:I(?:'m| am)\s+in\s+)([A-Za-z]+/[A-Za-z_]+)\s+(?:time zone|timezone|tz)",
		],
		"group": 1,
		"confidence": 0.8,
	},
]


# Maximum number of preferences to inject as system instructions per turn
_MAX_INJECTED_PREFERENCES = 20


class UserPreferenceProvider(ContextProvider):
	"""ContextProvider that learns and injects user preferences.

	Preferences are persisted in the **Persona** DocType's ``preferences``
	JSON field, scoped to ``(user, persona)``. This makes them available
	across all Chat Sessions for the same persona.

	On each ``before_run()``, loads preferences from the Persona doc and
	injects them as system instructions.

	On each ``after_run()``, scans new conversation messages for preference
	signals (name, date format, style requests, etc.) using regex patterns,
	and persists merged preferences back to the Persona doc.
	"""

	PREFERENCES_KEY = "preferences"

	def __init__(self) -> None:
		super().__init__("user_preferences")
		self._patterns = _PREFERENCE_PATTERNS

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	async def before_run(
		self,
		*,
		agent: Any,
		session: Any,
		context: Any,
		state: dict[str, Any],
	) -> None:
		"""Load preferences from the Persona doc and inject as instructions."""
		user, persona = self._get_user_and_persona(session)
		if not user:
			return

		prefs = self._load_preferences(user, persona=persona)

		# Also cache in session state for same-turn access by after_run
		state[self.PREFERENCES_KEY] = prefs

		instructions_text = self._format_preferences(prefs)
		if instructions_text:
			# Apply token budget — preferences are second priority after memories
			from ph_agent.api.token_counter import consume_context_budget

			instructions_text = consume_context_budget(state, "preferences", instructions_text)
			if instructions_text:
				context.extend_instructions(self.source_id, instructions_text)

	async def after_run(
		self,
		*,
		agent: Any,
		session: Any,
		context: Any,
		state: dict[str, Any],
	) -> None:
		"""Scan new messages for preference signals and persist to the Persona doc."""
		user, persona = self._get_user_and_persona(session)
		if not user:
			return

		# Collect user messages from this turn
		user_messages = [msg for msg in context.input_messages if msg.role == "user"]

		if user_messages:
			msg_text = " | ".join(
				c.text if hasattr(c, "text") and c.text else str(c)
				for msg in user_messages
				for c in (msg.contents or [])
			)

		if not user_messages:
			return

		signals = self._extract_preferences(user_messages)
		if not signals:
			return

		# Merge with existing from Persona doc (not from state — it may be stale
		# if another session updated it)
		existing = self._load_preferences(user, persona=persona)
		now = datetime.utcnow().isoformat()
		merged = self._merge_preferences(existing, signals, now=now)

		self._save_preferences(user, persona, merged)

		# Commit explicitly — after_run may run in a frappe context (streaming thread)
		# where automatic commit doesn't happen before frappe.destroy()
		frappe.db.commit()

		# Also update session state cache so same-turn references are fresh
		state[self.PREFERENCES_KEY] = merged

	# ------------------------------------------------------------------
	# Frappe DB persistence — scoped to (user, persona)
	# ------------------------------------------------------------------

	@staticmethod
	def _get_user_and_persona(session: Any) -> tuple[str | None, str | None]:
		"""Resolve the Frappe user and persona from the session's Chat Session doc."""
		session_id = getattr(session, "session_id", None)
		if not session_id:
			return None, None
		try:
			vals = frappe.db.get_value("Chat Session", session_id, ["user", "persona"])
			if not vals:
				return None, None
			return vals[0], vals[1]
		except Exception:
			return None, None

	@staticmethod
	def _load_preferences(user: str, persona: str | None = None) -> dict[str, Any]:
		"""Load preferences dict from the Persona doc's preferences JSON field."""
		if not user or not persona:
			return {}
		try:
			doc = frappe.get_doc("Persona", persona)
			if doc.preferences:
				if isinstance(doc.preferences, str):
					return json.loads(doc.preferences)
				return dict(doc.preferences)
			return {}
		except frappe.DoesNotExistError, Exception:
			pass
		return {}

	@staticmethod
	def _save_preferences(user: str, persona: str | None, prefs: dict[str, Any]) -> None:
		"""Save preferences dict to the Persona doc's preferences JSON field."""
		if not prefs or not persona:
			return
		try:
			doc = frappe.get_doc("Persona", persona)
			doc.preferences = json.dumps(prefs)
			doc.save(ignore_permissions=True)
		except Exception:
			pass

	# ------------------------------------------------------------------
	# Preference formatting
	# ------------------------------------------------------------------

	@staticmethod
	def _format_preferences(prefs: dict[str, Any]) -> str:
		"""Format stored preferences into a human-readable instruction string.

		Only includes preferences with confidence >= 0.5 to avoid injecting
		noisy or unconfirmed signals. Capped at ``_MAX_INJECTED_PREFERENCES``.
		"""
		parts: list[str] = []
		for key, pref in prefs.items():
			confidence = pref.get("confidence", 0)
			if confidence < 0.5:
				continue

			value = pref.get("value")
			if not value:
				continue

			fmt_key = key.replace("_", " ").title()
			parts.append(f"- {fmt_key}: {value}")

			# Defense-in-depth cap
			if len(parts) >= _MAX_INJECTED_PREFERENCES:
				break

		if not parts:
			return ""

		lines = [
			"The following user preferences have been learned from previous conversation turns:",
			*parts,
			"Please take these into account when generating your response.",
		]
		return "\n".join(lines)

	def _extract_preferences(
		self,
		messages: list[Message],
	) -> dict[str, dict[str, Any]]:
		"""Analyze a list of user messages and extract preference signals.

		Returns:
			A dict mapping preference keys to extracted info:
			``{key: {"value": ..., "confidence": ...}}``.
		"""
		signals: dict[str, dict[str, Any]] = {}

		for msg in messages:
			text = " ".join(c.text if hasattr(c, "text") and c.text else str(c) for c in (msg.contents or []))
			if not text:
				continue

			for pattern_def in self._patterns:
				key = pattern_def["key"]
				transform = pattern_def.get("transform")
				for pattern_str in pattern_def["patterns"]:
					match = re.search(pattern_str, text, re.IGNORECASE)
					if not match:
						continue

					raw_value = match.group(pattern_def["group"])
					value = transform(match) if transform else raw_value

					# Keep the highest-confidence extraction for this key
					existing = signals.get(key)
					new_conf = pattern_def["confidence"]
					if existing and existing.get("confidence", 0) >= new_conf:
						continue

					signals[key] = {
						"value": value,
						"confidence": new_conf,
					}
					break  # First pattern match wins for this preference key

		return signals

	@staticmethod
	def _merge_preferences(
		existing: dict[str, Any],
		signals: dict[str, dict[str, Any]],
		*,
		now: str,
	) -> dict[str, Any]:
		"""Merge newly extracted signals with existing preferences.

		For existing preferences:
		- If the same key is detected again with higher or equal confidence,
		  update the value and increase confidence (up to 1.0).
		- If detected with lower confidence, increment confidence slightly.

		For new preferences not yet stored, add them with ``first_seen_at``
		and ``updated_at`` timestamps.
		"""
		result = dict(existing)

		for key, signal in signals.items():
			prev = result.get(key)
			if prev is None:
				# Brand new preference
				result[key] = {
					"value": signal["value"],
					"confidence": signal["confidence"],
					"first_seen_at": now,
					"updated_at": now,
				}
			else:
				# Existing preference — reinforce or update
				prev_conf = prev.get("confidence", 0)
				new_conf = signal["confidence"]

				if new_conf >= prev_conf:
					# Update value and boost confidence
					prev["value"] = signal["value"]
					prev["confidence"] = min(prev_conf + 0.1, 1.0)
				else:
					# Lower confidence detection — just nudge upward
					prev["confidence"] = min(prev_conf + 0.05, 1.0)
				prev["updated_at"] = now

		return result
