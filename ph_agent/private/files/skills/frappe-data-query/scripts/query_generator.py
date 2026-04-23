#!/usr/bin/env python3
"""
Query Generator script for the frappe-data-query skill.

Generates a Frappe ORM query based on command-line parameters.
Usage:
    python query_generator.py --doctype "Sales Order" --fields "name,customer,total" --filters '{"status":"To Deliver and Bill"}' --limit 20
"""

import argparse
import json
import sys


def generate_query(doctype: str, fields: str, filters: str | None = None, limit: int = 20) -> str:
	"""
	Generate a Frappe ORM query string.

	Args:
		doctype: The DocType to query.
		fields: Comma-separated list of field names.
		filters: JSON string of filters.
		limit: Maximum number of records to return.

	Returns:
		A formatted Python code string.
	"""
	field_list = [f'"{f.strip()}"' for f in fields.split(",")]
	fields_str = ",\n        ".join(field_list)

	if filters:
		try:
			filter_dict = json.loads(filters)
			filters_str = json.dumps(filter_dict, indent=8)
		except json.JSONDecodeError:
			filters_str = filters
	else:
		filters_str = "{}"

	query = f"""records = frappe.get_all(
    "{doctype}",
    filters={filters_str},
    fields=[
        {fields_str}
    ],
    order_by="creation desc",
    limit={limit},
)"""
	return query


def main():
	parser = argparse.ArgumentParser(description="Generate a Frappe ORM query")
	parser.add_argument("--doctype", required=True, help="DocType to query")
	parser.add_argument("--fields", required=True, help="Comma-separated field names")
	parser.add_argument("--filters", default=None, help='JSON filters string')
	parser.add_argument("--limit", type=int, default=20, help="Max records (default: 20)")

	args = parser.parse_args()

	try:
		query = generate_query(args.doctype, args.fields, args.filters, args.limit)
		print(query)
	except Exception as e:
		print(f"Error: {e}", file=sys.stderr)
		sys.exit(1)


if __name__ == "__main__":
	main()
