"""
Create Tool tool for PH Agent.

Allows the AI to create Tool Registry records on user request.
Tools are always created disabled (is_enabled=0) and must be
manually enabled from the Tool Registry list.
"""

from typing import Annotated, Optional
from pydantic import Field
from agent_framework import tool, FunctionInvocationContext


@tool(
    name="create_tool",
    description=(
        "Create a new Tool Registry record. Tools extend the AI's capabilities "
        "by providing new functions it can call. Provide the tool name (lowercase "
        "letters, numbers, and hyphens only), a description, and the script type. "
        "For 'Existing Function' tools, provide the dotted Python function path. "
        "For 'Custom Script' tools, provide the Python code (must define a 'run_tool' "
        "function) and a JSON Schema describing the parameters. "
        "Tools are always created disabled — enable them from the Tool Registry list "
        "to make them active."
    ),
)
def create_tool_tool(
    tool_name: Annotated[
        str,
        Field(description="Unique tool name. Use only lowercase letters, numbers, and hyphens. Must not start or end with a hyphen. Max 140 characters."),
    ],
    description: Annotated[
        str,
        Field(description="Brief description of what the tool does. Max 2000 characters."),
    ],
    script_type: Annotated[
        str,
        Field(description="Type of script: 'Existing Function' (imports a dotted Python path) or 'Custom Script' (inline Python code with a run_tool function)."),
    ],
    python_function: Annotated[
        Optional[str],
        Field(description="Dotted Python function path (e.g., 'module.submodule.function_name'). Required when script_type is 'Existing Function'."),
    ] = None,
    custom_script: Annotated[
        Optional[str],
        Field(description="Inline Python code that defines a 'run_tool(**kwargs)' function. Required when script_type is 'Custom Script'. Must include a run_tool function as the entry point."),
    ] = None,
    parameters_json: Annotated[
        Optional[str],
        Field(description="JSON Schema describing the tool's parameters. Required when script_type is 'Custom Script'. Format: {\"type\": \"object\", \"properties\": {...}, \"required\": [...]}. Example: {\"type\": \"object\", \"properties\": {\"name\": {\"type\": \"string\", \"description\": \"The name\"}}, \"required\": [\"name\"]}"),
    ] = None,
    ctx: FunctionInvocationContext = None,
) -> str:
    """
    Create a new Tool Registry record.

    Args:
        tool_name: Unique lowercase name (letters, numbers, hyphens).
        description: Brief description of the tool.
        script_type: 'Existing Function' or 'Custom Script'.
        python_function: Dotted path for Existing Function tools.
        custom_script: Inline Python code for Custom Script tools.
        parameters_json: JSON Schema for Custom Script tool parameters.
        ctx: Function invocation context (injected by framework).

    Returns:
        Confirmation message with the tool name and disabled status.
    """
    import json

    import frappe

    # Import validation constants from the Tool Registry controller
    from ph_agent.ph_agent.doctype.tool_registry.tool_registry import (
        TOOL_NAME_RE,
        MAX_TOOL_NAME_LENGTH,
        MAX_DESCRIPTION_LENGTH,
    )

    # Check for cancellation via context
    if ctx and ctx.kwargs:
        session_name = ctx.kwargs.get("session_name", "")
        if session_name:
            cancel_key = f"ph_agent:cancel:{session_name}"
            if frappe.cache().get_value(cancel_key):
                return "Tool creation cancelled."

    # --- Validate tool_name ---
    tool_name = tool_name.strip()
    if not tool_name:
        return "Error: tool_name is required."

    if len(tool_name) > MAX_TOOL_NAME_LENGTH:
        return (
            f"Error: Tool name must be {MAX_TOOL_NAME_LENGTH} characters or fewer. "
            f"'{tool_name}' is {len(tool_name)} characters."
        )

    if not TOOL_NAME_RE.match(tool_name):
        return (
            "Error: Tool name must use only lowercase letters, numbers, and hyphens, "
            "and must not start or end with a hyphen."
        )

    # --- Validate description ---
    description = description.strip()
    if not description:
        return "Error: description is required."

    if len(description) > MAX_DESCRIPTION_LENGTH:
        return (
            f"Error: Description must be {MAX_DESCRIPTION_LENGTH} characters or fewer. "
            f"Provided description is {len(description)} characters."
        )

    # --- Validate script_type ---
    script_type = script_type.strip()
    allowed_script_types = {"Existing Function", "Custom Script"}
    if script_type not in allowed_script_types:
        return (
            f"Error: script_type must be one of: {', '.join(sorted(allowed_script_types))}. "
            f"Got '{script_type}'."
        )

    # --- Validate script_type-specific fields ---
    if script_type == "Existing Function":
        if not python_function or not python_function.strip():
            return "Error: python_function is required when script_type is 'Existing Function'."

        python_function = python_function.strip()
        # Validate dotted path format
        parts = python_function.rsplit(".", 1)
        if len(parts) != 2:
            return (
                f"Error: Invalid function path '{python_function}'. "
                "Expected format: 'module.submodule.function_name'."
            )

    elif script_type == "Custom Script":
        if not custom_script or not custom_script.strip():
            return "Error: custom_script is required when script_type is 'Custom Script'."

        custom_script = custom_script.strip()

        # Check that run_tool is defined in the script
        if "def run_tool" not in custom_script:
            return (
                "Error: Custom Script must define a function named 'run_tool' "
                "that serves as the tool entry point."
            )

        # Validate parameters_json
        if not parameters_json or not parameters_json.strip():
            return "Error: parameters_json is required when script_type is 'Custom Script'."

        parameters_json = parameters_json.strip()
        try:
            parsed_schema = json.loads(parameters_json)
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON in parameters_json: {e}"

        # Validate JSON Schema structure
        if not isinstance(parsed_schema, dict):
            return "Error: parameters_json must be a JSON object with 'type', 'properties', and 'required' fields."
        if parsed_schema.get("type") != "object":
            return "Error: parameters_json must have 'type': 'object'."
        if "properties" not in parsed_schema or not isinstance(parsed_schema["properties"], dict):
            return "Error: parameters_json must have a 'properties' field containing a JSON object."


    # --- Check for duplicate ---
    if frappe.db.exists("Tool Registry", tool_name):
        return f"Error: A tool named '{tool_name}' already exists."

    # --- Create the Tool Registry record ---
    try:
        doc_dict = {
            "doctype": "Tool Registry",
            "tool_name": tool_name,
            "is_enabled": 0,  # Always disabled by default
            "description": description,
            "script_type": script_type,
        }

        if script_type == "Existing Function":
            doc_dict["python_function"] = python_function
        elif script_type == "Custom Script":
            doc_dict["custom_script"] = custom_script
            doc_dict["parameters_json"] = parameters_json

        doc = frappe.get_doc(doc_dict)
        doc.insert()  # No ignore_permissions — respects Frappe permissions
        frappe.db.commit()

        return (
            f"✅ Tool '{tool_name}' has been created (disabled). "
            f"Enable it from the Tool Registry list to make it active."
        )

    except frappe.PermissionError:
        frappe.db.rollback()
        return (
            f"Error: You don't have permission to create tools. "
            f"Only users with the System Manager role can create Tool Registry records."
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(
            f"Failed to create tool '{tool_name}': {str(e)}",
            "Create Tool Error",
        )
        return f"Error creating tool '{tool_name}': {e}"
