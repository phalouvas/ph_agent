"""
Migration patch to fix system prompt inheritance on existing Chat Session records.

Previously, cross-session context (previous-session summaries) was injected directly
into the ``system_prompt`` field, which also caused the provider prompt to be duplicated
when a persona had inherited it.

This patch:
1. Detects sessions where the ``system_prompt`` starts with the legacy context prefix.
2. Extracts the context block into the new ``cross_session_context`` field.
3. Leaves only the clean system prompt (after the "---" separator) in ``system_prompt``.

Sessions that do not have the legacy prefix are left untouched.
"""

import frappe

_CONTEXT_PREFIX = "[Previous conversation context from recent sessions"
_SEPARATOR = "\n\n---\n\n"


def execute():
    """Split baked-in cross-session context out of system_prompt."""
    sessions = frappe.get_all(
        "Chat Session",
        filters={},
        fields=["name", "system_prompt"],
    )

    updated = 0
    for session in sessions:
        prompt = session.get("system_prompt") or ""
        if not prompt.startswith(_CONTEXT_PREFIX):
            continue

        # Split at the first separator to extract context vs. clean prompt
        if _SEPARATOR in prompt:
            context_block, clean_prompt = prompt.split(_SEPARATOR, 1)
        else:
            # The whole prompt is context (no separator means no system prompt was set)
            context_block = prompt
            clean_prompt = ""

        frappe.db.set_value(
            "Chat Session",
            session.name,
            {
                "cross_session_context": context_block,
                "system_prompt": clean_prompt,
            },
            update_modified=False,
        )
        updated += 1

    if updated:
        frappe.db.commit()

    frappe.logger().info(
        "fix_system_prompt_inheritance: migrated %d Chat Session record(s).", updated
    )
