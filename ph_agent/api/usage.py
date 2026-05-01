import frappe
from ph_agent.ph_agent.doctype.user_token_usage.user_token_usage import UserTokenUsage


@frappe.whitelist()
def get_user_usage(user: str | None = None) -> dict:
	"""Get token usage and cost summary for a user.

	PH Agent User role can only view their own usage.
	System Manager can view any user's usage.

	Args:
		user: Frappe User name. Defaults to the current session user.

	Returns:
		dict with keys: total_input_tokens, total_output_tokens, total_cost,
		currency, input_cost_over_per_1m, output_cost_over_per_1m,
		cache_hit_cost_over_per_1m.
	"""
	if not user:
		user = frappe.session.user

	# PH Agent User can only view their own usage
	if not frappe.has_permission("User Token Usage", "write"):
		user = frappe.session.user

	# Ensure the record exists
	UserTokenUsage.get_or_create_for_user(user)

	usage = frappe.get_doc("User Token Usage", user)

	return {
		"total_input_tokens": usage.total_input_tokens or 0,
		"total_output_tokens": usage.total_output_tokens or 0,
		"total_cache_hit_tokens": usage.total_cache_hit_tokens or 0,
		"total_cost": usage.total_cost or 0,
		"currency": "EUR",
		"input_cost_over_per_1m": usage.input_cost_over_per_1m or 0,
		"output_cost_over_per_1m": usage.output_cost_over_per_1m or 0,
		"cache_hit_cost_over_per_1m": usage.cache_hit_cost_over_per_1m or 0,
	}
