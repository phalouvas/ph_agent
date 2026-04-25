"""
Hacker News search tool for PH Agent.

Fetches top/new/best stories and searches stories by keyword using
the Firebase API and Algolia search. No API key required.
"""

from typing import Annotated, Optional
from pydantic import Field
from agent_framework import tool, FunctionInvocationContext


@tool(
    name="hacker_news",
    description=(
        "Fetch stories, comments, and trending topics from Hacker News. "
        "Supports operations: top_stories (current top stories), new_stories "
        "(latest submissions), best_stories (highest-rated recent stories), "
        "and search (find stories by keyword). No API key required."
    ),
)
def hacker_news_tool(
    operation: Annotated[
        str,
        Field(description="Operation: 'top_stories', 'new_stories', 'best_stories', or 'search'"),
    ] = "top_stories",
    query: Annotated[
        Optional[str],
        Field(description="Search keyword. Required for 'search' operation."),
    ] = None,
    max_results: Annotated[
        int,
        Field(description="Maximum number of results to return (1-10)"),
    ] = 5,
    ctx: FunctionInvocationContext = None,
) -> str:
    """
    Fetch stories from Hacker News.

    Args:
        operation: 'top_stories', 'new_stories', 'best_stories', or 'search'.
        query: Search keyword (required for 'search').
        max_results: Max results (1-10, default 5).
        ctx: Function invocation context (injected by framework).

    Returns:
        JSON-formatted stories with title, score, author, and URL.
    """
    import json

    # Check for cancellation via context
    if ctx and ctx.kwargs:
        import frappe
        session_name = ctx.kwargs.get("session_name", "")
        if session_name:
            cancel_key = f"ph_agent:cancel:{session_name}"
            if frappe.cache().get_value(cancel_key):
                return "Hacker News request cancelled."

    try:
        import requests
    except ImportError:
        return "Error: The 'requests' library is required but not available."

    max_results = max(1, min(max_results, 10))

    # Validate operation
    valid_ops = {"top_stories", "new_stories", "best_stories", "search"}
    if operation not in valid_ops:
        return (
            f"Error: Invalid operation '{operation}'. "
            f"Valid options: {', '.join(sorted(valid_ops))}."
        )

    if operation == "search":
        if not query:
            return "Error: A search query is required for the 'search' operation."
        return _search_stories(query, max_results, requests)
    else:
        return _fetch_stories(operation, max_results, requests)


def _fetch_stories(operation: str, max_results: int, requests) -> str:
    """Fetch top/new/best stories from Firebase API."""
    import json

    # Map operation to Firebase endpoint
    endpoint_map = {
        "top_stories": "topstories",
        "new_stories": "newstories",
        "best_stories": "beststories",
    }
    endpoint = endpoint_map[operation]

    try:
        # Step 1: Get list of story IDs
        ids_resp = requests.get(
            f"https://hacker-news.firebaseio.com/v0/{endpoint}.json",
            timeout=15,
        )
        ids_resp.raise_for_status()
        story_ids = ids_resp.json()

        if not story_ids:
            return json.dumps({
                "operation": operation,
                "result": "not_found",
                "message": f"No stories found for '{operation}'.",
            }, indent=2, ensure_ascii=False)

        # Step 2: Fetch individual story details (batch of IDs)
        story_ids = story_ids[:max_results]
        stories = []
        for sid in story_ids:
            try:
                item_resp = requests.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                    timeout=10,
                )
                if item_resp.ok:
                    item = item_resp.json()
                    if item and not item.get("deleted") and not item.get("dead"):
                        stories.append(_format_story(item))
            except Exception:
                continue  # Skip individual failures

        if not stories:
            return json.dumps({
                "operation": operation,
                "result": "not_found",
                "message": "No accessible stories found.",
            }, indent=2, ensure_ascii=False)

        return json.dumps({
            "operation": operation,
            "count": len(stories),
            "stories": stories,
        }, indent=2, ensure_ascii=False)

    except Exception as exc:
        import frappe
        frappe.log_error(
            f"Hacker News API error ({operation}): {str(exc)}",
            "Hacker News Error",
        )
        return f"Error fetching Hacker News stories: {exc}"


def _search_stories(query: str, max_results: int, requests) -> str:
    """Search stories using Algolia API."""
    import json

    try:
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={
                "query": query,
                "hitsPerPage": max_results,
                "tags": "story",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        import frappe
        frappe.log_error(
            f"Hacker News search error for '{query}': {str(exc)}",
            "Hacker News Search Error",
        )
        return f"Error searching Hacker News: {exc}"

    hits = data.get("hits", [])
    if not hits:
        return json.dumps({
            "query": query,
            "operation": "search",
            "result": "not_found",
            "message": f"No Hacker News stories found for '{query}'.",
        }, indent=2, ensure_ascii=False)

    stories = []
    for hit in hits[:max_results]:
        stories.append({
            "title": hit.get("title", ""),
            "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
            "hn_url": f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
            "points": hit.get("points", 0),
            "author": hit.get("author", ""),
            "num_comments": hit.get("num_comments", 0),
            "created_at": hit.get("created_at", ""),
            "tags": hit.get("_tags", []),
        })

    return json.dumps({
        "query": query,
        "operation": "search",
        "count": len(stories),
        "stories": stories,
    }, indent=2, ensure_ascii=False)


def _format_story(item: dict) -> dict:
    """Format a Firebase story item into a clean dict."""
    return {
        "title": item.get("title", ""),
        "url": item.get("url") or f"https://news.ycombinator.com/item?id={item.get('id', '')}",
        "hn_url": f"https://news.ycombinator.com/item?id={item.get('id', '')}",
        "score": item.get("score", 0),
        "author": item.get("by", ""),
        "descendants": item.get("descendants", 0),
        "time": item.get("time", 0),
        "type": item.get("type", "story"),
    }
