"""
Reddit search tool for PH Agent.

Searches subreddits, gets hot/top posts, and retrieves post details
using Reddit's public JSON API. No API key required.
"""

import time
from typing import Annotated, Optional
from pydantic import Field
from agent_framework import tool, FunctionInvocationContext

# Rate limiting: max 60 requests per minute
_last_call_time = 0.0
_MIN_INTERVAL = 1.0  # 1 second between calls


def _rate_limit():
    """Enforce minimum interval between Reddit API calls."""
    global _last_call_time
    elapsed = time.time() - _last_call_time
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call_time = time.time()


def _headers() -> dict:
    """Return headers with proper User-Agent (required by Reddit)."""
    return {
        "User-Agent": "ph_agent/1.0",
        "Accept": "application/json",
    }


@tool(
    name="reddit",
    description=(
        "Search Reddit for posts, comments, and trending topics. Can search "
        "across all of Reddit or within a specific subreddit. Supports operations: "
        "search (find posts by query), hot (hot/trending posts), and top (top "
        "posts by time period). No API key required."
    ),
)
def reddit_tool(
    query: Annotated[
        Optional[str],
        Field(description="Search query. Required for 'search' operation. Optional for 'hot' and 'top' (filters by relevance to query)."),
    ] = None,
    subreddit: Annotated[
        str,
        Field(description="Subreddit to search (e.g., 'python', 'finance', 'ERPNext'). Use 'all' for all of Reddit."),
    ] = "all",
    operation: Annotated[
        str,
        Field(description="Operation: 'search' (find posts by query), 'hot' (trending posts), or 'top' (top posts by time period)"),
    ] = "search",
    time_period: Annotated[
        str,
        Field(description="Time period for 'top' operation: 'hour', 'day', 'week', 'month', 'year', 'all'"),
    ] = "week",
    max_results: Annotated[
        int,
        Field(description="Maximum number of results to return (1-10)"),
    ] = 5,
    ctx: FunctionInvocationContext = None,
) -> str:
    """
    Search Reddit for posts and discussions.

    Args:
        query: Search query (required for 'search').
        subreddit: Subreddit name (default: 'all').
        operation: 'search', 'hot', or 'top'.
        time_period: Time period for 'top' (default: 'week').
        max_results: Max results (1-10, default 5).
        ctx: Function invocation context (injected by framework).

    Returns:
        JSON-formatted Reddit posts with details.
    """
    import json

    # Check for cancellation via context
    if ctx and ctx.kwargs:
        import frappe
        session_name = ctx.kwargs.get("session_name", "")
        if session_name:
            cancel_key = f"ph_agent:cancel:{session_name}"
            if frappe.cache().get_value(cancel_key):
                return "Reddit search cancelled."

    try:
        import requests
    except ImportError:
        return "Error: The 'requests' library is required but not available."

    max_results = max(1, min(max_results, 10))

    # Validate operation
    valid_ops = {"search", "hot", "top"}
    if operation not in valid_ops:
        return (
            f"Error: Invalid operation '{operation}'. "
            f"Valid options: {', '.join(sorted(valid_ops))}."
        )

    # Validate time period
    valid_periods = {"hour", "day", "week", "month", "year", "all"}
    if operation == "top" and time_period not in valid_periods:
        time_period = "week"

    # Validate query for search
    if operation == "search" and not query:
        return "Error: A search query is required for the 'search' operation."

    subreddit = subreddit.strip().lower()
    if not subreddit:
        subreddit = "all"

    _rate_limit()

    try:
        if operation == "search":
            url = f"https://www.reddit.com/r/{subreddit}/search.json"
            params = {
                "q": query,
                "restrict_sr": "on" if subreddit != "all" else "off",
                "sort": "relevance",
                "limit": max_results,
                "raw_json": "1",
            }
        elif operation == "hot":
            url = f"https://www.reddit.com/r/{subreddit}/hot.json"
            params = {"limit": max_results, "raw_json": "1"}
        else:  # top
            url = f"https://www.reddit.com/r/{subreddit}/top.json"
            params = {"limit": max_results, "t": time_period, "raw_json": "1"}

        resp = requests.get(url, params=params, headers=_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()

    except Exception as exc:
        import frappe
        frappe.log_error(
            f"Reddit API error ({operation} in r/{subreddit}): {str(exc)}",
            "Reddit Error",
        )
        return f"Error accessing Reddit: {exc}"

    children = data.get("data", {}).get("children", [])
    if not children:
        msg = f"No posts found"
        if query:
            msg += f" for '{query}'"
        if subreddit != "all":
            msg += f" in r/{subreddit}"
        return json.dumps({
            "query": query or "",
            "subreddit": subreddit,
            "operation": operation,
            "result": "not_found",
            "message": msg + ".",
        }, indent=2, ensure_ascii=False)

    results = []
    for child in children[:max_results]:
        post = child.get("data", {})
        if post.get("stickied"):
            continue  # Skip stickied posts

        # Truncate selftext for display
        selftext = post.get("selftext", "")
        if len(selftext) > 500:
            selftext = selftext[:500] + "..."

        # Get top comment if available
        top_comment = ""
        try:
            permalink = post.get("permalink", "")
            if permalink:
                comments_url = f"https://www.reddit.com{permalink}.json"
                comments_resp = requests.get(
                    comments_url, headers=_headers(), timeout=10
                )
                if comments_resp.ok:
                    comments_data = comments_resp.json()
                    if len(comments_data) > 1:
                        replies = comments_data[1].get("data", {}).get("children", [])
                        for reply in replies:
                            if reply.get("kind") == "t1":  # Comment
                                comment_body = reply.get("data", {}).get("body", "")
                                if comment_body:
                                    top_comment = comment_body[:300]
                                    if len(comment_body) > 300:
                                        top_comment += "..."
                                    break
        except Exception:
            pass  # Non-critical

        result = {
            "title": post.get("title", ""),
            "score": post.get("score", 0),
            "upvote_ratio": post.get("upvote_ratio"),
            "author": post.get("author", "[deleted]"),
            "num_comments": post.get("num_comments", 0),
            "created_utc": post.get("created_utc", 0),
            "subreddit": post.get("subreddit", ""),
            "url": post.get("url", ""),
            "permalink": f"https://www.reddit.com{post.get('permalink', '')}",
            "is_self": post.get("is_self", False),
            "selftext": selftext if post.get("is_self") else None,
            "domain": post.get("domain", ""),
            "top_comment_excerpt": top_comment or None,
        }
        results.append(result)

    return json.dumps({
        "query": query or "",
        "subreddit": subreddit,
        "operation": operation,
        "count": len(results),
        "results": results,
    }, indent=2, ensure_ascii=False)
