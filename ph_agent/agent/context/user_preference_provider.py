"""UserPreferenceProvider — learns user preferences from conversation.

Extracts user preferences (name, date format, response style, language,
preferred doctypes) via regex pattern matching on user messages, then
injects them as system instructions in subsequent turns via the
ContextProvider.before_run() hook.

Preferences are stored in the provider-scoped ``state`` dict under the
``preferences`` key. Because the session state is persisted by
``_save_session_state()``, preferences survive across turns in the same
session.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

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
            r"(\d{1,2}\.\d{1,2}\.\d{4})",       # DD.MM.YYYY
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


class UserPreferenceProvider(ContextProvider):
    """ContextProvider that learns and injects user preferences.

    On each ``before_run()``, reads stored preferences from the provider-
    scoped ``state`` dict and appends them as system instructions.

    On each ``after_run()``, scans the new conversation messages for
    preference signals (name, date format, style requests, etc.) using
    the defined regex patterns, and merges findings into the preference
    store.
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
        """Load preferences from state and inject as system instructions."""
        prefs = state.get(self.PREFERENCES_KEY)
        if not prefs:
            return

        instructions_text = self._format_preferences(prefs)
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
        """Scan new messages for preference signals and update stored preferences."""
        # Collect all user messages from the new input
        user_messages = [
            msg for msg in context.input_messages
            if msg.role == "user"
        ]

        if not user_messages:
            return

        signals = self._extract_preferences(user_messages)
        if not signals:
            return

        # Merge with existing preferences in provider-scoped state
        now = datetime.utcnow().isoformat()
        existing = state.get(self.PREFERENCES_KEY, {})
        merged = self._merge_preferences(existing, signals, now=now)
        state[self.PREFERENCES_KEY] = merged

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_preferences(prefs: dict[str, Any]) -> str:
        """Format stored preferences into a human-readable instruction string.

        Only includes preferences with confidence >= 0.5 to avoid injecting
        noisy or unconfirmed signals.
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
            text = " ".join(
                str(c) for c in (msg.contents or [])
                if isinstance(c, str)
            )
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
