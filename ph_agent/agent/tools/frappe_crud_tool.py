"""
Frappe CRUD tool for PH Agent.

Allows the AI to create, update, and delete Frappe/ERPNext records.
Complements the read-only query_frappe_data tool with write operations.
All operations include security validation and permission checks.
"""

import json
import logging
from typing import Annotated, Optional
from pydantic import Field
from agent_framework import tool, FunctionInvocationContext
from frappe.utils.file_manager import add_attachments

logger = logging.getLogger(__name__)

# DocTypes that are NEVER allowed to be created/updated/deleted by the AI
BLOCKED_DOCTYPES = {
	"User", "__Auth", "Session Defaults", "DefaultValue",
	"DocType", "DocField", "DocPerm", "Property Setter",
	"Custom Field", "Workflow", "Workflow State",
	"Workflow Action Master", "Server Script",
	"File", "Prepared Report",
	# Skill Registry — must use the dedicated create_skill tool
	"Skill Registry", "Skill Resource", "Skill Script",
}

# DocTypes that can only be read (never written) by the AI
READ_ONLY_DOCTYPES = {
	"ToDo", "Note", "Comment",
	"Activity Log", "Version", "Route History",
	"Error Log", "Error Snapshot",
}

# DocTypes that are explicitly allowed for write operations
ALLOWED_WRITE_DOCTYPES = {
	# CRM
	"Customer", "Lead", "Opportunity", "Contact", "Address",
	# Sales
	"Quotation", "Sales Order", "Delivery Note", "Sales Invoice",
	# Buying
	"Supplier", "Purchase Order", "Purchase Receipt", "Purchase Invoice",
	# Items
	"Item", "Item Price", "Product Bundle",
	# Accounting
	"Journal Entry", "Payment Entry", "Payment Request",
	# Stock
	"Warehouse", "Stock Entry",
	# Projects
	"Project", "Task",
	# HR
	"Employee",
	# Support
	"Issue",
	# Communication
	"Communication",
}

# When set to True, only ALLOWED_WRITE_DOCTYPES can be created/updated/deleted
# When False, any DocType not in BLOCKED_DOCTYPES or READ_ONLY_DOCTYPES is allowed
RESTRICT_TO_ALLOWED = True


def _validate_write_doctype(doctype: str) -> Optional[str]:
	"""Validate that a DocType can be written to. Returns error message or None."""
	if doctype in BLOCKED_DOCTYPES:
		return (
			f"Access denied: '{doctype}' is a restricted DocType and "
			f"cannot be created, updated, or deleted through the AI."
		)
	if doctype in READ_ONLY_DOCTYPES:
		return (
			f"Access denied: '{doctype}' is a read-only DocType. "
			f"You can query it but not create, update, or delete records."
		)
	if RESTRICT_TO_ALLOWED and doctype not in ALLOWED_WRITE_DOCTYPES:
		return (
			f"Access denied: '{doctype}' is not in the allowed list of writable DocTypes. "
			f"Allowed DocTypes for write operations: {', '.join(sorted(ALLOWED_WRITE_DOCTYPES))}."
		)
	return None


def _check_cancellation(ctx: FunctionInvocationContext | None) -> bool:
	"""Check if the operation was cancelled. Returns True if cancelled."""
	if ctx and ctx.kwargs:
		session_name = ctx.kwargs.get("session_name", "")
		if session_name:
			import frappe
			cancel_key = f"ph_agent:cancel:{session_name}"
			if frappe.cache().get_value(cancel_key):
				return True
	return False


def _get_context_info(ctx: FunctionInvocationContext | None) -> str:
	"""Get user/session context info string."""
	if ctx and ctx.kwargs:
		user = ctx.kwargs.get("user", "")
		session = ctx.kwargs.get("session_name", "")
		if user or session:
			return f" [User: {user}, Session: {session}]"
	return ""


# ─────────────────────────────────────────────────────────
#  CREATE RECORD TOOL
# ─────────────────────────────────────────────────────────


@tool(
	name="create_frappe_record",
	description=(
		"Create a new record in Frappe/ERPNext. "
		"Supply the DocType name and field values as a JSON object. "
		"Returns the created record name and details. "
		f"Allowed DocTypes: {', '.join(sorted(ALLOWED_WRITE_DOCTYPES))}."
	),
)
def create_frappe_record_tool(
	doctype: Annotated[
		str,
		Field(description="The DocType to create a record in (e.g. 'Customer', 'Sales Order', 'Item')"),
	],
	field_values: Annotated[
		str,
		Field(description="JSON object of field names and values to set on the new record, "
						  "e.g. '{\"customer_name\": \"Acme Corp\", \"customer_type\": \"Company\", "
						  "\"territory\": \"United States\"}'"),
	],
	ctx: FunctionInvocationContext = None,
) -> str:
	"""
	Create a new record in Frappe/ERPNext.

	Args:
		doctype: The DocType to create a record in.
		field_values: JSON string of field names and values.
		ctx: Function invocation context (injected by framework).

	Returns:
		Formatted result with the created record name and details.
	"""
	import frappe
	from frappe.exceptions import ValidationError

	context_info = _get_context_info(ctx)

	# Validate DocType
	error = _validate_write_doctype(doctype)
	if error:
		return f"{error}{context_info}"

	# Check cancellation
	if _check_cancellation(ctx):
		return "Operation cancelled."

	# Parse field values
	try:
		fields = json.loads(field_values)
	except json.JSONDecodeError as e:
		return f"Error: Invalid JSON in field_values: {e}{context_info}"

	if not isinstance(fields, dict):
		return f"Error: field_values must be a JSON object (dict), got {type(fields).__name__}{context_info}"

	try:
		doc = frappe.get_doc({"doctype": doctype, **fields})
		doc.insert(ignore_permissions=False)

		result = {
			"name": doc.name,
			"doctype": doctype,
			"creation": str(doc.creation) if hasattr(doc, 'creation') else None,
			"owner": doc.owner if hasattr(doc, 'owner') else None,
			"fields": fields,
		}

		# Include the title if it exists
		if hasattr(doc, 'title'):
			result["title"] = doc.title

		# For named DocTypes, include the naming series result
		if hasattr(doc, 'naming_series'):
			result["naming_series"] = doc.naming_series

		frappe.db.commit()

		summary = f"✅ Successfully created {doctype}: **{doc.name}**"
		return summary + "\n\n```json\n" + json.dumps(result, indent=2, default=str) + "\n```"

	except frappe.PermissionError:
		frappe.db.rollback()
		return f"Error: You don't have permission to create {doctype}.{context_info}"
	except ValidationError as e:
		frappe.db.rollback()
		return f"Validation error creating {doctype}: {e}{context_info}"
	except frappe.DuplicateEntryError as e:
		frappe.db.rollback()
		return f"Duplicate entry error: {e}{context_info}"
	except Exception as e:
		frappe.db.rollback()
		logger.exception("Error creating %s", doctype)
		return f"Error creating {doctype}: {e}{context_info}"


# ─────────────────────────────────────────────────────────
#  UPDATE RECORD TOOL
# ─────────────────────────────────────────────────────────


@tool(
	name="update_frappe_record",
	description=(
		"Update an existing record in Frappe/ERPNext. "
		"Supply the DocType, record name, and field values to update as a JSON object. "
		"Returns the updated record details. "
		f"Allowed DocTypes: {', '.join(sorted(ALLOWED_WRITE_DOCTYPES))}."
	),
)
def update_frappe_record_tool(
	doctype: Annotated[
		str,
		Field(description="The DocType of the record to update (e.g. 'Customer', 'Sales Order', 'Item')"),
	],
	name: Annotated[
		str,
		Field(description="The name (ID) of the record to update"),
	],
	field_values: Annotated[
		str,
		Field(description="JSON object of field names and new values, "
						  "e.g. '{\"customer_name\": \"New Name\", \"customer_type\": \"Individual\"}'"),
	],
	ctx: FunctionInvocationContext = None,
) -> str:
	"""
	Update an existing record in Frappe/ERPNext.

	Args:
		doctype: The DocType of the record.
		name: The record name/ID to update.
		field_values: JSON string of field names and new values.
		ctx: Function invocation context (injected by framework).

	Returns:
		Formatted result with the updated record details.
	"""
	import frappe
	from frappe.exceptions import ValidationError

	context_info = _get_context_info(ctx)

	# Validate DocType
	error = _validate_write_doctype(doctype)
	if error:
		return f"{error}{context_info}"

	# Check cancellation
	if _check_cancellation(ctx):
		return "Operation cancelled."

	# Parse field values
	try:
		fields = json.loads(field_values)
	except json.JSONDecodeError as e:
		return f"Error: Invalid JSON in field_values: {e}{context_info}"

	if not isinstance(fields, dict):
		return f"Error: field_values must be a JSON object (dict), got {type(fields).__name__}{context_info}"

	try:
		doc = frappe.get_doc(doctype, name)

		# Track what was changed
		changed = {}
		for key, value in fields.items():
			if hasattr(doc, key):
				old_value = getattr(doc, key)
				setattr(doc, key, value)
				changed[key] = {"old": old_value, "new": value}
			else:
				changed[key] = {"error": f"Field '{key}' does not exist on {doctype}"}

		doc.save(ignore_permissions=False)
		frappe.db.commit()

		result = {
			"name": doc.name,
			"doctype": doctype,
			"modified": str(doc.modified) if hasattr(doc, 'modified') else None,
			"modified_by": doc.modified_by if hasattr(doc, 'modified_by') else None,
			"updated_fields": changed,
		}

		summary = f"✅ Successfully updated {doctype}: **{doc.name}**"
		return summary + "\n\n```json\n" + json.dumps(result, indent=2, default=str) + "\n```"

	except frappe.DoesNotExistError:
		return f"Error: {doctype} '{name}' does not exist.{context_info}"
	except frappe.PermissionError:
		frappe.db.rollback()
		return f"Error: You don't have permission to update {doctype} '{name}'.{context_info}"
	except ValidationError as e:
		frappe.db.rollback()
		return f"Validation error updating {doctype} '{name}': {e}{context_info}"
	except Exception as e:
		frappe.db.rollback()
		logger.exception("Error updating %s '%s'", doctype, name)
		return f"Error updating {doctype} '{name}': {e}{context_info}"


# ─────────────────────────────────────────────────────────
#  DELETE RECORD TOOL
# ─────────────────────────────────────────────────────────


@tool(
	name="delete_frappe_record",
	description=(
		"Delete (cancel/archive) a record in Frappe/ERPNext. "
		"USE WITH CAUTION — only use when the user explicitly asks to delete or remove a record. "
		"Many Frappe records support 'Cancel' instead of hard-delete. "
		f"Allowed DocTypes: {', '.join(sorted(ALLOWED_WRITE_DOCTYPES))}."
	),
)
def delete_frappe_record_tool(
	doctype: Annotated[
		str,
		Field(description="The DocType of the record to delete (e.g. 'Customer', 'Lead', 'Item')"),
	],
	name: Annotated[
		str,
		Field(description="The name (ID) of the record to delete"),
	],
	permanent: Annotated[
		bool,
		Field(description="If True, permanently delete the record. If False (default), attempt to cancel/archive instead."),
	] = False,
	ctx: FunctionInvocationContext = None,
) -> str:
	"""
	Delete or cancel a record in Frappe/ERPNext.

	Args:
		doctype: The DocType of the record.
		name: The record name/ID to delete.
		permanent: If True, hard-delete. If False, attempt soft-delete/cancel.
		ctx: Function invocation context (injected by framework).

	Returns:
		Formatted result with deletion status.
	"""
	import frappe

	context_info = _get_context_info(ctx)

	# Validate DocType
	error = _validate_write_doctype(doctype)
	if error:
		return f"{error}{context_info}"

	# Check cancellation
	if _check_cancellation(ctx):
		return "Operation cancelled."

	try:
		# Try to find the record first
		if not frappe.db.exists(doctype, name):
			return f"Error: {doctype} '{name}' does not exist.{context_info}"

		if not permanent:
			# Attempt to cancel if the DocType supports it
			try:
				doc = frappe.get_doc(doctype, name)
				if hasattr(doc, 'docstatus') and doc.docstatus == 1:
					# Submitted document — cancel it
					doc.cancel()
					frappe.db.commit()
					return (
						f"✅ {doctype} **{name}** has been **cancelled** (submitted documents "
						f"cannot be hard-deleted; cancellation reverses its impact).{context_info}"
					)
			except frappe.PermissionError:
				frappe.db.rollback()
				return f"Error: You don't have permission to cancel {doctype} '{name}'.{context_info}"
			except Exception as e:
				frappe.db.rollback()
				logger.warning("Cancel failed for %s '%s': %s", doctype, name, e)
				# Fall through to delete

		# Hard delete
		try:
			frappe.delete_doc(doctype, name, ignore_permissions=False)
			frappe.db.commit()
			action = "permanently deleted" if permanent else "deleted"
			return f"✅ {doctype} **{name}** has been {action}.{context_info}"
		except frappe.PermissionError:
			frappe.db.rollback()
			return f"Error: You don't have permission to delete {doctype} '{name}'.{context_info}"
		except frappe.LinkExistsError as e:
			frappe.db.rollback()
			return (
				f"Error: {doctype} '{name}' is linked to other records and cannot be deleted. "
				f"Details: {e}{context_info}"
			)

	except frappe.DoesNotExistError:
		return f"Error: {doctype} '{name}' does not exist.{context_info}"
	except Exception as e:
		frappe.db.rollback()
		logger.exception("Error deleting %s '%s'", doctype, name)
		return f"Error deleting {doctype} '{name}': {e}{context_info}"


# ─────────────────────────────────────────────────────────
#  RUN CUSTOM DOCTYPE METHOD TOOL
# ─────────────────────────────────────────────────────────


@tool(
	name="run_frappe_method",
	description=(
		"Run a whitelisted Frappe/ERPNext method by dotted path. "
		"Use this to call specific Frappe API endpoints or controller methods "
		"that aren't covered by the standard CRUD tools. "
		"For example: 'frappe.client.get_list', 'frappe.client.insert', "
		"'erpnext.selling.doctype.customer.customer.get_customer_details'. "
		"Blocks access to system-level methods. USE WITH CAUTION for methods "
		"that modify data — prefer the dedicated CRUD tools when possible."
	),
)
def run_frappe_method_tool(
	method_path: Annotated[
		str,
		Field(description="Dotted path to a Frappe whitelisted method, e.g. 'frappe.client.get_list'"),
	],
	arguments: Annotated[
		Optional[str],
		Field(description="JSON object of keyword arguments to pass to the method, "
						  "e.g. '{\"doctype\": \"Customer\", \"fields\": [\"name\"]}'"),
	] = None,
	ctx: FunctionInvocationContext = None,
) -> str:
	"""
	Run a whitelisted Frappe/ERPNext method.

	Args:
		method_path: Dotted path to the method.
		arguments: JSON kwargs object.
		ctx: Function invocation context (injected by framework).

	Returns:
		Formatted method result.
	"""
	import frappe

	context_info = _get_context_info(ctx)

	# Check cancellation
	if _check_cancellation(ctx):
		return "Operation cancelled."

	# Security: block dangerous methods
	blocked_prefixes = [
		"frappe.delete_doc", "frappe.destroy", "frappe.db.sql",
		"frappe.db.commit", "frappe.db.rollback",
		"frappe.reload_doc", "frappe.cache",
		"os.", "subprocess", "sys.",
		"__builtins__", "eval", "exec", "compile",
		"shutil", "pathlib",
	]
	for prefix in blocked_prefixes:
		if method_path.startswith(prefix) or method_path == prefix:
			return f"Access denied: method '{method_path}' is blocked for security reasons.{context_info}"

	# Parse arguments
	kwargs = {}
	if arguments:
		try:
			kwargs = json.loads(arguments)
		except json.JSONDecodeError as e:
			return f"Error: Invalid JSON in arguments: {e}{context_info}"

		if not isinstance(kwargs, dict):
			return f"Error: arguments must be a JSON object (dict), got {type(kwargs).__name__}{context_info}"

	try:
		result = frappe.call(method_path, **kwargs)
		formatted = json.dumps(result, indent=2, default=str) if result is not None else "No result returned."
		return f"✅ Method `{method_path}` executed successfully:\n\n```json\n{formatted}\n```"

	except frappe.PermissionError:
		return f"Error: Permission denied for method '{method_path}'.{context_info}"
	except frappe.DoesNotExistError as e:
		return f"Error: {e}{context_info}"
	except Exception as e:
		logger.exception("Error calling method '%s'", method_path)
		return f"Error calling method '{method_path}': {e}{context_info}"


# ─────────────────────────────────────────────────────────
#  ATTACH FILES TO RECORD TOOL
# ─────────────────────────────────────────────────────────


@tool(
	name="attach_files_to_record",
	description=(
		"OPTIONAL — Attach uploaded files (PDFs, images, documents) to a specific record "
		"AFTER creating it. Use this when: (1) you created a record from a file "
		"(e.g., an invoice from a PDF) and should link the source file to the new record, "
		"or (2) the user explicitly asked to attach files. "
		"Do NOT use when: you're just answering a question, the file content was only used "
		"as reference, the record doesn't exist yet, or the user didn't request file attachment."
	),
)
def attach_files_to_record_tool(
	target_doctype: Annotated[
		str,
		Field(description="The DocType to attach files to (e.g. 'Sales Invoice', 'Customer', 'Item')"),
	],
	target_name: Annotated[
		str,
		Field(description="The record name/ID to attach files to"),
	],
	file_names: Annotated[
		str,
		Field(description="JSON array of existing File doc names, e.g. '[\"File-abc123\"]'. "
						  "Only include files relevant to this record."),
	],
	ctx: FunctionInvocationContext = None,
) -> str:
	"""
	Attach existing uploaded files to a Frappe/ERPNext record.

	Uses Frappe's native add_attachments() to link existing File documents
	to a target record. The files must already exist in the File doctype
	(typically uploaded via the chat interface).

	Args:
		target_doctype: The DocType to attach files to.
		target_name: The record name/ID to attach files to.
		file_names: JSON array of existing File document names.
		ctx: Function invocation context (injected by framework).

	Returns:
		Formatted result with list of attached files and their details.
	"""
	import frappe

	context_info = _get_context_info(ctx)

	# Check cancellation
	if _check_cancellation(ctx):
		return "Operation cancelled."

	# Validate target record exists
	try:
		if not frappe.db.exists(target_doctype, target_name):
			return f"Error: {target_doctype} '{target_name}' does not exist.{context_info}"
	except frappe.PermissionError:
		return f"Error: Permission denied — cannot check existence of {target_doctype}.{context_info}"
	except Exception as e:
		return f"Error checking record existence: {e}{context_info}"

	# Parse file_names JSON
	try:
		files_list = json.loads(file_names)
	except json.JSONDecodeError as e:
		return f"Error: Invalid JSON in file_names: {e}{context_info}"

	if not isinstance(files_list, list):
		return f"Error: file_names must be a JSON array, got {type(files_list).__name__}{context_info}"

	if not files_list:
		return f"Error: file_names list is empty. Provide at least one file name.{context_info}"

	# Validate each file exists
	valid_files = []
	errors = []
	for fname in files_list:
		if not isinstance(fname, str) or not fname.strip():
			errors.append(f"Invalid file name: '{fname}'")
			continue
		try:
			if frappe.db.exists("File", fname.strip()):
				valid_files.append(fname.strip())
			else:
				errors.append(f"File '{fname}' does not exist")
		except Exception as e:
			errors.append(f"Error checking file '{fname}': {e}")

	if not valid_files:
		error_detail = "; ".join(errors) if errors else "No valid files provided."
		return f"Error: No valid files to attach.{context_info}\nDetails: {error_detail}"

	# Attach files to the record
	try:
		add_attachments(
			doctype=target_doctype,
			name=target_name,
			attachments=valid_files,
		)
		frappe.db.commit()

		# Build result with details about each attached file
		attached_details = []
		for fname in valid_files:
			try:
				file_doc = frappe.get_doc("File", fname)
				attached_details.append({
					"file_name": file_doc.file_name,
					"file_url": file_doc.file_url,
					"new_file_name": fname,
				})
			except Exception:
				attached_details.append({"file_name": fname})

		result = {
			"target_doctype": target_doctype,
			"target_name": target_name,
			"attached_files": attached_details,
		}

		summary = (
			f"✅ Successfully attached {len(valid_files)} file(s) to "
			f"**{target_doctype}: {target_name}**"
		)

		if errors:
			summary += f"\n\n⚠️ {len(errors)} file(s) could not be attached: {'; '.join(errors)}"

		return summary + "\n\n```json\n" + json.dumps(result, indent=2, default=str) + "\n```"

	except frappe.PermissionError:
		frappe.db.rollback()
		return f"Error: You don't have permission to attach files to {target_doctype} '{target_name}'.{context_info}"
	except Exception as e:
		frappe.db.rollback()
		logger.exception("Error attaching files to %s '%s'", target_doctype, target_name)
		return f"Error attaching files to {target_doctype} '{target_name}': {e}{context_info}"
