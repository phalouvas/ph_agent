# PH Agent — Web Search & Online Tools

All tools listed here are **free and require no API key**. They are registered in the Tool Registry via `ph_agent/patches/v16_0/seed_tool_registry.py` and follow the same patterns as `web_search_tool.py` (`@tool` decorator, lazy imports, cancellation support, JSON output).

---

## ✅ 1. Wikipedia Tool — Implemented

**File:** `ph_agent/agent/tools/wikipedia_tool.py`  
**Tool name:** `wikipedia`  
**Dependencies:** `requests` (built-in)

Fetches clean, structured article content from Wikipedia.

**Use cases:**
- "Tell me about just-in-time manufacturing"
- "What is the capital of Bhutan?"
- "Explain the Toyota Production System"

**Parameters:**
- `query` (str, required) — The topic or article title to look up
- `lang` (str, default `"en"`) — Wikipedia language code (e.g., `en`, `de`, `fr`, `es`, `ja`)

**Implementation details:**
- Uses the MediaWiki API at `w/api.php` (`action=query&list=search`) for page search
- Uses the REST API at `/api/rest_v1/page/summary/` for article summaries
- Sets `User-Agent: ph_agent/1.0` header (required by Wikipedia)
- Handles disambiguation pages by returning the list of options
- Returns related search results as additional context
- Truncates extracts longer than 2000 characters

---

## ✅ 2. Yahoo Finance Tool — Implemented

**File:** `ph_agent/agent/tools/yahoo_finance_tool.py`  
**Tool name:** `yahoo_finance`  
**Dependencies:** `yfinance` (requires `pip install yfinance`)

Fetches stock quotes, historical prices, financial statements, and company information.

**Use cases:**
- "What's the current price of AAPL?"
- "Show me Tesla's revenue for the last 4 quarters"
- "What's the P/E ratio of Microsoft?"
- "Give me the dividend history of Coca-Cola"

**Parameters:**
- `symbol` (str, required) — Stock ticker symbol (e.g., `AAPL`, `TSLA`, `MSFT`)
- `operation` (str, default `"quote"`) — `quote`, `history`, `info`, `financials`, `dividends`, or `recommendations`
- `period` (str, default `"1mo"`) — Time period for history: `1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y`, `10y`, `ytd`, `max`

**Implementation details:**
- Lazy-imports `yfinance` with a clear error message if not installed
- Rate limited to max 1 call per 2 seconds to avoid IP throttling
- Handles invalid symbols gracefully with a clear error message
- `quote` returns current price, change, volume, market cap, P/E ratio
- `history` returns OHLCV records for the specified period
- `info` returns company overview (sector, employees, description, ratios)
- `financials` returns last 4 years of income statement data
- `dividends` returns the 20 most recent dividend payments
- `recommendations` returns recent analyst ratings

---

## ✅ 3. ECB Exchange Rates Tool — Implemented

**File:** `ph_agent/agent/tools/exchange_rate_tool.py`  
**Tool name:** `exchange_rate`  
**Dependencies:** `requests` (built-in), `xml.etree.ElementTree` (stdlib)

Fetches daily currency exchange rates from the European Central Bank.

**Use cases:**
- "What's the EUR/USD exchange rate today?"
- "Convert 1000 USD to GBP"
- "Show me the latest exchange rates"

**Parameters:**
- `base` (str, default `"EUR"`) — Base currency code (e.g., `EUR`, `USD`, `GBP`)
- `target` (str, optional) — Target currency for conversion. If omitted, returns all rates for base
- `amount` (float, optional) — Amount to convert (only used with `target`)

**Implementation details:**
- Fetches ECB's daily XML feed at `ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml`
- Parses XML with `xml.etree.ElementTree` (stdlib)
- Supports 30+ currencies with display names
- Computes cross-rates when base ≠ EUR
- Caches rates for 6 hours via `frappe.cache()` (ECB updates once per working day)
- Returns single conversion or full rate table

---

## ✅ 4. SEC Edgar Search Tool — Implemented

**File:** `ph_agent/agent/tools/sec_edgar_tool.py`  
**Tool name:** `sec_edgar`  
**Dependencies:** `requests` (built-in)

Looks up company CIK numbers and SEC filing metadata.

**Use cases:**
- "What is Apple's CIK number?"
- "Show me the latest 10-K filing for Microsoft"
- "When did Tesla file their last 10-Q?"

**Parameters:**
- `query` (str, required) — Company name (e.g., `Apple`, `Microsoft`) or CIK number (e.g., `320193`)
- `operation` (str, default `"search_cik"`) — `search_cik` or `latest_filings`
- `count` (int, default `5`, range 1–20) — Number of filings to return (only for `latest_filings`)

**Implementation details:**
- Uses SEC's public REST API at `efts.sec.gov`
- Sets proper `User-Agent` header (SEC requires identification)
- Rate limited to max 10 requests per second (100ms interval)
- `search_cik` returns CIK, ticker, SIC, location for matching companies
- `latest_filings` returns form type, filing date, description, and EDGAR URL
- Pads CIK numbers to 10 digits (SEC standard)

---

## ✅ 5. Stack Exchange Tool — Implemented

**File:** `ph_agent/agent/tools/stack_exchange_tool.py`  
**Tool name:** `stack_exchange`  
**Dependencies:** `requests` (built-in)

Searches questions and answers across Stack Overflow and the Stack Exchange network.

**Use cases:**
- "Find Stack Overflow answers about Python async/await"
- "How do I optimize a slow SQL query in ERPNext?"
- "Search for Frappe custom script examples"

**Parameters:**
- `query` (str, required) — Search query
- `site` (str, default `"stackoverflow"`) — Stack Exchange site (e.g., `stackoverflow`, `serverfault`, `superuser`, `askubuntu`)
- `tags` (str, optional) — Semicolon-separated tags to filter by (e.g., `python;sql`)
- `max_results` (int, default `5`, range 1–10) — Maximum results to return

**Implementation details:**
- Uses Stack Exchange API v2.3 at `api.stackexchange.com` (10k calls/day throttle, no key)
- Returns question title, score, answer count, accepted answer excerpt, view count, tags, and URL
- Fetches accepted answer body excerpt via a follow-up API call (HTML stripped)
- Supports tag filtering via the `tagged` parameter

---

## ✅ 6. Reddit Tool — Implemented

**File:** `ph_agent/agent/tools/reddit_tool.py`  
**Tool name:** `reddit`  
**Dependencies:** `requests` (built-in)

Searches subreddits, gets posts, comments, and trending topics.

**Use cases:**
- "What are people saying about ERPNext on Reddit?"
- "Show me the top posts from r/finance this week"
- "Search for discussions about AI in accounting"

**Parameters:**
- `query` (str, optional) — Search query (required for `search` operation)
- `subreddit` (str, default `"all"`) — Subreddit name (e.g., `python`, `finance`)
- `operation` (str, default `"search"`) — `search`, `hot`, or `top`
- `time_period` (str, default `"week"`) — Time period for `top`: `hour`, `day`, `week`, `month`, `year`, `all`
- `max_results` (int, default `5`, range 1–10) — Maximum results to return

**Implementation details:**
- Uses Reddit's public JSON API (append `.json` to any Reddit URL)
- Sets proper `User-Agent` header (Reddit requires identification)
- Rate limited to max 60 requests per minute (1s interval)
- Skips stickied posts
- Fetches top comment excerpt via a follow-up API call
- Returns title, score, upvote ratio, author, comment count, URL, selftext, and top comment

---

## ✅ 7. Hacker News Tool — Implemented

**File:** `ph_agent/agent/tools/hacker_news_tool.py`  
**Tool name:** `hacker_news`  
**Dependencies:** `requests` (built-in)

Searches stories, comments, and trending topics on Hacker News.

**Use cases:**
- "What's trending on Hacker News today?"
- "Show me the top stories about AI this week"
- "Search for discussions about Python 3.14"

**Parameters:**
- `operation` (str, default `"top_stories"`) — `top_stories`, `new_stories`, `best_stories`, or `search`
- `query` (str, optional) — Search keyword (required for `search` operation)
- `max_results` (int, default `5`, range 1–10) — Maximum results to return

**Implementation details:**
- Uses Firebase API at `hacker-news.firebaseio.com` for top/new/best stories
- Uses Algolia search API at `hn.algolia.com` for text search (both free, no key)
- Firebase path: fetches story IDs, then fetches individual item details
- Algolia path: returns full results directly with points, comments, and timestamps
- Returns title, URL, HN discussion link, score, author, comment count, and tags
