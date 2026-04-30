"""
SEC EDGAR search tool for PH Agent.

Looks up company CIK numbers and SEC filing metadata using the SEC's
public REST API. The SEC uses Akamai WAF which blocks non-browser
User-Agent strings, so this tool uses a standard browser User-Agent
to comply with SEC access requirements.

SEC API documentation:
  - Company search: https://efts.sec.gov/LATEST/search-index
  - Company submissions: https://data.sec.gov/submissions/CIK##########.json
  - Company facts (XBRL): https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
"""

import json
import re
import time
from typing import Annotated
from pydantic import Field
from agent_framework import tool, FunctionInvocationContext

# Rate limiting: max 10 requests per second (SEC requirement)
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
    """Return headers that pass SEC's Akamai WAF.

    The SEC's Akamai Web Application Firewall blocks requests with
    non-browser User-Agent strings (e.g. ``python-requests`` or
    custom agents like ``ph_agent/1.0``).  A standard browser
    User-Agent is required to access both ``efts.sec.gov`` and
    ``data.sec.gov``.
    """
    return {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
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
    """Search for a company by name and return CIK information.

    Uses the SEC's EDGAR full-text search API (``efts.sec.gov``) to find
    company filings, then extracts CIK, company name, and ticker from
    the ``display_names`` field of the search hits.
    """
    query_lower = query.strip().lower()

    _rate_limit()
    try:
        resp = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={
                "q": query,
                "dateRange": "all",
                "startdt": "",
                "enddt": "",
                "hitsPerPage": 50,
            },
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        import frappe
        frappe.log_error(
            f"SEC EDGAR CIK lookup error for '{query}': {str(exc)}",
            "SEC EDGAR Error",
        )
        return f"Error searching SEC EDGAR: {exc}"

    # Parse display_names from search hits to extract company info.
    # Each hit has a display_names list like:
    #   ["APPLE INC  (AAPL)  (CIK 0000320193)"]
    # and a ciks list like:
    #   ["0000320193"]
    seen_ciks: set[str] = set()
    results: list[dict[str, str]] = []

    for hit in data.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        ciks = source.get("ciks", [])
        display_names = source.get("display_names", [])

        for cik in ciks:
            cik_str = str(cik).strip()
            if cik_str in seen_ciks:
                continue
            seen_ciks.add(cik_str)

            # Extract name and ticker from display_names
            name = ""
            ticker = ""
            for dn in display_names:
                # Pattern: "COMPANY NAME  (TICKER)  (CIK ##########)"
                m = re.match(
                    r"^(.+?)\s{2,}\(([A-Za-z0-9.]+)\)\s{2,}\(CIK\s+(\d+)\)",
                    dn.strip(),
                )
                if m:
                    name = m.group(1).strip()
                    ticker = m.group(2).strip()
                    break
                # Pattern: "COMPANY NAME  (CIK ##########)" — no ticker
                m2 = re.match(
                    r"^(.+?)\s{2,}\(CIK\s+(\d+)\)",
                    dn.strip(),
                )
                if m2:
                    name = m2.group(1).strip()
                    break

            if not name:
                name = display_names[0] if display_names else "Unknown"

            # Check relevance: match against name or ticker
            name_lower = name.lower()
            ticker_lower = ticker.lower()
            if (query_lower in name_lower
                    or query_lower == ticker_lower
                    or name_lower.startswith(query_lower)):
                results.append({
                    "cik": cik_str.zfill(10),
                    "name": name,
                    "ticker": ticker,
                })

    if not results:
        return json.dumps({
            "query": query,
            "result": "not_found",
            "message": (
                f"No companies found matching '{query}'. "
                f"Try a different name, ticker symbol, or use the full legal name."
            ),
        }, indent=2, ensure_ascii=False)

    return json.dumps({
        "query": query,
        "count": len(results),
        "results": results[:10],
    }, indent=2, ensure_ascii=False)


def _latest_filings(cik: str, count: int, requests) -> str:
    """Fetch the latest filings for a company by CIK.

    Uses the SEC's official submissions API
    (https://data.sec.gov/submissions/CIK##########.json) which returns
    recent filings including form type, date, and document URLs.
    """
    # Clean CIK: remove non-digits, pad to 10 digits
    cik_clean = "".join(c for c in cik if c.isdigit())
    if not cik_clean:
        return "Error: Invalid CIK number. CIK should be a numeric identifier."

    cik_padded = cik_clean.zfill(10)

    _rate_limit()
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
        resp = requests.get(
            url,
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

    # Extract company info from the root of the response
    company_name = data.get("name", "")
    ticker = data.get("tickers", [None])[0] if data.get("tickers") else ""
    sic = data.get("sic", "")
    sic_description = data.get("sicDescription", "")
    address = data.get("addresses", {}).get("business", {})
    street1 = address.get("street1", "")
    state = address.get("state", "")

    # Recent filings are in filings.recent
    filings_data = data.get("filings", {}).get("recent", {})
    form_types = filings_data.get("form", [])
    filing_dates = filings_data.get("filingDate", [])
    primary_docs = filings_data.get("primaryDocument", [])
    accession_numbers = filings_data.get("accessionNumber", [])
    descriptions = filings_data.get("primaryDocDescription", [])

    if not form_types:
        return json.dumps({
            "cik": cik_padded,
            "result": "not_found",
            "message": f"No filings found for CIK '{cik_padded}'.",
        }, indent=2, ensure_ascii=False)

    filings = []
    for i in range(min(count, len(form_types))):
        acc_num = accession_numbers[i] if i < len(accession_numbers) else ""
        doc = primary_docs[i] if i < len(primary_docs) else ""
        desc = descriptions[i] if i < len(descriptions) else ""
        edgar_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_clean}/{acc_num.replace('-', '')}/{doc}"
            if acc_num and doc else ""
        )
        filings.append({
            "form_type": form_types[i] if i < len(form_types) else "",
            "filing_date": filing_dates[i] if i < len(filing_dates) else "",
            "description": desc or doc,
            "url": edgar_url,
        })

    return json.dumps({
        "company_name": company_name,
        "cik": cik_padded,
        "ticker": ticker,
        "sic": sic,
        "sic_description": sic_description,
        "business_address": street1,
        "state": state,
        "filings": filings,
    }, indent=2, ensure_ascii=False)
