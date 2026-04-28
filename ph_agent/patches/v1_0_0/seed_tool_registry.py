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
    {
        "doctype": "Tool Registry",
        "tool_name": "create_frappe_record",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Create a new record in Frappe/ERPNext. Supply the DocType name and field values as a JSON object. Returns the created record name and details. Allowed DocTypes include: Customer, Lead, Opportunity, Contact, Address, Quotation, Sales Order, Item, Supplier, Purchase Order, Project, Task, Issue, and more.",
        "python_function": "ph_agent.agent.tools.frappe_crud_tool.create_frappe_record_tool",
        "requires_approval": 0,
    },
    {
        "doctype": "Tool Registry",
        "tool_name": "update_frappe_record",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Update an existing record in Frappe/ERPNext. Supply the DocType, record name, and field values as a JSON object. Returns the updated record details.",
        "python_function": "ph_agent.agent.tools.frappe_crud_tool.update_frappe_record_tool",
        "requires_approval": 0,
    },
    {
        "doctype": "Tool Registry",
        "tool_name": "delete_frappe_record",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Delete or cancel a record in Frappe/ERPNext. USE WITH CAUTION — only use when the user explicitly asks to delete or remove a record. Supports cancellation (soft-delete for submitted docs) and permanent deletion.",
        "python_function": "ph_agent.agent.tools.frappe_crud_tool.delete_frappe_record_tool",
        "requires_approval": 0,
    },
    {
        "doctype": "Tool Registry",
        "tool_name": "run_frappe_method",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Run a whitelisted Frappe/ERPNext method by dotted path. Use for calling specific Frappe API endpoints or controller methods not covered by standard CRUD tools. Blocks system-level and dangerous methods. Prefer dedicated CRUD tools when possible.",
        "python_function": "ph_agent.agent.tools.frappe_crud_tool.run_frappe_method_tool",
        "requires_approval": 0,
    },
    {
        "doctype": "Tool Registry",
        "tool_name": "discover_frappe_schema",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Discover Frappe DocType schemas. Use 'list_doctypes' to search/filter available DocTypes by name pattern, or 'get_schema' to retrieve full field metadata (field names, types, labels, required status, link targets) for a specific DocType. Essential for understanding which DocTypes and fields exist before querying data.",
        "python_function": "ph_agent.agent.tools.schema_discovery_tool.discover_frappe_schema_tool",
        "requires_approval": 0,
    },
    {
        "doctype": "Tool Registry",
        "tool_name": "web_search",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Search the web using DuckDuckGo. Returns titles, URLs, and snippets for matching results. Supports date filtering (day/week/month/year) and domain-specific searches. Use this to find current information that may not be available in the ERPNext database.",
        "python_function": "ph_agent.agent.tools.web_search_tool.web_search_tool",
        "requires_approval": 0,
    },
    {
        "doctype": "Tool Registry",
        "tool_name": "create_skill",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Create a new Skill Registry record. Skills teach the AI about specific domains, processes, or knowledge areas. Skills are always created disabled (is_enabled=0) — enable them from the Skill Registry list to make them active. Provide skill_name (lowercase, hyphens, 64 chars max), description (1024 chars max), markdown content, and optional resources/scripts as JSON arrays.",
        "python_function": "ph_agent.agent.tools.create_skill_tool.create_skill_tool",
        "requires_approval": 0,
    },
    {
        "doctype": "Tool Registry",
        "tool_name": "create_tool",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Create a new Tool Registry record. Tools extend the AI's capabilities by providing new functions it can call. Provide tool_name (lowercase, hyphens, 140 chars max), description (2000 chars max), script_type ('Existing Function' or 'Custom Script'), and conditional fields. Tools are always created disabled (is_enabled=0) — enable them from the Tool Registry list to make them active.",
        "python_function": "ph_agent.agent.tools.create_tool_tool.create_tool_tool",
        "requires_approval": 0,
    },
    {
        "doctype": "Tool Registry",
        "tool_name": "wikipedia",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Fetch clean, structured article content from Wikipedia. Returns article summaries, key facts, and handles disambiguation pages gracefully. Supports multiple languages (default: English). Use this for general knowledge, definitions, explanations, and background information.",
        "python_function": "ph_agent.agent.tools.wikipedia_tool.wikipedia_tool",
        "requires_approval": 0,
    },
    {
        "doctype": "Tool Registry",
        "tool_name": "yahoo_finance",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Fetch stock quotes, historical prices, company information, financial statements, dividends, and analyst recommendations from Yahoo Finance. Supports operations: quote (current price), history (price history), info (company overview), financials (income statement), dividends (dividend history), and recommendations (analyst ratings). Requires: pip install yfinance.",
        "python_function": "ph_agent.agent.tools.yahoo_finance_tool.yahoo_finance_tool",
        "requires_approval": 0,
    },
    {
        "doctype": "Tool Registry",
        "tool_name": "exchange_rate",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Fetch current currency exchange rates from the European Central Bank. Supports 30+ currencies including USD, GBP, JPY, CHF, AUD, CAD, CNY, INR, BRL, and more. Can return all rates for a base currency or convert a specific amount between two currencies. Rates are updated once per working day by the ECB.",
        "python_function": "ph_agent.agent.tools.exchange_rate_tool.exchange_rate_tool",
        "requires_approval": 0,
    },
    {
        "doctype": "Tool Registry",
        "tool_name": "sec_edgar",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Look up company CIK numbers and SEC filing metadata using the SEC's public EDGAR API. Supports searching for a company by name to find its CIK number, and fetching the latest filings (10-K, 10-Q, 8-K, etc.) for a company by CIK. No API key required.",
        "python_function": "ph_agent.agent.tools.sec_edgar_tool.sec_edgar_tool",
        "requires_approval": 0,
    },
    {
        "doctype": "Tool Registry",
        "tool_name": "stack_exchange",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Search questions and answers across Stack Overflow and the Stack Exchange network. Returns question titles, scores, answer counts, accepted answer excerpts, and URLs. Supports filtering by tags and site (stackoverflow, serverfault, superuser, askubuntu, etc.). No API key required.",
        "python_function": "ph_agent.agent.tools.stack_exchange_tool.stack_exchange_tool",
        "requires_approval": 0,
    },
    {
        "doctype": "Tool Registry",
        "tool_name": "reddit",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Search Reddit for posts, comments, and trending topics. Can search across all of Reddit or within a specific subreddit. Supports operations: search (find posts by query), hot (hot/trending posts), and top (top posts by time period). No API key required.",
        "python_function": "ph_agent.agent.tools.reddit_tool.reddit_tool",
        "requires_approval": 0,
    },
    {
        "doctype": "Tool Registry",
        "tool_name": "hacker_news",
        "is_enabled": 1,
        "script_type": "Existing Function",
        "description": "Fetch stories, comments, and trending topics from Hacker News. Supports operations: top_stories (current top stories), new_stories (latest submissions), best_stories (highest-rated recent stories), and search (find stories by keyword). No API key required.",
        "python_function": "ph_agent.agent.tools.hacker_news_tool.hacker_news_tool",
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
