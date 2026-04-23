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
    {
        "doctype": "Tool Registry",
        "tool_name": "circle_calculator",
        "is_enabled": 1,
        "script_type": "Custom Script",
        "description": "Calculate the area and circumference of a circle given its radius. Demonstrates the Custom Script feature.",
        "custom_script": "import math\n\ndef run_tool(radius, unit=\"meters\", ctx=None):\n    \"\"\"\n    Calculate the area and circumference of a circle given its radius.\n\n    Parameters:\n        radius (float): The radius of the circle (required).\n        unit (str): Unit of measurement (default: \"meters\").\n        ctx: Function invocation context (injected by the framework).\n\n    Returns:\n        A formatted string with the area and circumference.\n    \"\"\"\n    area = math.pi * radius ** 2\n    circumference = 2 * math.pi * radius\n\n    context_info = \"\"\n    if ctx and hasattr(ctx, \"kwargs\"):\n        user = ctx.kwargs.get(\"user\", \"\")\n        session = ctx.kwargs.get(\"session_name\", \"\")\n        if user or session:\n            context_info = f\" [User: {user}, Session: {session}]\"\n\n    return (\n        f\"Circle (radius={radius} {unit}): \"\n        f\"Area = {area:.2f} sq. {unit}, \"\n        f\"Circumference = {circumference:.2f} {unit}{context_info}\"\n    )\n",
        "parameters_json": "{\n  \"type\": \"object\",\n  \"properties\": {\n    \"radius\": {\n      \"type\": \"number\",\n      \"description\": \"The radius of the circle\"\n    },\n    \"unit\": {\n      \"type\": \"string\",\n      \"description\": \"Unit of measurement (e.g., meters, feet)\"\n    }\n  },\n  \"required\": [\"radius\"]\n}",
        "requires_approval": 0,
    },
    {
        "doctype": "Tool Registry",
        "tool_name": "query_frappe_data",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Query Frappe/ERPNext data using the Frappe ORM. Can list records (get_all), fetch a single record (get_doc), or count records (count). Supports filters, field selection, sorting, and limiting. Always limits to 100 records max. Blocks sensitive DocTypes (User, __Auth) for non-Administrator users.",
        "python_function": "ph_agent.agent.tools.frappe_query_tool.query_frappe_data_tool",
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
