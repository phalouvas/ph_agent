---
name: frappe-data-query
description: "Query Frappe/ERPNext data safely using the Frappe ORM. Knows about DocType conventions, standard filters, and best practices for reading data without causing side effects."
---

# Frappe Data Query

A skill for reading data from Frappe/ERPNext using the Frappe ORM.

## When to use

- The user asks to look up data in the system (e.g. customers, sales orders, items).
- The user asks about record counts or statistics.
- The user wants to verify data that exists in the system.

## How to query

### Single record by name

```python
doc = frappe.get_doc("DocType", "name")
```

### List of records

```python
records = frappe.get_all(
    "DocType",
    filters={"field": "value"},
    fields=["name", "field1", "field2"],
    order_by="creation desc",
    limit=20,
)
```

### Count records

```python
count = frappe.db.count("DocType", filters={"field": "value"})
```

### Raw SQL (use only when ORM is insufficient)

```python
data = frappe.db.sql("""
    SELECT name, field FROM `tabDocType`
    WHERE field = %(value)s
""", {"value": "some_value"}, as_dict=True)
```

## Safety rules

- **Never** use `frappe.delete_doc`, `frappe.set_value` in query context.
- **Never** run INSERT/UPDATE/DELETE via raw SQL.
- Always parameterize raw SQL (use `%(name)s` placeholders).
- Limit results to 100 unless the user explicitly requests more.
- Do NOT query sensitive DocTypes (User, __Auth) unless the user is System Manager.

## Examples

### Get open sales orders

```python
orders = frappe.get_all(
    "Sales Order",
    filters={"status": "To Deliver and Bill", "docstatus": 1},
    fields=["name", "customer", "total", "transaction_date"],
    order_by="transaction_date desc",
    limit=20,
)
```

### Count customers by territory

```python
count = frappe.db.count("Customer", filters={"territory": "India"})
```
