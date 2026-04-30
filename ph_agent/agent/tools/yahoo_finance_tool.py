"""
Yahoo Finance tool for PH Agent.

Fetches stock quotes, historical prices, financial statements, and company
information using the yfinance library. Requires: pip install yfinance
"""

import time
from typing import Annotated, Optional
from pydantic import Field
from agent_framework import tool, FunctionInvocationContext

# Rate limiting: max 1 call per 2 seconds
_last_call_time = 0.0


def _rate_limit():
    """Enforce minimum 2-second interval between Yahoo Finance API calls."""
    global _last_call_time
    elapsed = time.time() - _last_call_time
    if elapsed < 2.0:
        time.sleep(2.0 - elapsed)
    _last_call_time = time.time()


@tool(
    name="yahoo_finance",
    description=(
        "Fetch stock quotes, historical prices, company information, financial "
        "statements, dividends, and analyst recommendations from Yahoo Finance. "
        "Supports operations: quote (current price), history (price history), "
        "info (company overview), financials (income statement), dividends "
        "(dividend history), and recommendations (analyst ratings)."
    ),
)
def yahoo_finance_tool(
    symbol: Annotated[
        str,
        Field(description="Stock ticker symbol (e.g., 'AAPL', 'TSLA', 'MSFT', 'GOOGL')"),
    ],
    operation: Annotated[
        str,
        Field(description="Data type to fetch: 'quote', 'history', 'info', 'financials', 'dividends', or 'recommendations'"),
    ] = "quote",
    period: Annotated[
        Optional[str],
        Field(description="Time period for history: '1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max'"),
    ] = "1mo",
    ctx: FunctionInvocationContext = None,
) -> str:
    """
    Fetch financial data from Yahoo Finance.

    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL').
        operation: Data type: 'quote', 'history', 'info', 'financials',
                   'dividends', or 'recommendations'.
        period: Time period for history data (default: '1mo').
        ctx: Function invocation context (injected by framework).

    Returns:
        JSON-formatted financial data.
    """
    import json

    # Check for cancellation via context
    if ctx and ctx.kwargs:
        import frappe
        session_name = ctx.kwargs.get("session_name", "")
        if session_name:
            cancel_key = f"ph_agent:cancel:{session_name}"
            if frappe.cache().get_value(cancel_key):
                return "Yahoo Finance request cancelled."

    # Lazy import yfinance
    try:
        import yfinance as yf
    except ImportError:
        return (
            "Error: The 'yfinance' library is not installed. "
            "Please install it with: pip install yfinance"
        )

    # Validate symbol
    symbol = symbol.strip().upper()
    if not symbol:
        return "Error: No stock symbol provided."

    # Validate operation
    valid_ops = {"quote", "history", "info", "financials", "dividends", "recommendations"}
    if operation not in valid_ops:
        return (
            f"Error: Invalid operation '{operation}'. "
            f"Valid options: {', '.join(sorted(valid_ops))}."
        )

    # Rate limit
    _rate_limit()

    try:
        ticker = yf.Ticker(symbol)

        if operation == "quote":
            # Fast path: get current price data
            hist = ticker.history(period="1d")
            info = ticker.info or {}

            if hist.empty and not info.get("currentPrice"):
                return json.dumps({
                    "symbol": symbol,
                    "error": f"No data found for symbol '{symbol}'. The symbol may be invalid or delisted.",
                }, indent=2, ensure_ascii=False)

            quote_data = {
                "symbol": symbol,
                "name": info.get("longName") or info.get("shortName", ""),
                "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "previous_close": info.get("previousClose") or info.get("regularMarketPreviousClose"),
                "change": info.get("regularMarketChange"),
                "change_percent": info.get("regularMarketChangePercent"),
                "day_high": info.get("dayHigh") or info.get("regularMarketDayHigh"),
                "day_low": info.get("dayLow") or info.get("regularMarketDayLow"),
                "volume": info.get("volume") or info.get("regularMarketVolume"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "currency": info.get("currency", "USD"),
            }
            # Clean None values
            quote_data = {k: v for k, v in quote_data.items() if v is not None}
            return json.dumps(quote_data, indent=2, ensure_ascii=False)

        elif operation == "history":
            valid_periods = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
            if period not in valid_periods:
                period = "1mo"
            hist = ticker.history(period=period)
            if hist.empty:
                return json.dumps({
                    "symbol": symbol,
                    "period": period,
                    "error": f"No historical data found for '{symbol}' in period '{period}'.",
                }, indent=2, ensure_ascii=False)

            records = []
            for date, row in hist.iterrows():
                records.append({
                    "date": str(date.date()),
                    "open": round(float(row["Open"]), 2),
                    "high": round(float(row["High"]), 2),
                    "low": round(float(row["Low"]), 2),
                    "close": round(float(row["Close"]), 2),
                    "volume": int(row["Volume"]),
                })

            return json.dumps({
                "symbol": symbol,
                "period": period,
                "count": len(records),
                "records": records,
            }, indent=2, ensure_ascii=False)

        elif operation == "info":
            info = ticker.info or {}
            if not info:
                return json.dumps({
                    "symbol": symbol,
                    "error": f"No company information found for '{symbol}'.",
                }, indent=2, ensure_ascii=False)

            # Extract key info fields
            key_info = {
                "symbol": symbol,
                "name": info.get("longName") or info.get("shortName", ""),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "country": info.get("country"),
                "website": info.get("website"),
                "employees": info.get("fullTimeEmployees"),
                "description": info.get("longBusinessSummary", ""),
                "market_cap": info.get("marketCap"),
                "enterprise_value": info.get("enterpriseValue"),
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "peg_ratio": info.get("pegRatio"),
                "dividend_yield": info.get("dividendYield"),
                "beta": info.get("beta"),
                "52_week_high": info.get("fiftyTwoWeekHigh"),
                "52_week_low": info.get("fiftyTwoWeekLow"),
                "50_day_avg": info.get("fiftyDayAverage"),
                "200_day_avg": info.get("twoHundredDayAverage"),
                "currency": info.get("currency", "USD"),
            }
            key_info = {k: v for k, v in key_info.items() if v is not None}
            if key_info.get("description") and len(key_info["description"]) > 1000:
                key_info["description"] = key_info["description"][:1000] + "..."
            return json.dumps(key_info, indent=2, ensure_ascii=False)

        elif operation == "financials":
            financials = ticker.financials
            if financials is None or financials.empty:
                return json.dumps({
                    "symbol": symbol,
                    "error": f"No financial data found for '{symbol}'.",
                }, indent=2, ensure_ascii=False)

            records = []
            for date in financials.columns[:4]:  # Last 4 years
                year_data = {}
                for field in ["Total Revenue", "Gross Profit", "Operating Income",
                              "Net Income", "EBITDA", "Operating Revenue",
                              "Cost Of Revenue", "Research And Development",
                              "Operating Expense", "Interest Expense"]:
                    val = financials.loc[field, date] if field in financials.index else None
                    if val is not None:
                        year_data[field.lower().replace(" ", "_")] = float(val)
                records.append({
                    "fiscal_year": str(date.year),
                    **year_data,
                })

            return json.dumps({
                "symbol": symbol,
                "financials": records,
            }, indent=2, ensure_ascii=False)

        elif operation == "dividends":
            dividends = ticker.dividends
            if dividends is None or dividends.empty:
                return json.dumps({
                    "symbol": symbol,
                    "message": f"No dividend data found for '{symbol}'. The stock may not pay dividends.",
                }, indent=2, ensure_ascii=False)

            records = []
            for date, amount in dividends.tail(20).items():
                records.append({
                    "date": str(date.date()),
                    "dividend": round(float(amount), 4),
                })

            return json.dumps({
                "symbol": symbol,
                "count": len(records),
                "recent_dividends": records,
            }, indent=2, ensure_ascii=False)

        elif operation == "recommendations":
            # yfinance v1.3+ changed recommendations to a summary table.
            # Use upgrades_downgrades for individual analyst actions with dates.
            recs = ticker.upgrades_downgrades
            if recs is None or recs.empty:
                # Fallback: try the summary table
                summary = ticker.recommendations
                if summary is not None and not summary.empty:
                    records = []
                    for _, row in summary.iterrows():
                        records.append({
                            "period": row.get("period", ""),
                            "strong_buy": int(row.get("strongBuy", 0)),
                            "buy": int(row.get("buy", 0)),
                            "hold": int(row.get("hold", 0)),
                            "sell": int(row.get("sell", 0)),
                            "strong_sell": int(row.get("strongSell", 0)),
                        })
                    return json.dumps({
                        "symbol": symbol,
                        "type": "summary",
                        "count": len(records),
                        "recommendations": records,
                    }, indent=2, ensure_ascii=False)

                return json.dumps({
                    "symbol": symbol,
                    "message": f"No analyst recommendations found for '{symbol}'.",
                }, indent=2, ensure_ascii=False)

            records = []
            for date, row in recs.head(10).iterrows():
                entry = {
                    "firm": row.get("Firm", ""),
                    "action": row.get("Action", ""),
                    "to_grade": row.get("ToGrade", row.get("To Grade", "")),
                    "from_grade": row.get("FromGrade", row.get("From Grade", "")),
                }
                # Handle both DatetimeIndex and integer index
                if hasattr(date, "date"):
                    entry["date"] = str(date.date())
                else:
                    entry["date"] = str(date)
                records.append(entry)

            return json.dumps({
                "symbol": symbol,
                "type": "upgrades_downgrades",
                "count": len(records),
                "recommendations": records,
            }, indent=2, ensure_ascii=False)

    except Exception as exc:
        import frappe
        frappe.log_error(
            f"Yahoo Finance error for '{symbol}' (op={operation}): {str(exc)}",
            "Yahoo Finance Error",
        )
        return f"Error fetching Yahoo Finance data: {exc}"
