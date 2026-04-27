"""
Migration patch to migrate existing data to the persona-based architecture.

For each user who has Chat Sessions or User Memory records:
1. Creates a "Default" persona for that user
2. Assigns all existing Chat Sessions to that Default persona
3. Assigns all existing User Memory records to that Default persona
4. Copies existing User Preference data into the Default persona's preferences JSON field
5. Sets the Default persona as is_default=1

This patch runs in [post_model_sync] — after DocTypes have been migrated
and the new Persona DocType and persona fields exist.
"""

import frappe


def execute():
    """Migrate existing data to persona-based scoping."""
    _create_default_personas()
    _assign_sessions_to_default_persona()
    _assign_memories_to_default_persona()
    _migrate_user_preferences()


def _get_users_with_data() -> set[str]:
    """Get all users who have existing Chat Sessions or User Memory records."""
    users: set[str] = set()

    session_users = frappe.get_all(
        "Chat Session",
        fields=["distinct user"],
        pluck="user",
    )
    users.update(session_users)

    memory_users = frappe.get_all(
        "User Memory",
        fields=["distinct user"],
        pluck="user",
    )
    users.update(memory_users)

    return users


def _create_default_personas() -> None:
    """Create a 'Default' persona for each user who has existing data."""
    users = _get_users_with_data()

    for user in users:
        if not user:
            continue

        # Skip if user already has a persona
        existing = frappe.get_all(
            "Persona",
            filters={"user": user, "persona_name": "Default"},
            limit=1,
        )
        if existing:
            continue

        try:
            doc = frappe.get_doc({
                "doctype": "Persona",
                "user": user,
                "persona_name": "Default",
                "is_default": 1,
                "icon": "user",
                "color": "#4f72b8",
            })
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception as e:
            frappe.log_error(
                title="Persona Migration Error",
                message=f"Failed to create Default persona for user {user}: {e}",
            )


def _assign_sessions_to_default_persona() -> None:
    """Assign all Chat Sessions without a persona to the user's Default persona."""
    sessions = frappe.get_all(
        "Chat Session",
        filters={"persona": ["is", "not set"]},
        fields=["name", "user"],
    )

    for session in sessions:
        if not session.user:
            continue

        default_persona = frappe.get_all(
            "Persona",
            filters={"user": session.user, "persona_name": "Default"},
            pluck="name",
            limit=1,
        )
        if not default_persona:
            continue

        try:
            frappe.db.set_value(
                "Chat Session",
                session.name,
                "persona",
                default_persona[0],
            )
        except Exception as e:
            frappe.log_error(
                title="Persona Migration Error",
                message=f"Failed to assign persona to session {session.name}: {e}",
            )

    frappe.db.commit()


def _assign_memories_to_default_persona() -> None:
    """Assign all User Memory records without a persona to the user's Default persona."""
    memories = frappe.get_all(
        "User Memory",
        filters={"persona": ["is", "not set"]},
        fields=["name", "user"],
    )

    for memory in memories:
        if not memory.user:
            continue

        default_persona = frappe.get_all(
            "Persona",
            filters={"user": memory.user, "persona_name": "Default"},
            pluck="name",
            limit=1,
        )
        if not default_persona:
            continue

        try:
            frappe.db.set_value(
                "User Memory",
                memory.name,
                "persona",
                default_persona[0],
            )
        except Exception as e:
            frappe.log_error(
                title="Persona Migration Error",
                message=f"Failed to assign persona to memory {memory.name}: {e}",
            )

    frappe.db.commit()


def _migrate_user_preferences() -> None:
    """Copy existing User Preference data into the Default persona's preferences JSON field."""
    preferences = frappe.get_all(
        "User Preference",
        fields=["user", "preferences"],
    )

    for pref in preferences:
        if not pref.user or not pref.preferences:
            continue

        default_persona = frappe.get_all(
            "Persona",
            filters={"user": pref.user, "persona_name": "Default"},
            pluck="name",
            limit=1,
        )
        if not default_persona:
            continue

        try:
            doc = frappe.get_doc("Persona", default_persona[0])
            # Only set preferences if the persona doesn't already have them
            if not doc.preferences:
                doc.preferences = pref.preferences
                doc.save(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(
                title="Persona Migration Error",
                message=f"Failed to migrate preferences for user {pref.user}: {e}",
            )

    frappe.db.commit()
