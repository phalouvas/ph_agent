"""
Migration patch to create the "PH Agent User" role and update all doctype
permission rules so that ph_agent features are gated behind this role.

The patch is idempotent and safe to run repeatedly.

Changes made:
1. Creates the "PH Agent User" role (if it does not already exist).
2. Updates "Chat Session" to add "PH Agent User" (create/read/write/delete if_owner).
3. Updates "Chat Message" to add "PH Agent User" (create/read if_owner).
4. Updates "Persona" to add "PH Agent User" (create/read/write/delete if_owner).
5. Updates "User Preference" to add "PH Agent User" (create/read/write/delete if_owner).
6. Updates "User Memory" to add "PH Agent User" (create/read/write/delete if_owner).
7. Updates "Saved Prompt" to add "PH Agent User" (full, if_owner).
"""

import frappe


def execute():
    """Create the PH Agent User role and update all doctype permissions."""
    _ensure_role_exists("PH Agent User")
    _update_chat_session_permissions()
    _update_chat_message_permissions()
    _update_persona_permissions()
    _update_user_preference_permissions()
    _update_user_memory_permissions()
    _update_saved_prompt_permissions()
    frappe.db.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_role_exists(role_name: str) -> None:
    """Create the role if it doesn't already exist."""
    if frappe.db.exists("Role", role_name):
        frappe.logger().info("Role '%s' already exists, skipping creation.", role_name)
        return

    role = frappe.get_doc({
        "doctype": "Role",
        "role_name": role_name,
        "desk_access": 1,
    })
    role.insert(ignore_permissions=True)
    frappe.logger().info("Created role '%s'.", role_name)


def _upsert_permission(doctype: str, role: str, perm_data: dict) -> bool:
    """Insert or update a single permission row for a given role on a doctype.

    Returns True if a row was inserted or updated, False if it already
    matched exactly.
    """
    existing = frappe.get_all(
        "DocPerm",
        filters={"parent": doctype, "role": role},
        fields=["name", "create", "read", "write", "delete", "if_owner",
                "share", "print", "email", "report", "export"],
        limit=1,
    )

    # Build the new row
    defaults = {
        "create": 0, "read": 0, "write": 0, "delete": 0,
        "if_owner": 0, "share": 0, "print": 0, "email": 0,
        "report": 0, "export": 0,
    }
    defaults.update(perm_data)

    if existing:
        row = existing[0]
        changed = any(
            defaults.get(field, 0) != row.get(field, 0)
            for field in defaults
        )
        if not changed:
            return False  # Already up-to-date
        frappe.db.set_value("DocPerm", row["name"], defaults)
        frappe.logger().info("Updated DocPerm for %s › %s", doctype, role)
        return True

    # Insert new
    perm = frappe.get_doc({
        "doctype": "DocPerm",
        "parent": doctype,
        "parentfield": "permissions",
        "parenttype": "DocType",
        "role": role,
        **defaults,
    })
    perm.insert(ignore_permissions=True)
    frappe.logger().info("Inserted DocPerm for %s › %s", doctype, role)
    return True


def _remove_permission(doctype: str, role: str) -> bool:
    """Remove the permission row for the given role on the doctype."""
    existing = frappe.get_all(
        "DocPerm",
        filters={"parent": doctype, "role": role},
        limit=1,
    )
    if not existing:
        return False
    frappe.delete_doc("DocPerm", existing[0]["name"], ignore_permissions=True)
    frappe.logger().info("Removed DocPerm for %s › %s", doctype, role)
    return True


# ---------------------------------------------------------------------------
# Per-doctype updates
# ---------------------------------------------------------------------------


def _update_chat_session_permissions() -> None:
    """Add 'PH Agent User' to Chat Session and remove the 'All' entry."""
    _remove_permission("Chat Session", "All")
    _upsert_permission("Chat Session", "PH Agent User", {
        "create": 1,
        "read": 1,
        "write": 1,
        "delete": 1,
        "if_owner": 1,
    })


def _update_chat_message_permissions() -> None:
    """Add 'PH Agent User' to Chat Message and remove the 'All' entry."""
    _remove_permission("Chat Message", "All")
    _upsert_permission("Chat Message", "PH Agent User", {
        "create": 1,
        "read": 1,
        "if_owner": 1,
    })


def _update_persona_permissions() -> None:
    """Add 'PH Agent User' to Persona (create/read/write/delete if_owner)."""
    _upsert_permission("Persona", "PH Agent User", {
        "create": 1,
        "read": 1,
        "write": 1,
        "delete": 1,
        "if_owner": 1,
    })


def _update_user_preference_permissions() -> None:
    """Add 'PH Agent User' to User Preference (create/read/write/delete if_owner)."""
    _upsert_permission("User Preference", "PH Agent User", {
        "create": 1,
        "read": 1,
        "write": 1,
        "delete": 1,
        "if_owner": 1,
    })


def _update_user_memory_permissions() -> None:
    """Replace 'All' with 'PH Agent User' on User Memory.

    'All' previously had read-only access. 'PH Agent User' gets full
    if_owner access, allowing the agent to create memories on behalf of
    the session owner.
    """
    _remove_permission("User Memory", "All")
    _upsert_permission("User Memory", "PH Agent User", {
        "create": 1,
        "read": 1,
        "write": 1,
        "delete": 1,
        "if_owner": 1,
    })


def _update_saved_prompt_permissions() -> None:
    """Replace 'All' with 'PH Agent User' on Saved Prompt.

    'All' previously had full CRUD. 'PH Agent User' gets full if_owner
    access.
    """
    _remove_permission("Saved Prompt", "All")
    _upsert_permission("Saved Prompt", "PH Agent User", {
        "create": 1,
        "read": 1,
        "write": 1,
        "delete": 1,
        "if_owner": 1,
        "email": 1,
        "print": 1,
        "report": 1,
        "export": 1,
        "share": 1,
    })
