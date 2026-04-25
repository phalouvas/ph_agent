# PH Agent — Upcoming Features

This document lists planned features for future development of PH Agent, ordered by priority.

---

## 1. Web Search Tool

Enable the agent to search the web for current information.

**Use cases:**
- "What's the current EUR/USD exchange rate?"
- "What are the latest ERPNext release notes?"
- "Find the current market price for raw material X"

**Implementation notes:**
- Add a new tool in `ph_agent/agent/tools/` (e.g., `web_search_tool.py`)
- Could use a free API (DuckDuckGo, SerpAPI free tier) or a paid one (Google Custom Search, SerpAPI)
- Register in Tool Registry via a patch
- Consider rate limiting and caching to avoid excessive API costs

---

## 2. Agent-Proposed Skill Registry Creation

Let the agent create Skill Registry records on user request. The user asks the agent to teach itself about a domain, and the agent drafts a skill with `SKILL.md` content, resources, and optionally scripts. The created skill is **disabled by default** — an admin must review and enable it before it becomes active.

**Use cases:**
- "Create a skill that teaches you about our invoice approval process"
- "Learn our company's leave policy and create a skill for it"
- "Document the steps for onboarding a new customer as a skill"

**Implementation notes:**
- Add a new tool (e.g., `create_skill_tool`) that accepts: name, description, skill content (Markdown), optional resources, optional scripts
- The tool creates a Skill Registry record with `is_enabled = 0` (disabled)
- The agent responds with a confirmation message including the skill name and a note that it's disabled pending admin review
- Consider adding a `proposed_by_agent` flag for filtering in the desk UI
- The agent should not be able to enable skills — only create them disabled

---

## 3. Agent-Proposed Tool Registry Creation

Let the agent create Tool Registry records on user request. The user describes a tool they want, and the agent generates the Python code and parameters JSON Schema. The created tool is **disabled by default** — an admin must review and enable it before it becomes available to the agent.

**Use cases:**
- "Create a tool that shows all overdue invoices for a customer"
- "Make a tool that calculates the total sales for a given month"
- "Create a tool that sends a reminder email to customers with pending payments"

**Implementation notes:**
- Add a new tool (e.g., `create_tool_tool`) that accepts: name, description, Python code (the `run_tool()` function), parameters JSON Schema
- The tool creates a Tool Registry record with `script_type = "Custom Script"` and `is_enabled = 0` (disabled)
- The agent generates both the Python function and the correct JSON Schema for parameters
- The agent responds with a confirmation message including the tool name and a note that it's disabled pending admin review
- Consider adding a `proposed_by_agent` flag for filtering in the desk UI
- The agent should not be able to enable tools — only create them disabled

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
