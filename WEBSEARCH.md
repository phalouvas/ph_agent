# PH Agent — Web Search & Online Tools

This document lists additional web search and online data tools for future implementation, ordered by priority. All tools listed here are **free and require no API key**.

---

## 1. Wikipedia Tool

Fetch clean, structured article content from Wikipedia.

**Use cases:**
- "Tell me about just-in-time manufacturing"
- "What is the capital of Bhutan?"
- "Explain the Toyota Production System"

**Implementation notes:**
- Add a new tool in `ph_agent/agent/tools/` (e.g., `wikipedia_tool.py`)
- Use the Wikipedia REST API at `en.wikipedia.org/api/rest_v1/` — no key required
- Return article summaries, infobox data, and related categories
- Handle disambiguation pages by returning the list of options
- Consider a `lang` parameter for multi-language support (default: `en`)
- No external dependencies — uses `requests` (already available in Frappe)

---

## 2. Yahoo Finance Tool

Fetch stock quotes, historical prices, financial statements, and company information.

**Use cases:**
- "What's the current price of AAPL?"
- "Show me Tesla's revenue for the last 4 quarters"
- "What's the P/E ratio of Microsoft?"
- "Give me the dividend history of Coca-Cola"

**Implementation notes:**
- Add a new tool in `ph_agent/agent/tools/` (e.g., `yahoo_finance_tool.py`)
- Use the `yfinance` Python library — `pip install yfinance`, no API key
- Support multiple operations: `quote`, `history`, `info`, `financials`, `dividends`, `recommendations`
- Accept a `symbol` parameter (e.g., `AAPL`, `TSLA`, `MSFT`)
- Accept an `operation` parameter to select the data type
- Handle invalid symbols gracefully with a clear error message
- Add rate limiting to avoid IP throttling (max 1 call per 2 seconds)
- Note: `yfinance` is an unofficial scraper — Yahoo could break it at any time

---

## 3. ECB Exchange Rates Tool

Fetch daily currency exchange rates from the European Central Bank.

**Use cases:**
- "What's the EUR/USD exchange rate today?"
- "Convert 1000 USD to GBP"
- "Show me the latest exchange rates"

**Implementation notes:**
- Add a new tool in `ph_agent/agent/tools/` (e.g., `exchange_rate_tool.py`)
- Use the ECB's free XML feed at `ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml` — no key required
- Parse the XML to get rates for 30+ currencies against EUR
- Support a `base` parameter (default: `EUR`) and `target` parameter for conversion
- Cache the rates for 6 hours (they only update once per working day)
- No external dependencies — uses `xml.etree.ElementTree` (stdlib) and `requests`

---

## 4. SEC Edgar Search Tool

Look up company CIK numbers and SEC filing metadata.

**Use cases:**
- "What is Apple's CIK number?"
- "Show me the latest 10-K filing for Microsoft"
- "When did Tesla file their last 10-Q?"

**Implementation notes:**
- Add a new tool in `ph_agent/agent/tools/` (e.g., `sec_edgar_tool.py`)
- Use the SEC's public REST API at `efts.sec.gov` — no key required
- Support operations: `search_cik` (find CIK by company name), `latest_filings` (get recent filings by CIK)
- Return filing type, date, description, and EDGAR URL
- Set a proper `User-Agent` header (SEC requires identification)
- Handle rate limiting (SEC allows 10 requests per second)
- No external dependencies — uses `requests`

---

## 5. Stack Exchange Tool

Search questions and answers across Stack Overflow and the Stack Exchange network.

**Use cases:**
- "Find Stack Overflow answers about Python async/await"
- "How do I optimize a slow SQL query in ERPNext?"
- "Search for Frappe custom script examples"

**Implementation notes:**
- Add a new tool in `ph_agent/agent/tools/` (e.g., `stack_exchange_tool.py`)
- Use the Stack Exchange REST API at `api.stackexchange.com` — no key required (10k calls/day throttle)
- Support a `site` parameter (default: `stackoverflow`; options: `serverfault`, `superuser`, etc.)
- Return question title, score, answer count, accepted answer excerpt, and URL
- Filter by `tags` parameter for targeted searches
- No external dependencies — uses `requests`

---

## 6. Reddit Tool

Search subreddits, get posts, comments, and trending topics.

**Use cases:**
- "What are people saying about ERPNext on Reddit?"
- "Show me the top posts from r/finance this week"
- "Search for discussions about AI in accounting"

**Implementation notes:**
- Add a new tool in `ph_agent/agent/tools/` (e.g., `reddit_tool.py`)
- Append `.json` to any Reddit URL — no key required for read-only access
- Support operations: `search` (search posts by query), `hot` (hot posts from a subreddit), `top` (top posts by time period)
- Return post title, score, comment count, author, URL, and top comment excerpt
- Set a proper `User-Agent` header (Reddit requires identification)
- Handle rate limiting (60 requests per minute)
- No external dependencies — uses `requests`

---

## 7. Hacker News Tool

Search stories, comments, and trending topics on Hacker News.

**Use cases:**
- "What's trending on Hacker News today?"
- "Show me the top stories about AI this week"
- "Search for discussions about Python 3.14"

**Implementation notes:**
- Add a new tool in `ph_agent/agent/tools/` (e.g., `hacker_news_tool.py`)
- Use the Firebase API at `hacker-news.firebaseio.com` — no key required
- Support operations: `top_stories`, `new_stories`, `best_stories`, `search`
- Return story title, score, author, comment count, and URL
- Use Algolia search API (`hn.algolia.com`) for text search — also free and no key
- No external dependencies — uses `requests`
