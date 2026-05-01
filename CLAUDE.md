# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common commands

```bash
# Run all tests (requires Frappe bench site)
bench --site <site> run-tests --app ph_agent

# Run a single test module
bench --site <site> run-tests --app ph_agent --module ph_agent.ph_agent.doctype.tool_registry.test_tool_registry

# Lint and format (auto-runs via pre-commit, but can run manually)
ruff check ph_agent/
ruff format ph_agent/
prettier --write ph_agent/public/js/ ph_agent/ph_agent/
eslint ph_agent/public/js/ ph_agent/ph_agent/

# Install pre-commit hooks (required before first commit)
pre-commit install

# Build (Flit — only for packaging, dev uses bench)
flit build
```

## Architecture

This is a **Frappe v16 app** for AI chatbots in ERPNext. The core flow:

1. **User sends message** → `api/chat.py:send_message()` stores it as a `Chat Message` DocType, then enqueues a background job
2. **Background job** → `api/agent_jobs.py:_call_agent_background()` handles file extraction, streaming/non-streaming LLM calls, token tracking, auto-summarization, follow-up suggestions, and title generation
3. **Agent** → `agent/framework_agent.py:_build_agent()` assembles the full agent with:
   - `OpenAIChatCompletionClient` from `agent-framework-openai` (patched for DeepSeek compatibility)
   - `FrappeMemoryProvider` — conversation history from `Chat Message` DocTypes (no `InMemoryHistoryProvider` — having both duplicates messages)
   - `SkillsProvider` — merges DocType-based skills (Skill Registry) and file-based skills (`private/files/skills/`)
   - `LLMMemoryProvider` — long-term memory extracted from conversations
   - `UserPreferenceProvider` — learned user preferences per persona
   - Hook-registered context providers via `ph_agent_context_providers` hook
4. **Tools** → `agent/tools/tool_manager.py:ToolManager` loads enabled tools from the Tool Registry DocType, caches them, filters by persona/session tool groups
5. **Real-time** → `frappe.publish_realtime()` pushes streaming chunks, status updates, token counters, and approval requests to the browser via WebSockets

### Key DocTypes

| DocType | Purpose |
|---------|---------|
| `Chat Session` | Conversation container; holds persona, provider, tool groups, session state, token counts |
| `Chat Message` | Individual messages; stores reasoning_content for DeepSeek thinking mode |
| `LLM Provider` | API key, URL, model, pricing, context limits |
| `Persona` | System prompt, tool groups, default provider, routing settings |
| `Tool Registry` | Python function or custom script wrapped as agent-callable tools |
| `Tool Approval Request` | Pending tool approvals with conversation state for resumption |
| `Skill Registry` | Domain-specific skills with resources and scripts (progressive disclosure) |
| `User Token Usage` | Per-user aggregate token counts and costs |
| `User Memory` / `User Preference` | Auto-extracted long-term facts and learned preferences |

### Front-end

The chat UI is `ph_agent/ph_agent/page/chat/chat.js` (loaded via `hooks.py:page_js`). It uses `vue-advanced-chat` and receives real-time events for streaming. Front-end modules are in `public/js/chat/modules/`. Formatting conversion from standard Markdown to vue-advanced-chat delimiters happens server-side in `_convert_formatting_for_vue_chat()`.

### Session state persistence

`AgentSession.state` (Microsoft Agent Framework serialization) is persisted to `Chat Session.session_state` after every turn via `_save_session_state()`. It's restored via `_load_session_state()` using `AgentSession.from_dict()` which properly deserializes `SerializationProtocol` objects. State is cleared when a session is closed or archived (`chat_session.py` `before_save()`). During regeneration, `skip_session_state=True` prevents stale state from leaking in.

## Important constraints

### Frappe conventions
- All API methods must be `@frappe.whitelist()`. Permission checks use `frappe.has_permission()`.
- Never add `frappe` as a dependency in `pyproject.toml` — it's managed by bench.
- Enable hooks in `hooks.py` only when the corresponding methods exist — empty hooks crash app boot.
- Background jobs enqueued via `frappe.enqueue()` must check cancellation flags (`frappe.cache().get_value("ph_agent:cancel:{session}")`) for cooperative cancellation.
- Use `doc_events` in `hooks.py` for Document lifecycle hooks (on_update, on_trash, after_insert).
- Database migrations go in `ph_agent/patches/vX_Y_Z/` and are registered in `ph_agent/patches.txt`.

### Agent framework
- This uses the **Microsoft Agent Framework** (`agent-framework`, `agent-framework-openai`, `agent-framework-core`).
- The `FrappeMemoryProvider` handles ALL conversation history. Do NOT add `InMemoryHistoryProvider` — having both duplicates messages and produces malformed conversations (orphaned tool_calls).
- `ToolManager` rebuilds tools from the database on every call (FunctionTool objects can't be pickled). Only metadata is cached.

### DeepSeek compatibility
- `_framework_agent.py` monkey-patches `agent_framework_openai` to handle DeepSeek's `reasoning_content` field (vs standard `reasoning_details`).
- Tool schemas include `additionalProperties: false` to help DeepSeek populate required parameters correctly.
- Reasoning content is persisted in `Chat Message.reasoning_content` and echoed back in subsequent requests (required by DeepSeek's thinking mode).
- Thinking mode is disabled when `temperature` is set (formats conflict with DeepSeek).

### Per-session locking
- `ph_agent:lock:{session}` (frappe cache) prevents concurrent processing within a session.
- `ph_agent:cancel:{session}` allows cooperative cancellation of in-progress generation.
- `ph_agent:job:{session}` tracks the RQ job ID for cancellation via `send_stop_job_command`.

### Code style
- Tabs for Python/JS/Vue/CSS/SCSS/HTML; spaces only for JSON (indent 1).
- Double quotes for Python. Maximum line length 110 chars for Python, 99 for others.
- Ruff handles Python formatting/linting; Prettier for JS/Vue; ESLint for JS linting.
- Pre-commit is mandatory — install via `pre-commit install`.

## Additional context

The `.github/copilot-instructions.md` file contains complementary guidelines about front-end patterns (MutationObserver, conditional auto-scroll), session state serialization, and the tool approval workflow — consult it for those details.
