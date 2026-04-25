"""
Wikipedia search tool for PH Agent.

Fetches clean, structured article content from the Wikipedia REST API.
Supports multiple languages and handles disambiguation pages gracefully.
"""

from typing import Annotated, Optional
from pydantic import Field
from agent_framework import tool, FunctionInvocationContext


@tool(
    name="wikipedia",
    description=(
        "Fetch clean, structured article content from Wikipedia. Returns article "
        "summaries, key facts, and handles disambiguation pages gracefully. "
        "Supports multiple languages (default: English). Use this for general "
        "knowledge, definitions, explanations, and background information."
    ),
)
def wikipedia_tool(
    query: Annotated[
        str,
        Field(description="The topic or article title to look up on Wikipedia"),
    ],
    lang: Annotated[
        str,
        Field(description="Wikipedia language code (e.g., 'en', 'de', 'fr', 'es', 'ja')"),
    ] = "en",
    ctx: FunctionInvocationContext = None,
) -> str:
    """
    Search Wikipedia and return article content.

    Args:
        query: The topic or article title to look up.
        lang: Wikipedia language code (default: 'en').
        ctx: Function invocation context (injected by framework).

    Returns:
        JSON-formatted article content with title, summary, and URL.
    """
    import json

    # Check for cancellation via context
    if ctx and ctx.kwargs:
        import frappe
        session_name = ctx.kwargs.get("session_name", "")
        if session_name:
            cancel_key = f"ph_agent:cancel:{session_name}"
            if frappe.cache().get_value(cancel_key):
                return "Wikipedia search cancelled."

    try:
        import requests
    except ImportError:
        return "Error: The 'requests' library is required but not available."

    # Step 1: Search for the page
    search_url = f"https://{lang}.wikipedia.org/api/rest_v1/search/page"
    try:
        search_resp = requests.get(
            search_url,
            params={"q": query, "limit": 3},
            timeout=15,
        )
        search_resp.raise_for_status()
        search_data = search_resp.json()
    except Exception as exc:
        import frappe
        frappe.log_error(
            f"Wikipedia search error for '{query}' (lang={lang}): {str(exc)}",
            "Wikipedia Search Error",
        )
        return f"Error searching Wikipedia: {exc}"

    pages = search_data.get("pages", [])
    if not pages:
        return json.dumps({
            "query": query,
            "lang": lang,
            "result": "not_found",
            "message": f"No Wikipedia articles found for '{query}'.",
        }, indent=2, ensure_ascii=False)

    # Step 2: Get the summary for the top result
    top_title = pages[0].get("title", "")
    summary_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(top_title, safe='')}"

    try:
        summary_resp = requests.get(summary_url, timeout=15)
        summary_resp.raise_for_status()
        summary_data = summary_resp.json()
    except Exception as exc:
        import frappe
        frappe.log_error(
            f"Wikipedia summary error for '{top_title}': {str(exc)}",
            "Wikipedia Summary Error",
        )
        return f"Error fetching article summary: {exc}"

    # Check for disambiguation
    page_type = summary_data.get("type", "standard")
    if page_type == "disambiguation":
        # Return the list of disambiguation options
        disambig_links = []
        for link in summary_data.get("links", []):
            disambig_links.append({
                "title": link.get("title", ""),
                "url": f"https://{lang}.wikipedia.org/wiki/{requests.utils.quote(link.get('title', ''), safe='')}",
            })

        # Also include search results as alternatives
        alternatives = []
        for page in pages[1:]:
            alternatives.append({
                "title": page.get("title", ""),
                "description": page.get("description", ""),
            })

        return json.dumps({
            "query": query,
            "lang": lang,
            "result": "disambiguation",
            "message": f"'{top_title}' is a disambiguation page. Please specify which one you mean.",
            "options": disambig_links[:10],
            "alternative_results": alternatives,
        }, indent=2, ensure_ascii=False)

    # Build the result
    extract = summary_data.get("extract", "")
    if len(extract) > 2000:
        extract = extract[:2000] + "..."

    result = {
        "query": query,
        "lang": lang,
        "result": "found",
        "title": summary_data.get("title", ""),
        "description": summary_data.get("description", ""),
        "summary": extract,
        "url": summary_data.get("content_urls", {}).get("desktop", {}).get("page", ""),
        "thumbnail": summary_data.get("thumbnail", {}).get("source") if summary_data.get("thumbnail") else None,
    }

    # Add related search results as context
    if len(pages) > 1:
        result["related_searches"] = [
            {"title": p.get("title", ""), "description": p.get("description", "")}
            for p in pages[1:]
        ]

    return json.dumps(result, indent=2, ensure_ascii=False)
