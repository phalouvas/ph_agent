"""Session state size management and compaction.

Handles loading, saving, and size enforcement for ``Chat Session.session_state``.
"""

import json
from typing import Any

import frappe

# Keys that are known to always be empty and can be stripped on save.
_KNOWN_EMPTY_KEYS = {"frappe_history", "agent_skills"}

# Keys that are legacy from InMemoryHistoryProvider and can be stripped on load.
_KNOWN_LEGACY_KEYS = {"in_memory"}


class LoggingEncoder(json.JSONEncoder):
	"""JSON encoder that logs warnings for non-standard types instead of silently stringifying."""

	def default(self, obj):
		if isinstance(obj, (str, int, float, bool, type(None), list, dict)):
			return super().default(obj)
		frappe.log_error(
			title="Session state serialization: non-standard type",
			message=f"Non-standard type {type(obj).__name__} encountered during JSON serialization.",
		)
		try:
			return super().default(obj)
		except TypeError:
			return str(obj)


def get_max_state_bytes() -> int:
	"""Return the configured max session state size in bytes."""
	try:
		settings = frappe.get_single("PH Agent Settings")
		kb = settings.max_session_state_size_kb
		if kb and kb > 0:
			return int(kb) * 1024
	except Exception:
		pass
	return 500 * 1024  # default 500KB


def is_compaction_enabled() -> bool:
	"""Return whether session state compaction is enabled in settings."""
	try:
		settings = frappe.get_single("PH Agent Settings")
		return bool(settings.session_state_compaction_enabled)
	except Exception:
		return True


def cleanup_state_on_load(state: dict[str, Any]) -> dict[str, Any]:
	"""Strip known-legacy, stale budget, and known-empty keys from state on load.

	Safe to run on every load — only removes data that is demonstrably
	unnecessary:

	- ``in_memory``: Legacy InMemoryHistoryProvider messages that may
	  exist in old sessions. Current code uses FrappeMemoryProvider instead.
	- Per-provider ``_ctx_budget_remaining`` / ``_ctx_budget_consumed``: stale
	  budget counters from the previous turn. Re-initialized fresh each turn
	  by ``init_context_budget()`` and ``consume_context_budget()``.
	- Empty dicts for keys known to never hold data (frappe_history, agent_skills).
	"""
	if not state:
		return state

	for legacy_key in _KNOWN_LEGACY_KEYS:
		state.pop(legacy_key, None)

	for empty_key in _KNOWN_EMPTY_KEYS:
		if empty_key in state and isinstance(state[empty_key], dict) and not state[empty_key]:
			del state[empty_key]

	# Strip per-provider budget keys — recreated fresh each turn
	_budget_keys = {"_ctx_budget_remaining", "_ctx_budget_consumed"}
	for key, value in state.items():
		if isinstance(value, dict) and key not in _budget_keys:
			for bk in _budget_keys:
				value.pop(bk, None)

	return state


def compact_state(
	state: dict[str, Any],
	current_size_bytes: int,
	max_bytes: int,
) -> dict[str, Any]:
	"""Apply escalating compaction strategies.

	Steps (in order of decreasing safety):
	1. Remove empty top-level dicts (except budget infrastructure keys)
	2. If still over limit, truncate individual string values > 1000 chars
	   in the largest provider sub-state

	Returns the compacted state (mutates in-place).
	"""
	# Step 1: Remove empty top-level dicts (skip internal budget keys)
	keys_to_remove = []
	for key, value in state.items():
		if key in ("_ctx_budget_remaining", "_ctx_budget_consumed"):
			continue
		if isinstance(value, dict) and not value:
			keys_to_remove.append(key)
	for key in keys_to_remove:
		del state[key]

	# Re-check size after step 1
	if _serialized_size(state) <= max_bytes:
		return state

	# Step 2: Find the largest provider sub-state and truncate its string values
	largest_key = _find_largest_key(state)
	if largest_key:
		value = state[largest_key]
		old_size = len(json.dumps(value, ensure_ascii=False))
		if isinstance(value, dict):
			_truncate_dict_values(value)
		elif isinstance(value, list):
			_truncate_list_values(value)
		new_size = len(json.dumps(state[largest_key], ensure_ascii=False))
		frappe.log_error(
			title="Session state compaction: truncated",
			message=f"Compaction truncated '{largest_key}' from {old_size} to {new_size} bytes.",
		)

	return state


def emergency_truncate(state: dict[str, Any], max_bytes: int) -> dict[str, Any]:
	"""Last-resort truncation: keep only first 2 sub-keys of the largest provider dict.

	Iterates from largest to smallest provider dict until the state fits within max_bytes.
	"""
	candidates = []
	for key, value in state.items():
		if key in ("_ctx_budget_remaining", "_ctx_budget_consumed") or key in _KNOWN_EMPTY_KEYS:
			continue
		if isinstance(value, dict):
			candidates.append((key, len(json.dumps(value, ensure_ascii=False))))
	candidates.sort(key=lambda x: x[1], reverse=True)

	for key, _ in candidates:
		provider_state = state.get(key, {})
		if isinstance(provider_state, dict) and len(provider_state) > 2:
			essential_keys = list(provider_state.keys())[:2]
			state[key] = {k: provider_state[k] for k in essential_keys}
			if _serialized_size(state) <= max_bytes:
				break

	return state


def compact_json_dumps(obj: Any) -> str:
	"""Serialize to compact JSON (no indent, no ASCII escaping)."""
	return json.dumps(obj, ensure_ascii=False, cls=LoggingEncoder)


def _serialized_size(obj: Any) -> int:
	"""Return the byte size of obj serialized to compact JSON."""
	return len(compact_json_dumps(obj))


def _find_largest_key(state: dict[str, Any]) -> str | None:
	"""Find the key whose JSON representation is the largest."""
	largest_key = None
	largest_size = 0
	for key, value in state.items():
		if isinstance(value, (dict, list)):
			size = len(json.dumps(value, ensure_ascii=False))
			if size > largest_size:
				largest_size = size
				largest_key = key
	return largest_key


def _truncate_dict_values(d: dict[str, Any]) -> None:
	"""Truncate string values > 1000 chars in a dict (recursing into nested dicts and lists)."""
	for key, value in list(d.items()):
		if isinstance(value, str) and len(value) > 1000:
			d[key] = value[:1000] + "..."
		elif isinstance(value, dict):
			_truncate_dict_values(value)
		elif isinstance(value, list):
			_truncate_list_values(value)


def _truncate_list_values(lst: list[Any]) -> None:
	"""Truncate string values > 1000 chars in list items."""
	for i, item in enumerate(lst):
		if isinstance(item, dict):
			_truncate_dict_values(item)
		elif isinstance(item, str) and len(item) > 1000:
			lst[i] = item[:1000] + "..."
