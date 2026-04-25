"""
Create Skill tool for PH Agent.

Allows the AI to create Skill Registry records on user request.
Skills are always created disabled (is_enabled=0) and must be
manually enabled from the Skill Registry list.
"""

from typing import Annotated, Optional
from pydantic import Field
from agent_framework import tool, FunctionInvocationContext


@tool(
    name="create_skill",
    description=(
        "Create a new Skill Registry record. Skills teach the AI about specific "
        "domains, processes, or knowledge areas. Provide the skill name (lowercase "
        "letters, numbers, and hyphens only), a description, and the skill content "
        "in Markdown format. Optionally include resources (static reference text or "
        "dynamic functions) and scripts (executable Python functions or file references). "
        "Skills are always created disabled — enable them from the Skill Registry list "
        "to make them active."
    ),
)
def create_skill_tool(
    skill_name: Annotated[
        str,
        Field(description="Unique skill name. Use only lowercase letters, numbers, and hyphens. Must not start or end with a hyphen. Max 64 characters."),
    ],
    description: Annotated[
        str,
        Field(description="Brief description of what the skill teaches. Max 1024 characters."),
    ],
    content: Annotated[
        str,
        Field(description="The skill instructions body in Markdown format. This is the knowledge/content the AI will use when the skill is active."),
    ],
    resources: Annotated[
        Optional[str],
        Field(description="Optional JSON array of resource objects. Each object: resource_name (required), description (optional), resource_type ('Static Text' or 'Dynamic Function'), content (required if Static Text), python_function (required if Dynamic Function). Example: [{\"resource_name\": \"ref_doc\", \"resource_type\": \"Static Text\", \"content\": \"# Reference\\n\\nKey information here.\"}]"),
    ] = None,
    scripts: Annotated[
        Optional[str],
        Field(description="Optional JSON array of script objects. Each object: script_name (required), description (optional), script_type ('In-Process Function' or 'File Reference'), python_function (required if In-Process Function), file (required if File Reference). Example: [{\"script_name\": \"helper\", \"script_type\": \"In-Process Function\", \"python_function\": \"module.path.function_name\"}]"),
    ] = None,
    ctx: FunctionInvocationContext = None,
) -> str:
    """
    Create a new Skill Registry record.

    Args:
        skill_name: Unique lowercase name (letters, numbers, hyphens).
        description: Brief description of the skill.
        content: Markdown skill instructions body.
        resources: Optional JSON array of resource objects.
        scripts: Optional JSON array of script objects.
        ctx: Function invocation context (injected by framework).

    Returns:
        Confirmation message with the skill name and disabled status.
    """
    import json
    import re

    import frappe

    # Import validation constants from the Skill Registry controller
    from ph_agent.ph_agent.doctype.skill_registry.skill_registry import (
        SKILL_NAME_RE,
        MAX_NAME_LENGTH,
        MAX_DESCRIPTION_LENGTH,
    )

    # Check for cancellation via context
    if ctx and ctx.kwargs:
        session_name = ctx.kwargs.get("session_name", "")
        if session_name:
            cancel_key = f"ph_agent:cancel:{session_name}"
            if frappe.cache().get_value(cancel_key):
                return "Skill creation cancelled."

    # --- Validate skill_name ---
    skill_name = skill_name.strip()
    if not skill_name:
        return "Error: skill_name is required."

    if len(skill_name) > MAX_NAME_LENGTH:
        return (
            f"Error: Skill name must be {MAX_NAME_LENGTH} characters or fewer. "
            f"'{skill_name}' is {len(skill_name)} characters."
        )

    if not SKILL_NAME_RE.match(skill_name):
        return (
            "Error: Skill name must use only lowercase letters, numbers, and hyphens, "
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

    # --- Validate content ---
    content = content.strip()
    if not content:
        return "Error: content is required."

    # --- Check for duplicate ---
    if frappe.db.exists("Skill Registry", skill_name):
        return f"Error: A skill named '{skill_name}' already exists."

    # --- Parse and validate resources ---
    parsed_resources = []
    if resources:
        try:
            parsed_resources = json.loads(resources)
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON in resources parameter: {e}"

        if not isinstance(parsed_resources, list):
            return "Error: resources must be a JSON array."

        for i, res in enumerate(parsed_resources):
            if not isinstance(res, dict):
                return f"Error: Resource at index {i} must be a JSON object."
            if "resource_name" not in res:
                return f"Error: Resource at index {i} is missing 'resource_name'."
            if "resource_type" not in res:
                return f"Error: Resource at index {i} is missing 'resource_type'."
            if res["resource_type"] not in ("Static Text", "Dynamic Function"):
                return (
                    f"Error: Resource '{res['resource_name']}' has invalid "
                    f"resource_type '{res['resource_type']}'. "
                    "Must be 'Static Text' or 'Dynamic Function'."
                )
            if res["resource_type"] == "Static Text" and not res.get("content"):
                return (
                    f"Error: Resource '{res['resource_name']}' is type 'Static Text' "
                    f"but has no 'content'."
                )
            if res["resource_type"] == "Dynamic Function" and not res.get("python_function"):
                return (
                    f"Error: Resource '{res['resource_name']}' is type 'Dynamic Function' "
                    f"but has no 'python_function'."
                )

    # --- Parse and validate scripts ---
    parsed_scripts = []
    if scripts:
        try:
            parsed_scripts = json.loads(scripts)
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON in scripts parameter: {e}"

        if not isinstance(parsed_scripts, list):
            return "Error: scripts must be a JSON array."

        for i, scr in enumerate(parsed_scripts):
            if not isinstance(scr, dict):
                return f"Error: Script at index {i} must be a JSON object."
            if "script_name" not in scr:
                return f"Error: Script at index {i} is missing 'script_name'."
            if "script_type" not in scr:
                return f"Error: Script at index {i} is missing 'script_type'."
            if scr["script_type"] not in ("In-Process Function", "File Reference"):
                return (
                    f"Error: Script '{scr['script_name']}' has invalid "
                    f"script_type '{scr['script_type']}'. "
                    "Must be 'In-Process Function' or 'File Reference'."
                )
            if scr["script_type"] == "In-Process Function" and not scr.get("python_function"):
                return (
                    f"Error: Script '{scr['script_name']}' is type 'In-Process Function' "
                    f"but has no 'python_function'."
                )
            if scr["script_type"] == "File Reference" and not scr.get("file"):
                return (
                    f"Error: Script '{scr['script_name']}' is type 'File Reference' "
                    f"but has no 'file'."
                )

    # --- Create the Skill Registry record ---
    try:
        doc_dict = {
            "doctype": "Skill Registry",
            "skill_name": skill_name,
            "is_enabled": 0,  # Always disabled by default
            "description": description,
            "content": content,
        }

        if parsed_resources:
            doc_dict["resources"] = parsed_resources

        if parsed_scripts:
            doc_dict["scripts"] = parsed_scripts

        doc = frappe.get_doc(doc_dict)
        doc.insert()  # No ignore_permissions — respects Frappe permissions
        frappe.db.commit()

        return (
            f"✅ Skill '{skill_name}' has been created (disabled). "
            f"Enable it from the Skill Registry list to make it active."
        )

    except frappe.PermissionError:
        frappe.db.rollback()
        return (
            f"Error: You don't have permission to create skills. "
            f"Only users with the System Manager role can create Skill Registry records."
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(
            f"Failed to create skill '{skill_name}': {str(e)}",
            "Create Skill Error",
        )
        return f"Error creating skill '{skill_name}': {e}"
