"""Helper for atomic token counter updates.

Uses raw SQL UPDATE with COALESCE to avoid read-then-write races.
"""

import time

import frappe


def _atomic_update_chat_session_tokens(session: str, input_tokens: int, output_tokens: int, cache_hit_tokens: int) -> None:
	"""Atomically increment Chat Session token counters.

	Retries on QueryDeadlockError (MariaDB ER_CHECKREAD / MySQL deadlock)
	which can occur when the Chat Session row was read earlier in the same
	transaction and another process modified it before our UPDATE commits.
	"""
	sql = """UPDATE `tabChat Session`
		SET input_tokens = COALESCE(input_tokens, 0) + %(input_tokens)s,
		    output_tokens = COALESCE(output_tokens, 0) + %(output_tokens)s,
		    cache_hit_tokens = COALESCE(cache_hit_tokens, 0) + %(cache_hit_tokens)s,
		    estimated_conversation_tokens = COALESCE(estimated_conversation_tokens, 0) + %(estimated_conversation_tokens)s
		WHERE name = %(session)s"""
	params = {
		"input_tokens": input_tokens,
		"output_tokens": output_tokens,
		"cache_hit_tokens": cache_hit_tokens,
		"estimated_conversation_tokens": input_tokens + output_tokens,
		"session": session,
	}

	last_exc = None
	for attempt in range(3):
		try:
			frappe.db.sql(sql, params)
			frappe.db.commit()
			return
		except frappe.QueryDeadlockError as exc:
			last_exc = exc
			frappe.db.rollback()
			time.sleep(0.1 * (2 ** attempt))  # 0.1, 0.2, 0.4 s
	raise last_exc  # type: ignore[misc]


def _atomic_update_user_token_usage(usage_name: str, input_tokens: int, output_tokens: int, cache_hit_tokens: int, cost: float) -> None:
	"""Atomically increment User Token Usage counters.

	Retries on QueryDeadlockError for the same reason as
	_atomic_update_chat_session_tokens.
	"""
	sql = """UPDATE `tabUser Token Usage`
		SET total_input_tokens = COALESCE(total_input_tokens, 0) + %(input_tokens)s,
		    total_output_tokens = COALESCE(total_output_tokens, 0) + %(output_tokens)s,
		    total_cache_hit_tokens = COALESCE(total_cache_hit_tokens, 0) + %(cache_hit_tokens)s,
		    total_cost = COALESCE(total_cost, 0) + %(cost)s,
		    last_updated = %(last_updated)s
		WHERE name = %(name)s"""
	params = {
		"input_tokens": input_tokens,
		"output_tokens": output_tokens,
		"cache_hit_tokens": cache_hit_tokens,
		"cost": cost,
		"last_updated": frappe.utils.now_datetime(),
		"name": usage_name,
	}

	last_exc = None
	for attempt in range(3):
		try:
			frappe.db.sql(sql, params)
			frappe.db.commit()
			return
		except frappe.QueryDeadlockError as exc:
			last_exc = exc
			frappe.db.rollback()
			time.sleep(0.1 * (2 ** attempt))
	raise last_exc  # type: ignore[misc]


def _resolve_effective_rates(session_name: str) -> dict:
	"""Resolve effective pricing rates (provider base + per-user override).

	Returns a dict with user, usage_name, and effective rates so callers
	can apply the 3-tier cost formula without repeating DB lookups.
	"""
	session_doc = frappe.get_doc("Chat Session", session_name)
	provider = frappe.get_doc("LLM Provider", session_doc.llm_provider)

	from ph_agent.ph_agent.doctype.user_token_usage.user_token_usage import UserTokenUsage

	usage_name = UserTokenUsage.get_or_create_for_user(session_doc.user)
	usage_doc = frappe.get_doc("User Token Usage", usage_name)

	return {
		"user": session_doc.user,
		"usage_name": usage_name,
		"eff_input": float(provider.input_cost_per_1m_tokens or 0) + float(usage_doc.input_cost_over_per_1m or 0),
		"eff_output": float(provider.output_cost_per_1m_tokens or 0) + float(usage_doc.output_cost_over_per_1m or 0),
		"eff_cache": float(provider.cache_hit_cost_per_1m_tokens or 0) + float(usage_doc.cache_hit_cost_over_per_1m or 0),
	}


def _calculate_cost_from_rates(input_tokens: int, output_tokens: int, cache_hit_tokens: int, rates: dict) -> float:
	"""Calculate EUR cost from effective rates dict (from _resolve_effective_rates).

	3-tier formula: cache_miss * eff_input + cache_hit * eff_cache + output * eff_output, all / 1_000_000.
	"""
	cache_miss = max(0, input_tokens - cache_hit_tokens)
	return (
		cache_miss * rates["eff_input"]
		+ cache_hit_tokens * rates["eff_cache"]
		+ output_tokens * rates["eff_output"]
	) / 1_000_000
