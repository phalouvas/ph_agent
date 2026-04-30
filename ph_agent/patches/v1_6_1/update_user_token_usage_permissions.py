import frappe


def execute():
	"""Update User Token Usage doctype with permlevel 1 for cost override fields
	and add System Manager permlevel 1 permission row.
	"""
	frappe.reload_doc("ph_agent", "doctype", "user_token_usage")
