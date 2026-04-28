"""
Migration patch to backfill the tool_group field on existing Tool Registry records.

The tool_group field was added in phase 1 of the Tool Token Reduction feature.
This patch assigns the correct group to each known built-in tool and falls back
to "General" for any remaining records that still have no group.
"""

import frappe

# Mapping of tool_name → tool_group for all built-in tools
TOOL_GROUP_MAP = {
    # General
    "show_datetime": "General",
    "calculate": "General",
    "circle_calculator": "General",
    # ERPNext
    "query_frappe_data": "ERPNext",
    "create_frappe_record": "ERPNext",
    "update_frappe_record": "ERPNext",
    "delete_frappe_record": "ERPNext",
    "run_frappe_method": "ERPNext",
    "discover_frappe_schema": "ERPNext",
    # Financial
    "yahoo_finance": "Financial",
    "exchange_rate": "Financial",
    "sec_edgar": "Financial",
    # Web
    "web_search": "Web",
    "wikipedia": "Web",
    "stack_exchange": "Web",
    "reddit": "Web",
    "hacker_news": "Web",
    # Meta
    "create_skill": "Meta",
    "create_tool": "Meta",
}


def execute():
    """Backfill tool_group on existing Tool Registry records."""
    for tool_name, group in TOOL_GROUP_MAP.items():
        if frappe.db.exists("Tool Registry", tool_name):
            frappe.db.set_value(
                "Tool Registry", tool_name, "tool_group", group,
                update_modified=False,
            )
            frappe.logger().info(
                "Set tool_group='%s' on Tool Registry '%s'.", group, tool_name
            )

    # Fallback: any tool not in the map gets 'General'
    frappe.db.sql(
        "UPDATE `tabTool Registry` SET tool_group='General' WHERE tool_group IS NULL OR tool_group=''"
    )
