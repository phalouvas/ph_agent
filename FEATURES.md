# PH Agent — Features

PH Agent is a Frappe app that integrates agentic AI chatbots into ERPNext, enabling autonomous, intelligent conversations and task automation within your business workflows.

---

## Table of Contents

- [1. AI Chat Interface](#1-ai-chat-interface)
- [2. Multi-LLM Provider System](#2-multi-llm-provider-system)
- [3. Agent Framework & Core Intelligence](#3-agent-framework--core-intelligence)
- [4. Tools System](#4-tools-system)
- [5. Skills System](#5-skills-system)
- [6. Memory & Context Providers](#6-memory--context-providers)
- [7. Conversation Management](#7-conversation-management)
  - [Temporary Sessions](#temporary-sessions)
- [8. File Handling](#8-file-handling)
- [9. Token Management & Auto-Summarization](#9-token-management--auto-summarization)
- [10. Tool Approval Workflow](#10-tool-approval-workflow)
- [11. Saved Prompts](#11-saved-prompts)
- [12. Real-Time Communication](#12-real-time-communication)
- [13. Security & Permissions](#13-security--permissions)
- [14. Configuration & Setup](#14-configuration--setup)

---

## 1. AI Chat Interface

A full-featured chat interface embedded in the ERPNext desk, powered by `vue-advanced-chat`.

| Feature | Description |
|---------|-------------|
| **Rich Chat UI** | Modern chat interface with message bubbles, timestamps, and sender indicators |
| **Real-Time Streaming** | Agent responses appear incrementally via WebSocket — no waiting for full responses |
| **Message Status Indicators** | Spinners during generation, error messages on failures, approval-waiting states |
| **Auto-Scroll** | Automatically scrolls to new content when near the bottom; respects manual scroll-up |
| **Shadow DOM Styling** | Custom styles injected into the chat component's shadow root for consistent theming |
| **Stop Generation** | Cancel ongoing AI generation with a red stop button |
| **Message Actions** | Hover over messages to reveal Edit, Delete, Select, and Regenerate options |

---

## 2. Multi-LLM Provider System

Configure multiple AI providers and switch between them per session.

| Feature | Description |
|---------|-------------|
| **Multiple Providers** | Configure any number of LLM providers (DeepSeek, OpenAI, Ollama, or any OpenAI-compatible API) |
| **API Configuration** | Per-provider settings: API key, API URL, default model, temperature |
| **Thinking/Reasoning Mode** | Enable DeepSeek's chain-of-thought reasoning with configurable reasoning effort |
| **Streaming Support** | Per-provider toggle for streaming responses |
| **Token Limits** | Configurable max output tokens, context length, and auto-summary threshold per provider |
| **File Size Limits** | Per-provider max file size for attachment extraction |
| **Default Provider** | Mark one provider as default for new sessions |
| **System Prompt** | Default system prompt inherited by all sessions; overridable per session |
| **Per-Session Overrides** | Change provider, temperature, thinking mode, and system prompt per session |

---

## 3. Agent Framework & Core Intelligence

The core agent system that powers all AI interactions.

| Feature | Description |
|---------|-------------|
| **Agent Framework** | Built on Microsoft's `agent-framework` library with OpenAI-compatible chat completions |
| **DeepSeek Reasoning** | Patched OpenAI client to extract `reasoning_content` from DeepSeek API — enables thinking mode with multi-turn tool calls |
| **Session State Persistence** | Full agent session state serialized and restored across restarts |
| **Response Post-Processing** | Automatically fixes LLM sentence concatenation issues (e.g., `"first.No"` → `"first. No"`) |
| **Streaming & Non-Streaming** | Supports both streaming (incremental chunks) and non-streaming (full response) modes |
| **Context Limit Validation** | Checks if conversation would exceed provider context length before making API calls |
| **Temperature Control** | Per-session temperature override for response creativity |
| **Follow-Up Suggestions** | Automatically generates contextual follow-up questions after each response |

---

## 4. Tools System

The agent can use tools to interact with Frappe/ERPNext data and perform computations.

### Built-in Tools

| Tool | Purpose | Capabilities |
|------|---------|-------------|
| **show_datetime** | Display current date/time | Format options: ISO, full, short, custom strftime |
| **calculate** | Math operations | Add, subtract, multiply, divide, percentage, power, sqrt, log, circle geometry |
| **query_frappe_data** | Read Frappe data | `get_all`, `get_doc`, `count` with filters, fields, ordering, pagination |
| **create_frappe_record** | Create records | Whitelist-based doctype validation; permission checks |
| **update_frappe_record** | Update records | Partial field updates with validation |
| **delete_frappe_record** | Delete/cancel records | Soft-delete (cancel) or permanent delete with validation |
| **run_frappe_method** | Call whitelisted APIs | Calls dotted Frappe methods; blocks dangerous methods |
| **discover_frappe_schema** | Inspect DocTypes | List doctypes by pattern, get full field metadata and schema |
| **web_search** | Search the web | DuckDuckGo search with result count, date range, and domain filtering |
| **wikipedia** | Look up Wikipedia articles | Fetches article summaries in multiple languages; handles disambiguation |
| **yahoo_finance** | Retrieve financial data | Stock quotes, historical prices, financial statements, dividends, analyst ratings |
| **exchange_rate** | Get currency exchange rates | Live ECB rates for 30+ currencies; cross-rate conversion |
| **sec_edgar** | Search SEC filings | Company CIK lookup and latest 10-K/10-Q filing metadata |
| **stack_exchange** | Search Q&A forums | Stack Overflow and Stack Exchange network search with tag filtering |
| **reddit** | Browse Reddit | Search posts, hot/trending topics, and top comments across subreddits |
| **hacker_news** | Explore Hacker News | Top, new, and best stories with Algolia-powered search |

### Tool Registry (DocType)

| Feature | Description |
|---------|-------------|
| **Existing Function** | Import Python tools from dotted paths (e.g., `ph_agent.agent.tools.datetime_tool.show_datetime_tool`) |
| **Custom Script** | Inline Python code with mandatory `run_tool()` function; runs in a restricted safe namespace |
| **Server Script** | Link to a Frappe Server Script — reads its script content at runtime |
| **Parameters JSON** | JSON Schema defining tool input parameters; auto-builds typed input models |
| **Approval Flag** | Mark tools as requiring human approval before execution |
| **Enable/Disable** | Toggle tools on/off to include or exclude them from the agent |
| **Cache Invalidation** | Tool cache automatically invalidated on create, update, or delete |

---

## 5. Skills System

A **progressive disclosure** system that teaches the AI how to perform domain-specific tasks. Skills combine high-level instructions with reference resources and executable scripts.

### Skill Sources

| Source | Description |
|--------|-------------|
| **DocType-Based** | Create records in the **Skill Registry** with rich content, resources, and scripts |
| **File-Based** | Place skill folders under `private/files/skills/<skill-name>/` on your site — must contain at least a `SKILL.md` |

If a file-based skill has the same name as a DocType-based skill, the DocType version takes precedence.

### Skill Structure

Each skill can contain:

| Component | Description |
|-----------|-------------|
| **SKILL.md** | Required: Markdown with YAML frontmatter (`name`, `description`). Contains instructions the AI reads to understand when and how to use the skill |
| **Resources** | Supplementary reference material — static Markdown text or dynamic Python functions that return content at runtime |
| **Scripts** | Executable Python scripts — in-process functions (imported callable) or file references (subprocess with 30s timeout) |

### Sample Skill

PH Agent ships with a `frappe-data-query` sample skill that teaches the AI to query Frappe/ERPNext data safely. It is seeded automatically during migration.

---

## 6. Memory & Context Providers

The agent maintains persistent memory across conversations to learn user preferences and recall important context.

### LLM Memory Provider

| Feature | Description |
|---------|-------------|
| **Fact Extraction** | Uses the LLM to extract facts from conversation turns (categories: Fact, Preference, Goal, Context, Personal, Other) |
| **Confidence Scoring** | Each memory fact has a 0.0–1.0 confidence score; only facts ≥ 0.6 are injected |
| **Relevance Filtering** | Matches memories to the current user query using word-overlap scoring; top 15 most relevant memories are injected |
| **Rate Limiting** | Extraction limited to once per 30 seconds per user to avoid overhead |
| **Persistence** | Stored in the **User Memory** DocType per user |
| **Deduplication** | Avoids storing duplicate facts; updates confidence and encounter count on re-occurrence |
| **Context Integration** | High-confidence memories are injected as system instructions before each turn |

### User Preference Provider

| Feature | Description |
|---------|-------------|
| **Preference Detection** | Regex patterns detect user name, date format, language, response style, timezone from conversation |
| **Confidence Scoring** | Each pattern has a confidence level (0.4–0.8) |
| **Storage** | JSON field in the **User Preference** DocType per user |
| **Cross-Session** | Preferences are shared across all sessions for the same user |
| **Injection** | Top 20 preferences formatted into system instructions |

### Cross-Session Context

| Feature | Description |
|---------|-------------|
| **Recent Session Summaries** | Loads summaries from the 3 most recent sessions to provide continuity |
| **Context Instruction** | Injected as a system instruction: "Previous conversation context from recent sessions — use for continuity but do not mention explicitly" |
| **Fallback** | Falls back to the first user message if no summary exists |

---

## 7. Conversation Management

Full session and message management capabilities.

| Feature | Description |
|---------|-------------|
| **Session Management** | Create, browse, rename, and delete chat sessions from the chat UI |
| **Auto-Generated Titles** | After the first exchange, the LLM generates a concise title for the session automatically |
| **Message History** | Full message history loaded on every turn for contextual replies |
| **Message Editing** | Edit your own messages; subsequent messages are automatically deleted and the agent regenerates its response |
| **Message Deletion** | Delete individual messages or batch delete selected messages |
| **Message Regeneration** | Regenerate agent responses with a single click — the message stays in place with a spinner |
| **Conversation Summarization** | Manually trigger summarization of selected or all messages in a session |
| **Session State Recovery** | Full agent state is persisted and restored, enabling seamless continuation after page reloads |
| **Temporary Sessions** | Toggle a session as temporary with the 👻 button — it will be auto-deleted when you navigate away, switch rooms, or close the tab. An hourly scheduled job cleans up any orphaned temporary sessions. Messages, memories, and tool approvals are all cascade-deleted. |

### Temporary Sessions

Temporary sessions behave identically to normal sessions during their lifetime — messages are saved, memories are extracted, and all features work as expected. The difference is purely a cleanup concern:

| Aspect | Behavior |
|--------|----------|
| **Toggle** | Click the 👻 button in the page actions to mark the current session as temporary or permanent |
| **Auto-Delete on Navigation** | Switching to another room or creating a new chat automatically deletes the previous temporary session |
| **Auto-Delete on Tab Close** | Closing the browser tab fires a `sendBeacon` request to delete the active temporary session |
| **Hourly Cleanup** | A scheduled job deletes any temporary sessions older than 1 hour (safety net for browser crashes) |
| **Cascade Deletion** | Deleting a temporary session removes all its messages, attached files, user memories, and tool approval requests |
| **Cross-Session Context** | Temporary session summaries are excluded from cross-session context injection into new sessions |

---

## 8. File Handling

Attach files to chat messages and have the agent automatically read their content.

| Feature | Description |
|---------|-------------|
| **File Attachments** | Attach files to chat messages via the paperclip icon |
| **Automatic Extraction** | Files are automatically converted to Markdown text using the `markitdown` library |
| **Supported Formats** | PDF, DOCX, PPTX, XLSX, XLS, HTML, CSV, JSON, XML, EPUB, TXT |
| **Size Limits** | Configurable per provider (default: 50 MB) |
| **Frappe File Records** | Files stored as Frappe `File` records linked to the chat message |
| **Cascade Delete** | Deleting a chat message also deletes its attached files |
| **Graceful Handling** | Missing files, unsupported formats, and oversized files are handled gracefully with clear messages |

---

## 9. Token Management & Auto-Summarization

Intelligent token tracking to stay within context limits.

| Feature | Description |
|---------|-------------|
| **Token Tracking** | Input and output tokens tracked per message and accumulated per session |
| **Context Window** | Respects the provider's context length (default: 128,000 tokens) |
| **Max Output Tokens** | Configurable per provider (default: 32,768 tokens) |
| **Context Limit Validation** | Throws an error before making an API call if the conversation would exceed the context limit |
| **Token Warnings** | Real-time alerts when approaching 75% of context capacity |
| **Auto-Summarization** | Automatically summarizes the conversation when tokens exceed 85% of the context window |
| **Summary Cooldown** | Prevents re-summarization within 60 seconds |
| **Token Reset** | Estimated conversation tokens reset to 0 after a successful summary |
| **Emergency Fallback** | If summarization fails at 95%+ tokens, oldest non-summary messages are deleted |
| **Real-Time Updates** | Token count updates published via WebSocket |

---

## 10. Tool Approval Workflow

Human-in-the-loop approval for sensitive tool executions.

| Feature | Description |
|---------|-------------|
| **Approval Requests** | When the agent wants to call a tool marked as requiring approval, a **Tool Approval Request** record is created |
| **Approval UI** | Administrators approve or reject requests directly from the Tool Approval Request form |
| **Conversation State** | Full agent session state is saved in the approval request for seamless continuation |
| **Post-Approval Execution** | Approved tools are executed automatically and the conversation resumes |
| **Rejection Handling** | Rejected tool calls are communicated back to the agent |
| **Auto-Cancellation** | Pending approval requests are automatically cancelled when the parent session or message is deleted |

---

## 11. Saved Prompts

Reusable prompt templates with variable substitution.

| Feature | Description |
|---------|-------------|
| **Prompt Templates** | Save prompts with `{{variable}}` placeholders for reuse |
| **Categories** | Organize prompts by user-defined categories |
| **Favorites** | Mark prompts as favorites for quick access |
| **Variable Substitution** | When inserting a saved prompt, a form is displayed to fill in variable values |
| **Usage Tracking** | Auto-incremented usage count to track popular prompts |

---

## 12. Real-Time Communication

All real-time events are delivered via Frappe's built-in WebSocket system.

| Event | Purpose |
|-------|---------|
| `new_message` | A new message has been posted to the session |
| `message_chunk` | Streaming chunk of an agent response |
| `reasoning_chunk` | Streaming chunk of the LLM's thinking/reasoning process |
| `token_update` | Current token count and context usage percentage |
| `token_warning` | Warning when approaching context limits |
| `agent_status` | Status updates (e.g., "Calling AI…", "Extracting files…") |
| `generation_cancelled` | User has cancelled ongoing generation |
| `approval_needed` | Agent is requesting tool approval |
| `approval_resolved` | Tool approval has been granted or denied |
| `suggestions_ready` | Follow-up question suggestions are available |
| `message_edited` | A message has been edited and subsequent messages deleted |
| `session_renamed` | Session title has been auto-generated |

---

## 13. Security & Permissions

| Aspect | Description |
|--------|-------------|
| **Blocked DocTypes** | The agent cannot create, update, or delete sensitive system DocTypes (User, DocType, Server Script, File, Workflow, etc.) |
| **Read-Only DocTypes** | Certain DocTypes are read-only (ToDo, Note, Comment, Activity Log, etc.) |
| **Tool Allowlist** | Write operations are restricted to an explicit allowlist of permitted DocTypes |
| **Script Sandboxing** | Custom scripts run in a restricted namespace without `exec`, `eval`, `__import__`, or `open` |
| **Script Approval** | Skills require user approval before executing scripts by default |
| **Session Locking** | Per-session cache lock prevents concurrent message processing |
| **Cancellation** | Users can cancel generation at any time; cancellation is cooperative and graceful |

---

## 14. Configuration & Setup

| Feature | Description |
|---------|-------------|
| **Dependencies** | `agent-framework`, `agent-framework-core`, `agent-framework-openai`, `markitdown[pdf,docx,pptx,xlsx,html]` |
| **Installation Hook** | After migration, sample skills are seeded and the `private/files/skills/` directory is created |
| **Cache Invalidation** | Tool and skill caches are automatically invalidated on DocType changes |
| **CSS & JS Includes** | Chat UI styles and scripts are automatically loaded in the ERPNext desk |
| **Pre-commit** | Ruff, ESLint, Prettier, and PyUpgrade configured for code quality |
