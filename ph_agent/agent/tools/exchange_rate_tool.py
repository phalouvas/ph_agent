"""
ECB Exchange Rates tool for PH Agent.

Fetches daily currency exchange rates from the European Central Bank.
Rates are cached for 6 hours (ECB updates once per working day).
Supports 30+ currencies against EUR with cross-rate computation.
"""

import xml.etree.ElementTree as ET
from typing import Annotated, Optional
from pydantic import Field
from agent_framework import tool, FunctionInvocationContext

# Cache key and TTL (6 hours)
ECB_CACHE_KEY = "ph_agent:ecb_rates"
ECB_CACHE_TTL = 6 * 60 * 60  # 6 hours in seconds

# ECB XML feed URL
ECB_FEED_URL = "https://ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

# Common currency names for display
CURRENCY_NAMES = {
    "EUR": "Euro",
    "USD": "US Dollar",
    "GBP": "British Pound",
    "JPY": "Japanese Yen",
    "CHF": "Swiss Franc",
    "AUD": "Australian Dollar",
    "CAD": "Canadian Dollar",
    "CNY": "Chinese Yuan",
    "HKD": "Hong Kong Dollar",
    "NZD": "New Zealand Dollar",
    "SEK": "Swedish Krona",
    "KRW": "South Korean Won",
    "SGD": "Singapore Dollar",
    "NOK": "Norwegian Krone",
    "MXN": "Mexican Peso",
    "INR": "Indian Rupee",
    "BRL": "Brazilian Real",
    "ZAR": "South African Rand",
    "TRY": "Turkish Lira",
    "RUB": "Russian Ruble",
    "PLN": "Polish Zloty",
    "DKK": "Danish Krone",
    "CZK": "Czech Koruna",
    "HUF": "Hungarian Forint",
    "ILS": "Israeli Shekel",
    "CLP": "Chilean Peso",
    "PHP": "Philippine Peso",
    "MYR": "Malaysian Ringgit",
    "IDR": "Indonesian Rupiah",
    "THB": "Thai Baht",
    "ISK": "Icelandic Krona",
    "RON": "Romanian Leu",
    "BGN": "Bulgarian Lev",
    "HRK": "Croatian Kuna",
}


def _fetch_rates_from_ecb() -> dict[str, float] | None:
    """Fetch exchange rates from ECB XML feed. Returns {CURRENCY: rate_vs_EUR}."""
    try:
        import requests
        resp = requests.get(ECB_FEED_URL, timeout=15)
        resp.raise_for_status()
    except Exception:
        return None

    try:
        root = ET.fromstring(resp.content)
        # Namespace: http://www.ecb.int/vocabulary/2002-08-01/eurofxref
        ns = {"ns": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
        rates = {"EUR": 1.0}
        for cube in root.findall(".//ns:Cube/ns:Cube/ns:Cube", ns):
            currency = cube.get("currency")
            rate = cube.get("rate")
            if currency and rate:
                rates[currency] = float(rate)
        return rates
    except ET.ParseError as exc:
        import frappe
        frappe.log_error(f"ECB XML parse error: {exc}", "ECB Exchange Rate Error")
        return None


def _get_rates() -> dict[str, float] | None:
    """Get exchange rates, using cache if available."""
    import frappe
    cached = frappe.cache().get_value(ECB_CACHE_KEY)
    if cached is not None:
        return cached

    rates = _fetch_rates_from_ecb()
    if rates:
        frappe.cache().set_value(ECB_CACHE_KEY, rates, expires_in_sec=ECB_CACHE_TTL)
    return rates


def _convert(rates: dict[str, float], base: str, target: str, amount: float = 1.0) -> float | None:
    """Convert amount from base currency to target currency using cross rates."""
    if base not in rates or target not in rates:
        return None
    # Convert base → EUR → target
    base_rate = rates[base]  # 1 EUR = base_rate of base currency
    target_rate = rates[target]  # 1 EUR = target_rate of target currency
    # amount in base → amount / base_rate in EUR → (amount / base_rate) * target_rate in target
    return (amount / base_rate) * target_rate


@tool(
    name="exchange_rate",
    description=(
        "Fetch current currency exchange rates from the European Central Bank. "
        "Supports 30+ currencies including USD, GBP, JPY, CHF, AUD, CAD, CNY, "
        "INR, BRL, and more. Can return all rates for a base currency or convert "
        "a specific amount between two currencies. Rates are updated once per "
        "working day by the ECB."
    ),
)
def exchange_rate_tool(
    base: Annotated[
        str,
        Field(description="Base currency code (e.g., 'EUR', 'USD', 'GBP'). Default: EUR"),
    ] = "EUR",
    target: Annotated[
        Optional[str],
        Field(description="Target currency code for conversion (e.g., 'USD', 'JPY'). If omitted, returns all rates for the base currency."),
    ] = None,
    amount: Annotated[
        Optional[float],
        Field(description="Amount to convert from base to target (e.g., 1000). Only used when target is specified."),
    ] = None,
    ctx: FunctionInvocationContext = None,
) -> str:
    """
    Fetch currency exchange rates from the ECB.

    Args:
        base: Base currency code (default: 'EUR').
        target: Optional target currency for conversion.
        amount: Optional amount to convert (only with target).
        ctx: Function invocation context (injected by framework).

    Returns:
        JSON-formatted exchange rate data.
    """
    import json

    # Check for cancellation via context
    if ctx and ctx.kwargs:
        import frappe
        session_name = ctx.kwargs.get("session_name", "")
        if session_name:
            cancel_key = f"ph_agent:cancel:{session_name}"
            if frappe.cache().get_value(cancel_key):
                return "Exchange rate request cancelled."

    base = base.upper().strip()
    if target:
        target = target.upper().strip()

    rates = _get_rates()
    if rates is None:
        return "Error: Unable to fetch exchange rates from the European Central Bank. The feed may be temporarily unavailable."

    if base not in rates:
        return json.dumps({
            "error": f"Unknown currency code '{base}'. Supported currencies: {', '.join(sorted(rates.keys()))}",
        }, indent=2, ensure_ascii=False)

    if target:
        # Single conversion
        if target not in rates:
            return json.dumps({
                "error": f"Unknown currency code '{target}'. Supported currencies: {', '.join(sorted(rates.keys()))}",
            }, indent=2, ensure_ascii=False)

        conv_amount = amount if amount is not None else 1.0
        result = _convert(rates, base, target, conv_amount)
        if result is None:
            return f"Error: Cannot convert from {base} to {target}."

        return json.dumps({
            "base": base,
            "base_name": CURRENCY_NAMES.get(base, base),
            "target": target,
            "target_name": CURRENCY_NAMES.get(target, target),
            "amount": conv_amount,
            "converted_amount": round(result, 4),
            "rate": round(_convert(rates, base, target, 1.0), 6),
            "source": "European Central Bank",
            "note": "Rates updated once per working day.",
        }, indent=2, ensure_ascii=False)

    else:
        # Return all rates relative to base
        all_rates = []
        for currency, rate_vs_eur in sorted(rates.items()):
            if currency == base:
                continue
            converted = _convert(rates, base, currency, 1.0)
            all_rates.append({
                "currency": currency,
                "name": CURRENCY_NAMES.get(currency, currency),
                "rate": round(converted, 6) if converted else None,
            })

        return json.dumps({
            "base": base,
            "base_name": CURRENCY_NAMES.get(base, base),
            "count": len(all_rates),
            "rates": all_rates,
            "source": "European Central Bank",
            "note": "Rates updated once per working day.",
        }, indent=2, ensure_ascii=False)
