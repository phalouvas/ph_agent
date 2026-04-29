"""
Web Search tool for PH Agent.

Allows the AI to search the web using DuckDuckGo (via the ddgs library).
Supports date filtering and domain-specific searches.
"""

from typing import Annotated, Optional
from pydantic import Field
from agent_framework import tool, FunctionInvocationContext


@tool(
    name="web_search",
    description=(
        "Search the web using DuckDuckGo. Returns titles, URLs, and snippets "
        "for matching results. Supports date filtering (day/week/month/year) "
        "and domain-specific searches. Use this to find current information "
        "that may not be available in the ERPNext database."
    ),
)
def web_search_tool(
    query: Annotated[
        str,
        Field(description="The search query to look up on the web"),
    ],
    max_results: Annotated[
        int,
        Field(description="Maximum number of search results to return (1-10)"),
    ] = 5,
    date_range: Annotated[
        Optional[str],
        Field(description="Filter results by time: 'day', 'week', 'month', or 'year'"),
    ] = None,
    domain_filter: Annotated[
        Optional[str],
        Field(description="Comma-separated list of domains to restrict results to (e.g. 'docs.erpnext.com,github.com')"),
    ] = None,
    ctx: FunctionInvocationContext = None,
) -> str:
    """
    Search the web using DuckDuckGo.

    Args:
        query: The search query.
        max_results: Max results to return (1-10, default 5).
        date_range: Optional time filter: 'day', 'week', 'month', 'year'.
        domain_filter: Optional comma-separated domains to restrict search.
        ctx: Function invocation context (injected by framework).

    Returns:
        JSON-formatted search results with title, url, snippet, and source.
    """
    import json

    # Lazy import ddgs for graceful degradation
    try:
        from ddgs import DDGS
    except ImportError:
        return (
            "Error: The 'ddgs' library is not installed. "
            "Please install it with: pip install ddgs"
        )

    # Clamp max_results
    max_results = max(1, min(max_results, 10))

    # Build effective query with domain filter
    effective_query = query
    if domain_filter:
        domains = [d.strip() for d in domain_filter.split(",") if d.strip()][:3]
        if domains:
            site_clause = " OR ".join(f"site:{d}" for d in domains)
            effective_query = f"({query}) ({site_clause})"

    # Map date_range to DDGS timelimit
    timelimit_map = {"day": "d", "week": "w", "month": "m", "year": "y"}
    timelimit = timelimit_map.get(date_range) if date_range else None

    # Check for cancellation via context
    if ctx and ctx.kwargs:
        import frappe
        session_name = ctx.kwargs.get("session_name", "")
        if session_name:
            cancel_key = f"ph_agent:cancel:{session_name}"
            if frappe.cache().get_value(cancel_key):
                return "Search cancelled."

    try:
        kwargs = {"max_results": max_results}
        if timelimit:
            kwargs["timelimit"] = timelimit

        with DDGS() as ddgs:
            raw_results = list(ddgs.text(effective_query, **kwargs))

    except Exception as exc:
        return f"Error performing web search: {exc}"

    # Normalize results
    normalized = []
    for result in raw_results or []:
        if not isinstance(result, dict):
            continue
        title = (result.get("title") or "").strip()
        url = (result.get("href") or "").strip()
        snippet = (result.get("body") or "").strip()
        if not url:
            continue
        if len(snippet) > 500:
            snippet = snippet[:500] + "..."
        normalized.append({
            "title": title or "Untitled",
            "url": url,
            "snippet": snippet,
            "source": "ddgs",
        })

    if not normalized:
        return f"No results found for '{query}'."

    result = json.dumps(normalized, indent=2, ensure_ascii=False)
    summary = f"Found {len(normalized)} result(s) for '{query}':\n\n"
    return summary + result
