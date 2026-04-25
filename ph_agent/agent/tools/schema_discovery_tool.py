"""
Frappe Schema Discovery tool for introspecting DocType schemas.

Allows the LLM to discover available DocTypes and their field structures
before querying data, bridging the "schema blindness" gap.
"""

import json
from typing import Annotated, Optional
from pydantic import Field
from agent_framework import tool, FunctionInvocationContext

import frappe
from frappe.model.meta import Meta


def _get_context_info(ctx: FunctionInvocationContext | None) -> str:
    """Get user/session context info string for error messages."""
    if ctx and ctx.kwargs:
        user = ctx.kwargs.get("user", "")
        session = ctx.kwargs.get("session_name", "")
        if user or session:
            return f" [User: {user}, Session: {session}]"
    return ""


@tool(
    name="discover_frappe_schema",
    description="Discover Frappe DocType schemas. Use 'list_doctypes' to search/filter available DocTypes by name pattern, or 'get_schema' to retrieve full field metadata (field names, types, labels, required status, link targets) for a specific DocType. Essential for understanding which DocTypes and fields exist before querying data."
)
def discover_frappe_schema_tool(
    operation: Annotated[
        str,
        Field(description="Operation to perform: 'list_doctypes' to search for DocTypes by name pattern, or 'get_schema' to get full field metadata for a specific DocType")
    ],
    doctype_pattern: Annotated[
        Optional[str],
        Field(description="DocType name pattern to search for (used with 'list_doctypes' operation). Supports SQL LIKE wildcards: '%' for any chars, '_' for single char. Example: 'Issue', '%ToDo%', 'Sales%'")
    ] = None,
    doctype: Annotated[
        Optional[str],
        Field(description="Exact DocType name to get schema for (used with 'get_schema' operation). Example: 'Issue', 'Customer', 'Sales Order'")
    ] = None,
    ctx: FunctionInvocationContext = None
) -> str:
    """
    Discover Frappe DocType schemas.
    
    Two operations:
      - list_doctypes: Search/filter DocTypes by name pattern
      - get_schema: Get full field metadata for a specific DocType
    
    Args:
        operation: 'list_doctypes' or 'get_schema'
        doctype_pattern: DocType name pattern for list_doctypes (SQL LIKE)
        doctype: Exact DocType name for get_schema
        ctx: Function invocation context (injected by framework)
        
    Returns:
        JSON string with schema information
    """
    context_str = _get_context_info(ctx)

    try:
        if operation == "list_doctypes":
            return _list_doctypes(doctype_pattern, context_str)
        elif operation == "get_schema":
            return _get_schema(doctype, context_str)
        else:
            return (
                f"Error: Unknown operation '{operation}'. "
                f"Use 'list_doctypes' to search DocTypes or 'get_schema' to inspect a DocType's fields.{context_str}"
            )
    except frappe.DoesNotExistError as e:
        return f"Error: DocType not found: {e}{context_str}"
    except frappe.PermissionError as e:
        return f"Error: Permission denied: {e}{context_str}"
    except Exception as e:
        frappe.logger().exception("Schema discovery error")
        return f"Error discovering schema: {e}{context_str}"


def _list_doctypes(pattern: str | None, context_str: str) -> str:
    """List DocTypes matching the given name pattern."""
    filters = {"istable": 0}

    if pattern:
        # Support both exact names and LIKE patterns
        if "%" in pattern or "_" in pattern:
            filters["name"] = ["like", pattern]
        else:
            filters["name"] = ["like", f"%{pattern}%"]

    doctypes = frappe.get_all(
        "DocType",
        fields=["name", "module", "is_submittable", "istable"],
        filters=filters,
        limit=50,
        order_by="name asc",
    )

    if not doctypes:
        if pattern:
            return f"No DocTypes found matching '{pattern}'. Try a broader search pattern.{context_str}"
        return f"No DocTypes found.{context_str}"

    result = {
        "operation": "list_doctypes",
        "pattern": pattern or "(all non-Table DocTypes)",
        "count": len(doctypes),
        "doctypes": [
            {
                "name": d["name"],
                "module": d["module"],
                "is_submittable": bool(d["is_submittable"]),
            }
            for d in doctypes
        ],
    }

    return json.dumps(result, indent=2)


def _get_schema(doctype: str | None, context_str: str) -> str:
    """Get full field metadata for a specific DocType."""
    if not doctype:
        return f"Error: 'doctype' parameter is required for 'get_schema' operation.{context_str}"

    if not frappe.db.exists("DocType", doctype):
        return f"Error: DocType '{doctype}' does not exist.{context_str}"

    meta: Meta = frappe.get_meta(doctype)

    fields = []
    for f in meta.fields:
        field_info = {
            "fieldname": f.fieldname,
            "label": f.label or f.fieldname,
            "fieldtype": f.fieldtype,
            "reqd": bool(f.reqd),
            "read_only": bool(f.read_only),
            "hidden": bool(f.hidden),
            "description": f.description or "",
        }

        # Type-specific extras
        if f.fieldtype == "Link" and f.options:
            field_info["target_doctype"] = f.options
        elif f.fieldtype == "Select" and f.options:
            options = [o.strip() for o in f.options.split("\n") if o.strip()]
            field_info["options"] = options
        elif f.fieldtype in ("Table", "Table MultiSelect") and f.options:
            field_info["child_doctype"] = f.options
        elif f.fieldtype == "Dynamic Link" and f.options:
            field_info["dynamic_link_field"] = f.options

        # Default values
        if f.default is not None:
            field_info["default"] = f.default

        fields.append(field_info)

    result = {
        "operation": "get_schema",
        "doctype": doctype,
        "module": meta.module or "",
        "is_submittable": bool(meta.is_submittable),
        "title_field": meta.title_field or "",
        "search_fields": meta.search_fields or "",
        "field_count": len(fields),
        "fields": fields,
    }

    return json.dumps(result, indent=2)
