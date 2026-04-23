"""
Migration patch to seed default Tool Registry entries.

Creates the built-in tools (show_datetime, calculate) in the Tool Registry
if they don't already exist.
"""

import frappe

TOOL_REGISTRY_SEED = [
    {
        "doctype": "Tool Registry",
        "tool_name": "show_datetime",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Shows the current date and time. Useful for testing tool registration and verifying the system is working.",
        "python_function": "ph_agent.agent.tools.datetime_tool.show_datetime_tool",
        "requires_approval": 0,
    },
    {
        "doctype": "Tool Registry",
        "tool_name": "calculate",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Performs mathematical calculations. Supports basic arithmetic, percentages, and common math functions.",
        "python_function": "ph_agent.agent.tools.calculator_tool.calculate_tool",
        "requires_approval": 0,
    },
]


def execute():
    """Seed default Tool Registry entries if they don't exist."""
    for record in TOOL_REGISTRY_SEED:
        tool_name = record["tool_name"]

        # Check if already exists
        if frappe.db.exists("Tool Registry", tool_name):
            frappe.logger().info("Tool Registry entry '%s' already exists, skipping.", tool_name)
            continue

        try:
            doc = frappe.get_doc(record)
            doc.insert(ignore_permissions=True)
            frappe.logger().info("Created Tool Registry entry: %s", tool_name)
        except Exception as e:
            frappe.logger().error("Failed to create Tool Registry entry '%s': %s", tool_name, str(e))
            raise
