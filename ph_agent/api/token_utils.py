"""Helper for atomic token counter updates.

Uses raw SQL UPDATE with COALESCE to avoid read-then-write races.
"""

import frappe


def _atomic_update_chat_session_tokens(session: str, input_tokens: int, output_tokens: int, cache_hit_tokens: int) -> None:
	"""Atomically increment Chat Session token counters."""
	frappe.db.sql(
		"""UPDATE `tabChat Session`
		SET input_tokens = COALESCE(input_tokens, 0) + %(input_tokens)s,
		    output_tokens = COALESCE(output_tokens, 0) + %(output_tokens)s,
		    cache_hit_tokens = COALESCE(cache_hit_tokens, 0) + %(cache_hit_tokens)s,
		    estimated_conversation_tokens = COALESCE(estimated_conversation_tokens, 0) + %(estimated_conversation_tokens)s
		WHERE name = %(session)s""",
		{
			"input_tokens": input_tokens,
			"output_tokens": output_tokens,
			"cache_hit_tokens": cache_hit_tokens,
			"estimated_conversation_tokens": input_tokens + output_tokens,
			"session": session,
		},
	)
	frappe.db.commit()


def _atomic_update_user_token_usage(usage_name: str, input_tokens: int, output_tokens: int, cache_hit_tokens: int, cost: float) -> None:
	"""Atomically increment User Token Usage counters."""
	frappe.db.sql(
		"""UPDATE `tabUser Token Usage`
		SET total_input_tokens = COALESCE(total_input_tokens, 0) + %(input_tokens)s,
		    total_output_tokens = COALESCE(total_output_tokens, 0) + %(output_tokens)s,
		    total_cache_hit_tokens = COALESCE(total_cache_hit_tokens, 0) + %(cache_hit_tokens)s,
		    total_cost = COALESCE(total_cost, 0) + %(cost)s,
		    last_updated = %(last_updated)s
		WHERE name = %(name)s""",
		{
			"input_tokens": input_tokens,
			"output_tokens": output_tokens,
			"cache_hit_tokens": cache_hit_tokens,
			"cost": cost,
			"last_updated": frappe.utils.now_datetime(),
			"name": usage_name,
		},
	)
	frappe.db.commit()
