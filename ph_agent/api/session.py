"""
API for programmatic Chat Session creation with document reference support.

Provides a whitelisted ``create_session`` method that lets any app create a
Chat Session linked to a specific document (e.g. a portfolio, security, or
sales order).  The reference fields (``reference_doctype`` + ``reference_name``)
are set at creation time and are read-only thereafter.
"""

import frappe


@frappe.whitelist()
def create_session(persona, reference_doctype=None, reference_name=None):
	"""Create a new Chat Session linked to a document reference.

	Args:
		persona: Persona name to associate with this session (required).
		reference_doctype: Optional DocType to link this session to.
		reference_name: Optional document name to link this session to.

	Returns:
		dict with ``session`` (name), ``title``, and ``llm_provider`` keys.
	"""
	# Validate persona
	if not frappe.db.exists("Persona", persona):
		frappe.throw(frappe._("Persona {0} not found.").format(persona))

	persona_user = frappe.db.get_value("Persona", persona, "user")
	if persona_user != frappe.session.user:
		frappe.throw(frappe._("Persona {0} does not belong to you.").format(persona))

	# Resolve default LLM Provider
	default = frappe.get_list(
		"LLM Provider",
		filters={"is_default": 1, "is_enabled": 1},
		pluck="name",
		limit=1,
	)
	if not default:
		frappe.throw(frappe._("No default LLM Provider configured. Please set up a provider first."))
	provider_name = default[0]

	# Build session title from reference document if provided
	title = "New Chat"
	if reference_doctype and reference_name:
		try:
			meta = frappe.get_meta(reference_doctype)
			title_field = meta.get("title_field") or "name"
			title_value = frappe.db.get_value(reference_doctype, reference_name, title_field)
			if title_value:
				title = f"{title_value} — New Chat"
		except Exception:
			# Fall back to default title
			pass

	session = frappe.get_doc(
		{
			"doctype": "Chat Session",
			"title": title,
			"persona": persona,
			"user": frappe.session.user,
			"llm_provider": provider_name,
			"status": "Open",
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
		}
	)
	session.insert(ignore_permissions=False)
	frappe.db.commit()

	return {
		"session": session.name,
		"title": session.title,
		"llm_provider": session.llm_provider,
		"reference_doctype": reference_doctype,
		"reference_name": reference_name,
	}
