"""
Frappe ORM Query tool for PH Agent.

Allows the AI to query Frappe/ERPNext data safely using the Frappe ORM.
Supports get_all, get_doc, and count operations with security restrictions.
"""

from typing import Annotated, Optional
from pydantic import Field
from agent_framework import tool, FunctionInvocationContext


SENSITIVE_DOCTYPES = {"User", "__Auth", "Session Defaults", "DefaultValue"}


@tool(
    name="query_frappe_data",
    description=(
        "Query Frappe/ERPNext data using the Frappe ORM. "
        "Use this to look up records, list data, or get counts. "
        "Supports get_all (list), get_doc (single), and count operations. "
        "Always limit results to 100 unless the user asks for more."
    ),
)
def query_frappe_data_tool(
    doctype: Annotated[
        str,
        Field(description="The DocType to query (e.g. 'Customer', 'Sales Order', 'Item')"),
    ],
    operation: Annotated[
        str,
        Field(description="Type of query: 'get_all' for list, 'get_doc' for single record by name, 'count' for record count"),
    ] = "get_all",
    name: Annotated[
        Optional[str],
        Field(description="Record name to fetch when operation='get_doc'. Not used for other operations."),
    ] = None,
    filters: Annotated[
        Optional[str],
        Field(description="JSON string of filters, e.g. '{\"status\": \"Open\", \"docstatus\": 1}'"),
    ] = None,
    fields: Annotated[
        Optional[str],
        Field(description="Comma-separated field names to return, e.g. 'name,customer,total'. Defaults to 'name' if not specified."),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Maximum number of records to return (max 100)"),
    ] = 20,
    order_by: Annotated[
        Optional[str],
        Field(description="Sort order, e.g. 'creation desc' or 'modified asc'"),
    ] = "creation desc",
    ctx: FunctionInvocationContext = None,
) -> str:
    """
    Query Frappe/ERPNext data safely using the Frappe ORM.

    Args:
        doctype: The DocType to query.
        operation: 'get_all' (list), 'get_doc' (single record), or 'count'.
        name: Record name (only for operation='get_doc').
        filters: JSON string of filters.
        fields: Comma-separated field names.
        limit: Max records (1-100).
        order_by: Sort order.
        ctx: Function invocation context (injected by framework).

    Returns:
        Formatted query results as a string.
    """
    import frappe
    import json

    # Security: block sensitive DocTypes
    if doctype in SENSITIVE_DOCTYPES:
        user = frappe.session.user
        if user != "Administrator":
            return f"Access denied: '{doctype}' is a sensitive DocType. Only Administrator can query it."

    # Validate limit
    limit = max(1, min(limit, 100))

    # Parse filters
    parsed_filters = None
    if filters:
        try:
            parsed_filters = json.loads(filters)
        except json.JSONDecodeError:
            return f"Error: Invalid JSON in filters parameter: {filters}"

    # Parse fields
    parsed_fields = None
    if fields:
        parsed_fields = [f.strip() for f in fields.split(",") if f.strip()]

    # Also check for cancellation via context
    if ctx and ctx.kwargs:
        session_name = ctx.kwargs.get("session_name", "")
        if session_name:
            cancel_key = f"ph_agent:cancel:{session_name}"
            if frappe.cache().get_value(cancel_key):
                return "Query cancelled."

    try:
        if operation == "count":
            count = frappe.db.count(doctype, filters=parsed_filters)
            return f"Count of {doctype}: {count}"

        elif operation == "get_doc":
            if not name:
                return "Error: 'name' parameter is required for operation='get_doc'."
            doc = frappe.get_doc(doctype, name)
            # Return key fields only (exclude large text fields)
            result = {k: v for k, v in doc.as_dict().items()
                      if k not in ("_user_tags", "_comments", "_assign", "_liked_by", "__runlinks", "doctype")}
            return json.dumps(result, indent=2, default=str, sort_keys=False)

        else:  # get_all (default)
            if not parsed_fields:
                parsed_fields = ["name"]

            records = frappe.get_all(
                doctype,
                filters=parsed_filters,
                fields=parsed_fields,
                order_by=order_by,
                limit=limit,
            )
            if not records:
                return f"No {doctype} records found matching the given filters."

            result = json.dumps(records, indent=2, default=str)
            summary = f"Found {len(records)} {doctype} record(s):\n\n"
            return summary + result

    except frappe.DoesNotExistError:
        return f"Error: {doctype} '{name}' does not exist."
    except frappe.PermissionError:
        return f"Error: You don't have permission to query {doctype}."
    except frappe.ValidationError as e:
        return f"Error querying {doctype}: {e}"
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Frappe query tool error: %s", str(e))
        return f"Error querying {doctype}: {e}"
