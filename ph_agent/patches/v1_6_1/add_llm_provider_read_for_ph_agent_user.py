"""
Migration patch to add read-only "PH Agent User" permission on LLM Provider.

This was missed in v1.6.0's create_ph_agent_user_role patch. Without read
access to LLM Provider, PH Agent User cannot create chat sessions because
the API needs to list/lookup available providers.

The api_key field is a Password type — Frappe automatically hides its
value from non-privileged roles in API responses, so read-only is safe.
"""

import frappe


def execute():
    """Add read-only PH Agent User permission on LLM Provider."""
    _upsert_permission("LLM Provider", "PH Agent User", {"read": 1})
    frappe.db.commit()


def _upsert_permission(doctype: str, role: str, perm_data: dict) -> bool:
    """Insert or update a single DocPerm row for a given role on a doctype."""
    existing = frappe.get_all(
        "DocPerm",
        filters={"parent": doctype, "role": role},
        fields=["name"],
        limit=1,
    )

    defaults = {
        "create": 0, "read": 0, "write": 0, "delete": 0,
        "if_owner": 0, "share": 0, "print": 0, "email": 0,
        "report": 0, "export": 0,
    }
    defaults.update(perm_data)

    if existing:
        frappe.db.set_value("DocPerm", existing[0]["name"], defaults)
        frappe.logger().info("Updated DocPerm for %s > %s", doctype, role)
        return True

    perm = frappe.get_doc({
        "doctype": "DocPerm",
        "parent": doctype,
        "parentfield": "permissions",
        "parenttype": "DocType",
        "role": role,
        **defaults,
    })
    perm.insert(ignore_permissions=True)
    frappe.logger().info("Inserted DocPerm for %s > %s", doctype, role)
    return True
