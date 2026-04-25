"""
SEC EDGAR search tool for PH Agent.

Looks up company CIK numbers and SEC filing metadata using the SEC's
public REST API. Requires a proper User-Agent header (SEC requirement).
"""

import time
from typing import Annotated, Optional
from pydantic import Field
from agent_framework import tool, FunctionInvocationContext

# Rate limiting: max 10 requests per second
_last_call_time = 0.0
_MIN_INTERVAL = 0.1  # 100ms between calls


def _rate_limit():
    """Enforce minimum interval between SEC API calls."""
    global _last_call_time
    elapsed = time.time() - _last_call_time
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call_time = time.time()


def _headers() -> dict:
    """Return headers with proper User-Agent (required by SEC)."""
    return {
        "User-Agent": "ph_agent/1.0 (your-email@example.com)",
        "Accept": "application/json",
    }


@tool(
    name="sec_edgar",
    description=(
        "Look up company CIK numbers and SEC filing metadata using the SEC's "
        "public EDGAR API. Supports searching for a company by name to find "
        "its CIK number, and fetching the latest filings (10-K, 10-Q, 8-K, etc.) "
        "for a company by CIK. No API key required."
    ),
)
def sec_edgar_tool(
    query: Annotated[
        str,
        Field(description="Company name to search for (e.g., 'Apple', 'Microsoft'), or a CIK number (e.g., '320193')"),
    ],
    operation: Annotated[
        str,
        Field(description="Operation: 'search_cik' to find CIK by company name, or 'latest_filings' to get recent filings by CIK"),
    ] = "search_cik",
    count: Annotated[
        int,
        Field(description="Number of latest filings to return (1-20, default 5). Only used with 'latest_filings' operation."),
    ] = 5,
    ctx: FunctionInvocationContext = None,
) -> str:
    """
    Search SEC EDGAR for company and filing information.

    Args:
        query: Company name or CIK number.
        operation: 'search_cik' or 'latest_filings'.
        count: Number of filings to return (1-20, default 5).
        ctx: Function invocation context (injected by framework).

    Returns:
        JSON-formatted search results or filing data.
    """
    import json

    # Check for cancellation via context
    if ctx and ctx.kwargs:
        import frappe
        session_name = ctx.kwargs.get("session_name", "")
        if session_name:
            cancel_key = f"ph_agent:cancel:{session_name}"
            if frappe.cache().get_value(cancel_key):
                return "SEC EDGAR search cancelled."

    try:
        import requests
    except ImportError:
        return "Error: The 'requests' library is required but not available."

    query = query.strip()
    if not query:
        return "Error: No search query provided."

    count = max(1, min(count, 20))

    if operation == "search_cik":
        return _search_cik(query, requests)
    elif operation == "latest_filings":
        return _latest_filings(query, count, requests)
    else:
        return (
            f"Error: Invalid operation '{operation}'. "
            f"Valid options: 'search_cik', 'latest_filings'."
        )


def _search_cik(query: str, requests) -> str:
    """Search for a company by name and return CIK information."""
    import json

    _rate_limit()
    try:
        resp = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={"q": query, "dateRange": "all", "startdt": "", "enddt": ""},
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        import frappe
        frappe.log_error(
            f"SEC EDGAR search error for '{query}': {str(exc)}",
            "SEC EDGAR Error",
        )
        return f"Error searching SEC EDGAR: {exc}"

    results = []
    for hit in data.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        cik = source.get("cik") or source.get("cik_str", "")
        name = source.get("name", "") or source.get("company_name", "")
        if cik:
            results.append({
                "cik": str(cik).zfill(10),
                "name": name,
                "ticker": source.get("ticker", ""),
                "sic": source.get("sic", ""),
                "sic_description": source.get("sic_description", ""),
                "location": source.get("location", ""),
                "state": source.get("state", ""),
                "country": source.get("country", ""),
            })

    if not results:
        return json.dumps({
            "query": query,
            "result": "not_found",
            "message": f"No companies found matching '{query}'. Try a different name or use the full legal name.",
        }, indent=2, ensure_ascii=False)

    return json.dumps({
        "query": query,
        "count": len(results),
        "results": results[:10],
    }, indent=2, ensure_ascii=False)


def _latest_filings(cik: str, count: int, requests) -> str:
    """Fetch the latest filings for a company by CIK."""
    import json

    # Clean CIK: remove non-digits, pad to 10 digits
    cik_clean = "".join(c for c in cik if c.isdigit())
    if not cik_clean:
        return "Error: Invalid CIK number. CIK should be a numeric identifier."

    cik_padded = cik_clean.zfill(10)

    _rate_limit()
    try:
        url = f"https://efts.sec.gov/cgi-bin/browse-edgar"
        resp = requests.get(
            url,
            params={
                "action": "getcompany",
                "CIK": cik_padded,
                "type": "",
                "dateb": "",
                "owner": "exclude",
                "start": "0",
                "count": str(count),
                "output": "json",
            },
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        import frappe
        frappe.log_error(
            f"SEC EDGAR filings error for CIK '{cik}': {str(exc)}",
            "SEC EDGAR Error",
        )
        return f"Error fetching SEC filings: {exc}"

    company = data.get("company", {})
    filings_list = data.get("filings", {}).get("recent", {})

    if not filings_list:
        return json.dumps({
            "cik": cik_padded,
            "result": "not_found",
            "message": f"No filings found for CIK '{cik_padded}'.",
        }, indent=2, ensure_ascii=False)

    # Extract filing data
    form_types = filings_list.get("form", [])
    filing_dates = filings_list.get("filingDate", [])
    descriptions = filings_list.get("primaryDocument", [])
    accession_numbers = filings_list.get("accessionNumber", [])

    filings = []
    for i in range(min(count, len(form_types))):
        acc_num = accession_numbers[i] if i < len(accession_numbers) else ""
        doc = descriptions[i] if i < len(descriptions) else ""
        edgar_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_clean}/{acc_num.replace('-', '')}/{doc}"
            if acc_num and doc else ""
        )
        filings.append({
            "form_type": form_types[i] if i < len(form_types) else "",
            "filing_date": filing_dates[i] if i < len(filing_dates) else "",
            "description": doc,
            "url": edgar_url,
        })

    return json.dumps({
        "company_name": company.get("name", ""),
        "cik": cik_padded,
        "ticker": company.get("ticker", ""),
        "sic": company.get("sic", ""),
        "sic_description": company.get("sicDescription", ""),
        "business_address": company.get("businessAddress", {}).get("street1", ""),
        "state": company.get("businessAddress", {}).get("state", ""),
        "filings": filings,
    }, indent=2, ensure_ascii=False)
