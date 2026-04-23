# Common Frappe/ERPNext DocTypes

A quick reference for commonly queried DocTypes in ERPNext.

## Sales & Customers

| DocType | Key Fields | Common Filters |
|---------|-----------|----------------|
| Customer | `name`, `customer_name`, `territory`, `customer_group`, `customer_type` | `disabled: 0` |
| Sales Order | `name`, `customer`, `total`, `status`, `transaction_date` | `docstatus: 1`, `status: "To Deliver and Bill"` |
| Delivery Note | `name`, `customer`, `total`, `posting_date` | `docstatus: 1` |
| Sales Invoice | `name`, `customer`, `grand_total`, `posting_date`, `outstanding_amount` | `docstatus: 1`, `outstanding_amount: [">", 0]` |

## Purchasing & Inventory

| DocType | Key Fields | Common Filters |
|---------|-----------|----------------|
| Supplier | `name`, `supplier_name`, `supplier_group` | `disabled: 0` |
| Purchase Order | `name`, `supplier`, `total`, `status`, `transaction_date` | `docstatus: 1` |
| Item | `name`, `item_name`, `item_group`, `stock_uom` | `disabled: 0`, `has_variants: 0` |
| Stock Ledger Entry | `item_code`, `warehouse`, `actual_qty`, `posting_date` | `item_code: "..."`, `warehouse: "..."` |

## Accounting

| DocType | Key Fields | Common Filters |
|---------|-----------|----------------|
| Account | `name`, `account_name`, `account_type`, `parent_account` | `is_group: 0` |
| Journal Entry | `name`, `posting_date`, `total_debit`, `total_credit` | `docstatus: 1` |
| GL Entry | `account`, `debit`, `credit`, `posting_date`, `voucher_type` | `is_cancelled: 0` |

## HR & Payroll

| DocType | Key Fields | Common Filters |
|---------|-----------|----------------|
| Employee | `name`, `employee_name`, `department`, `designation`, `status` | `status: "Active"` |
| Attendance | `employee`, `attendance_date`, `status`, `working_hours` | `docstatus: 1` |
| Salary Slip | `employee`, `start_date`, `end_date`, `net_pay` | `docstatus: 1` |

## Manufacturing

| DocType | Key Fields | Common Filters |
|---------|-----------|----------------|
| BOM | `item`, `quantity`, `is_active`, `is_default` | `is_active: 1`, `docstatus: 1` |
| Work Order | `production_item`, `qty`, `status`, `planned_start_date` | `docstatus: 1` |

## Projects & Support

| DocType | Key Fields | Common Filters |
|---------|-----------|----------------|
| Project | `name`, `project_name`, `status`, `expected_start_date` | `status: "Open"` |
| Task | `subject`, `project`, `status`, `exp_start_date` | `status: ["!=", "Cancelled"]` |
| Issue | `subject`, `customer`, `status`, `priority` | `status: ["!=", "Closed"]` |
