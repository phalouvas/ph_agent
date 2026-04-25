# PH Agent — Upcoming Features

This document lists planned features for future development of PH Agent, ordered by priority.

---

## ~~1. Web Search Tool~~ ✅ Implemented

~~Enable the agent to search the web for current information.~~

**Use cases:**
- ~~"What's the current EUR/USD exchange rate?"~~
- ~~"What are the latest ERPNext release notes?"~~
- ~~"Find the current market price for raw material X"~~

**Implementation:**
- Tool: `ph_agent/agent/tools/web_search_tool.py` — `@tool(name="web_search")` using the `ddgs` library
- Parameters: `query` (required), `max_results` (default 5, capped 1–10), `date_range` (day/week/month/year), `domain_filter` (comma-separated domains)
- Registered in Tool Registry via `ph_agent/patches/v16_0/seed_tool_registry.py`
- Lazy-imports `ddgs` for graceful degradation if not installed

---

## ~~2. Agent-Proposed Skill Registry Creation~~ ✅ Implemented

~~Let the agent create Skill Registry records on user request. The user asks the agent to teach itself about a domain, and the agent drafts a skill with `SKILL.md` content, resources, and optionally scripts. The created skill is **disabled by default** — an admin must review and enable it before it becomes active.~~

**Use cases:**
- ~~"Create a skill that teaches you about our invoice approval process"~~
- ~~"Learn our company's leave policy and create a skill for it"~~
- ~~"Document the steps for onboarding a new customer as a skill"~~

**Implementation:**
- Tool: `ph_agent/agent/tools/create_skill_tool.py` — `@tool(name="create_skill")`
- Parameters: `skill_name` (required, lowercase/hyphens, 64 chars max), `description` (required, 1024 chars max), `content` (required, Markdown), `resources` (optional JSON array), `scripts` (optional JSON array)
- Validates all inputs against the same rules as the Skill Registry controller (regex, length limits, duplicate check)
- Creates Skill Registry record with `is_enabled = 0` (always disabled)
- Uses `doc.insert()` (no `ignore_permissions`) — respects Frappe permissions (System Manager role required)
- Registered in Tool Registry via `ph_agent/patches/v16_0/seed_tool_registry.py`
- Skill Registry added to `BLOCKED_DOCTYPES` in `frappe_crud_tool.py` to prevent CRUD bypass

---

## 3. Agent-Proposed Tool Registry Creation

Let the agent create Tool Registry records on user request. The user describes a tool they want, and the agent generates the Python code and parameters JSON Schema. The created tool is **disabled by default** — an admin must review and enable it before it becomes active.

**Use cases:**
- "Create a tool that shows all overdue invoices for a customer"
- "Make a tool that calculates the total sales for a given month"
- "Create a tool that sends a reminder email to customers with pending payments"

**Implementation notes:**
- Add a new tool (e.g., `create_tool_tool`) following the same pattern as `create_skill_tool`:
  - `@tool(name="create_tool")` decorator with `ctx: FunctionInvocationContext = None`
  - Parameters: `tool_name` (required, lowercase/hyphens), `description` (required), `script_type` (required, "Existing Function" or "Custom Script"), `python_function` (conditional), `custom_script` (conditional), `parameters_json` (conditional)
  - Validates inputs against Tool Registry field rules
  - Creates Tool Registry record with `is_enabled = 0` (always disabled)
  - Uses `doc.insert()` (no `ignore_permissions`) — respects Frappe permissions
  - The agent generates both the Python function code and the correct JSON Schema for parameters
  - The agent responds with a confirmation message including the tool name and a note that it's disabled pending admin review
- Add "Tool Registry" to `BLOCKED_DOCTYPES` in `frappe_crud_tool.py` to prevent CRUD bypass

---

## 4. Multi-Modal Input (Vision)

Support image attachments so the agent can analyze screenshots, photos, diagrams, and charts.

**Use cases:**
- Upload a screenshot of an error message and ask the agent what it means
- Take a photo of a receipt and have the agent extract line items
- Upload a chart and ask for analysis

**Implementation notes:**
- Extend the file attachment system in `api/chat.py` to accept images (PNG, JPG, JPEG, GIF, WebP)
- Pass image data to vision-capable models (DeepSeek-VL, GPT-4V, etc.)
- Update the LLM Provider DocType to flag which providers support vision
- Update the chat UI to display image thumbnails inline
- Handle size limits and format validation

---

## 5. Conversation Branching

Let users branch off from any point in a conversation to explore alternative paths.

**Use cases:**
- Ask "What if we used a different supplier?" and explore that path without losing the original thread
- Compare two analytical approaches side-by-side
- Revisit a previous decision point and try a different direction

**Implementation notes:**
- Add a "Branch" action to messages in the chat UI
- When branching, create a new Chat Session that inherits the conversation history up to that point
- Display branched sessions in a tree or tabbed view
- Allow users to switch between branches and compare outcomes
- Consider a visual indicator showing which branch is currently active

---

## 6. Voice Input

Enable hands-free interaction using speech-to-text.

**Use cases:**
- Ask questions while working in a warehouse or on the shop floor
- Dictate complex queries without typing
- Accessibility for users who cannot type easily

**Implementation notes:**
- Use the browser's built-in Web Speech API (`SpeechRecognition`) — no external dependencies
- Add a microphone button to the chat input area
- Show a recording indicator while listening
- Transcribe speech to text and submit as a normal message
- Handle browser compatibility and permission prompts
- Consider adding a "push-to-talk" mode for noisy environments
