"""
Stack Exchange search tool for PH Agent.

Searches questions and answers across Stack Overflow and the Stack Exchange
network using the public Stack Exchange API. No API key required (10k calls/day
throttle applies).
"""

from typing import Annotated, Optional
from pydantic import Field
from agent_framework import tool, FunctionInvocationContext


@tool(
    name="stack_exchange",
    description=(
        "Search questions and answers across Stack Overflow and the Stack Exchange "
        "network. Returns question titles, scores, answer counts, accepted answer "
        "excerpts, and URLs. Supports filtering by tags and site. No API key required."
    ),
)
def stack_exchange_tool(
    query: Annotated[
        str,
        Field(description="Search query to find questions (e.g., 'Python async/await', 'SQL optimization')"),
    ],
    site: Annotated[
        str,
        Field(description="Stack Exchange site to search (e.g., 'stackoverflow', 'serverfault', 'superuser', 'askubuntu')"),
    ] = "stackoverflow",
    tags: Annotated[
        Optional[str],
        Field(description="Semicolon-separated tags to filter by (e.g., 'python;sql' or 'javascript;react')"),
    ] = None,
    max_results: Annotated[
        int,
        Field(description="Maximum number of results to return (1-10)"),
    ] = 5,
    ctx: FunctionInvocationContext = None,
) -> str:
    """
    Search Stack Exchange sites for questions and answers.

    Args:
        query: Search query.
        site: Stack Exchange site (default: 'stackoverflow').
        tags: Optional semicolon-separated tags to filter by.
        max_results: Max results (1-10, default 5).
        ctx: Function invocation context (injected by framework).

    Returns:
        JSON-formatted search results with question details.
    """
    import json

    # Check for cancellation via context
    if ctx and ctx.kwargs:
        import frappe
        session_name = ctx.kwargs.get("session_name", "")
        if session_name:
            cancel_key = f"ph_agent:cancel:{session_name}"
            if frappe.cache().get_value(cancel_key):
                return "Stack Exchange search cancelled."

    try:
        import requests
    except ImportError:
        return "Error: The 'requests' library is required but not available."

    max_results = max(1, min(max_results, 10))

    # Build API parameters
    params = {
        "order": "desc",
        "sort": "relevance",
        "intitle": query,
        "pagesize": max_results,
        "site": site,
        "filter": "withbody",  # Include answer body excerpts
    }

    if tags:
        # Stack Exchange API uses semicolons for tag filtering
        params["tagged"] = tags

    try:
        resp = requests.get(
            "https://api.stackexchange.com/2.3/search",
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        import frappe
        frappe.log_error(
            f"Stack Exchange search error for '{query}' on '{site}': {str(exc)}",
            "Stack Exchange Error",
        )
        return f"Error searching Stack Exchange: {exc}"

    if data.get("error"):
        error_info = data["error"]
        return (
            f"Stack Exchange API error: {error_info.get('message', 'Unknown error')} "
            f"(type: {error_info.get('type', '')})"
        )

    items = data.get("items", [])
    if not items:
        return json.dumps({
            "query": query,
            "site": site,
            "result": "not_found",
            "message": f"No questions found for '{query}' on {site}.",
        }, indent=2, ensure_ascii=False)

    results = []
    for item in items[:max_results]:
        accepted_answer_id = item.get("accepted_answer_id")
        accepted_excerpt = ""

        # Fetch accepted answer excerpt if available
        if accepted_answer_id:
            try:
                ans_resp = requests.get(
                    f"https://api.stackexchange.com/2.3/questions/{item['question_id']}/answers",
                    params={
                        "order": "desc",
                        "sort": "votes",
                        "site": site,
                        "pagesize": 1,
                        "filter": "withbody",
                    },
                    timeout=10,
                )
                if ans_resp.ok:
                    ans_data = ans_resp.json()
                    ans_items = ans_data.get("items", [])
                    if ans_items:
                        body = ans_items[0].get("body", "")
                        # Strip HTML tags for excerpt
                        import re
                        body_text = re.sub(r"<[^>]+>", "", body)
                        accepted_excerpt = body_text[:300]
                        if len(body_text) > 300:
                            accepted_excerpt += "..."
            except Exception:
                pass  # Non-critical, skip excerpt

        result = {
            "title": item.get("title", ""),
            "score": item.get("score", 0),
            "answer_count": item.get("answer_count", 0),
            "is_answered": item.get("is_answered", False),
            "has_accepted_answer": accepted_answer_id is not None,
            "accepted_answer_excerpt": accepted_excerpt,
            "view_count": item.get("view_count", 0),
            "tags": item.get("tags", []),
            "creation_date": item.get("creation_date", 0),
            "url": item.get("link", ""),
        }
        results.append(result)

    return json.dumps({
        "query": query,
        "site": site,
        "count": len(results),
        "has_more": data.get("has_more", False),
        "results": results,
    }, indent=2, ensure_ascii=False)
