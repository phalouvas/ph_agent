"""
Migration hook to seed sample skills and create the private/files/skills/ directory.

On ``after_migrate``:
1. Ensures the site-scoped ``private/files/skills/`` directory exists.
2. Copies sample skill files from the app's version-controlled directory to
   the site-scoped directory (idempotent — skips any that already exist).
3. Seeds a sample Skill Registry record if none exist.

All operations are idempotent and safe to run repeatedly.
"""

import shutil
from pathlib import Path

import frappe

# Sample skills to seed as Skill Registry records
SAMPLE_SKILLS = [
	{
		"doctype": "Skill Registry",
		"skill_name": "frappe-data-query",
		"is_enabled": 1,
		"description": "Query Frappe/ERPNext data safely using the Frappe ORM. "
		"Knows about DocType conventions, standard filters, and best practices "
		"for reading data without causing side effects.",
		"content": (
			"# Frappe Data Query\n\n"
			"A skill for reading data from Frappe/ERPNext using the Frappe ORM.\n\n"
			"## When to use\n\n"
			"- The user asks to look up data in the system (e.g. customers, sales orders, items).\n"
			"- The user asks about record counts or statistics.\n"
			"- The user wants to verify data that exists in the system.\n\n"
			"## How to query\n\n"
			"### Single record by name\n\n"
			"```python\n"
			"doc = frappe.get_doc('DocType', 'name')\n"
			"```\n\n"
			"### List of records\n\n"
			"```python\n"
			"records = frappe.get_all(\n"
			'    "DocType",\n'
			'    filters={"field": "value"},\n'
			'    fields=["name", "field1", "field2"],\n'
			'    order_by="creation desc",\n'
			'    limit=20,\n'
			")\n"
			"```\n\n"
			"### Count records\n\n"
			"```python\n"
			"count = frappe.db.count('DocType', filters={'field': 'value'})\n"
			"```\n\n"
			"### Raw SQL (use only when ORM is insufficient)\n\n"
			"```python\n"
			"data = frappe.db.sql('''\n"
			"    SELECT name, field FROM `tabDocType`\n"
			"    WHERE field = %(value)s\n"
			"''', {'value': 'some_value'}, as_dict=True)\n"
			"```\n\n"
			"## Safety rules\n\n"
			"- **Never** use `frappe.delete_doc`, `frappe.set_value` in query context.\n"
			"- **Never** run INSERT/UPDATE/DELETE via raw SQL.\n"
			"- Always parameterize raw SQL (use `%(name)s` placeholders).\n"
			"- Limit results to 100 unless the user explicitly requests more.\n"
			"- Do NOT query sensitive DocTypes (User, __Auth) unless the user is System Manager.\n\n"
			"## Examples\n\n"
			"### Get open sales orders\n\n"
			"```python\n"
			"orders = frappe.get_all(\n"
			'    "Sales Order",\n'
			'    filters={"status": "To Deliver and Bill", "docstatus": 1},\n'
			'    fields=["name", "customer", "total", "transaction_date"],\n'
			'    order_by="transaction_date desc",\n'
			'    limit=20,\n'
			")\n"
			"```\n\n"
			"### Count customers by territory\n\n"
			"```python\n"
			"count = frappe.db.count('Customer', filters={'territory': 'India'})\n"
			"```"
		),
		"resources": [
			{
				"resource_name": "doc_types",
				"description": "Quick reference table of common Frappe/ERPNext DocTypes with key fields and filters.",
				"resource_type": "Static Text",
				"content": (
					"# Common Frappe/ERPNext DocTypes\n\n"
					"A quick reference for commonly queried DocTypes in ERPNext.\n\n"
					"## Sales & Customers\n\n"
					"| DocType | Key Fields | Common Filters |\n"
					"|---------|-----------|----------------|\n"
					"| Customer | `name`, `customer_name`, `territory`, `customer_group`, `customer_type` | `disabled: 0` |\n"
					"| Sales Order | `name`, `customer`, `total`, `status`, `transaction_date` | `docstatus: 1`, `status: \"To Deliver and Bill\"` |\n"
					"| Delivery Note | `name`, `customer`, `total`, `posting_date` | `docstatus: 1` |\n"
					"| Sales Invoice | `name`, `customer`, `grand_total`, `posting_date`, `outstanding_amount` | `docstatus: 1`, `outstanding_amount: [\">\", 0]` |\n\n"
					"## Purchasing & Inventory\n\n"
					"| DocType | Key Fields | Common Filters |\n"
					"|---------|-----------|----------------|\n"
					"| Supplier | `name`, `supplier_name`, `supplier_group` | `disabled: 0` |\n"
					"| Purchase Order | `name`, `supplier`, `total`, `status`, `transaction_date` | `docstatus: 1` |\n"
					"| Item | `name`, `item_name`, `item_group`, `stock_uom` | `disabled: 0`, `has_variants: 0` |\n"
					"| Stock Ledger Entry | `item_code`, `warehouse`, `actual_qty`, `posting_date` | `item_code: \"...\"`, `warehouse: \"...\"` |\n\n"
					"## Accounting\n\n"
					"| DocType | Key Fields | Common Filters |\n"
					"|---------|-----------|----------------|\n"
					"| Account | `name`, `account_name`, `account_type`, `parent_account` | `is_group: 0` |\n"
					"| Journal Entry | `name`, `posting_date`, `total_debit`, `total_credit` | `docstatus: 1` |\n"
					"| GL Entry | `account`, `debit`, `credit`, `posting_date`, `voucher_type` | `is_cancelled: 0` |\n\n"
					"## HR & Payroll\n\n"
					"| DocType | Key Fields | Common Filters |\n"
					"|---------|-----------|----------------|\n"
					"| Employee | `name`, `employee_name`, `department`, `designation`, `status` | `status: \"Active\"` |\n"
					"| Attendance | `employee`, `attendance_date`, `status`, `working_hours` | `docstatus: 1` |\n"
					"| Salary Slip | `employee`, `start_date`, `end_date`, `net_pay` | `docstatus: 1` |\n\n"
					"## Manufacturing\n\n"
					"| DocType | Key Fields | Common Filters |\n"
					"|---------|-----------|----------------|\n"
					"| BOM | `item`, `quantity`, `is_active`, `is_default` | `is_active: 1`, `docstatus: 1` |\n"
					"| Work Order | `production_item`, `qty`, `status`, `planned_start_date` | `docstatus: 1` |\n\n"
					"## Projects & Support\n\n"
					"| DocType | Key Fields | Common Filters |\n"
					"|---------|-----------|----------------|\n"
					"| Project | `name`, `project_name`, `status`, `expected_start_date` | `status: \"Open\"` |\n"
					"| Task | `subject`, `project`, `status`, `exp_start_date` | `status: [\"!=\", \"Cancelled\"]` |\n"
					"| Issue | `subject`, `customer`, `status`, `priority` | `status: [\"!=\", \"Closed\"]` |"
				),
			},
		],
		"scripts": [
			{
				"script_name": "query_generator",
				"description": "Generates a Frappe ORM query string from doctype, fields, filters, and limit parameters.",
				"script_type": "File Reference",
				"file": "/private/files/skills/frappe-data-query/scripts/query_generator.py",
			},
		],
	},
]


def after_migrate():
	"""Run after all migrations are complete.

	Ensures the site's ``private/files/skills/`` directory exists, copies
	sample skill files from the app repo, and seeds sample Skill Registry records.
	"""
	_ensure_skills_directory()
	_copy_sample_skill_files()
	_seed_sample_skills()


def _ensure_skills_directory():
	"""Create the site-scoped private/files/skills/ directory if it doesn't exist."""
	skills_dir = Path(frappe.get_site_path("private", "files", "skills"))
	skills_dir.mkdir(parents=True, exist_ok=True)
	frappe.logger().info("Ensured skills directory exists: %s", skills_dir)


def _copy_sample_skill_files():
	"""Copy sample skill files from the app repo to the site directory.

	Only copies subdirectories that don't already exist in the destination.
	"""
	source_dir = Path(frappe.get_app_path("ph_agent", "private", "files", "skills"))
	dest_dir = Path(frappe.get_site_path("private", "files", "skills"))

	if not source_dir.exists():
		frappe.logger().info("No sample skills source directory at %s, skipping file copy.", source_dir)
		return

	for skill_subdir in source_dir.iterdir():
		if not skill_subdir.is_dir():
			continue

		dest_subdir = dest_dir / skill_subdir.name
		if dest_subdir.exists():
			frappe.logger().info("Sample skill '%s' already exists at destination, skipping.", skill_subdir.name)
			continue

		try:
			shutil.copytree(str(skill_subdir), str(dest_subdir), dirs_exist_ok=True)
			frappe.logger().info("Copied sample skill '%s' to %s", skill_subdir.name, dest_subdir)
		except Exception as e:
			frappe.logger().error("Failed to copy sample skill '%s': %s", skill_subdir.name, str(e))


def _seed_sample_skills():
	"""Seed sample Skill Registry records if they don't already exist.

	Guards against the DocType table not existing yet (first migration run).
	Uses a raw SQL check for table existence because ``table_exists()`` can
	return False for tables created outside of Frappe's sync mechanism
	(e.g. when DocType JSON was imported during an aborted migration).
	"""
	try:
		frappe.db.sql("SELECT COUNT(*) FROM `tabSkill Registry` LIMIT 1")
	except Exception:
		frappe.logger().info(
			"'tabSkill Registry' table does not exist yet, skipping Skill Registry seeding."
		)
		return

	for record in SAMPLE_SKILLS:
		skill_name = record["skill_name"]

		try:
			if frappe.db.exists("Skill Registry", skill_name):
				frappe.logger().info("Skill Registry record '%s' already exists, skipping.", skill_name)
				continue
		except Exception as e:
			frappe.logger().error("Error checking Skill Registry '%s': %s", skill_name, str(e))
			continue

		try:
			doc = frappe.get_doc(record)
			doc.insert(ignore_permissions=True)
			frappe.db.commit()
			frappe.logger().info("Created Skill Registry record: %s", skill_name)
		except Exception as e:
			frappe.db.rollback()
			frappe.logger().error("Failed to create Skill Registry record '%s': %s", skill_name, str(e))
