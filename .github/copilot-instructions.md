# Project Guidelines

## Code Style
- **Indentation**: Use tabs for Python, JavaScript, Vue, CSS, SCSS, HTML files (configured in `.editorconfig`). Use spaces only for JSON files (indent size 1).
- **Line length**: Maximum 110 characters for Python (configured in `pyproject.toml`), 99 for other languages (`.editorconfig`). Ruff will enforce this.
- **Formatting**: Use Ruff for Python formatting and linting. Use Prettier for JavaScript/Vue/SCSS. Use ESLint for JavaScript linting.
- **Imports**: Use Ruff's import sorter (I rule). Unused imports are allowed (`F401` ignored) but should be cleaned up.
- **Quotes**: Double quotes for Python strings (Ruff format `quote-style = "double"`).
- **Naming**: Avoid ambiguous variable names (`E741` ignored) but aim for clarity.

Refer to `.editorconfig`, `.pre-commit-config.yaml`, and `pyproject.toml` for detailed configurations.

## Architecture
- This is a **Frappe v16 app** that integrates agentic AI chatbots into ERPNext.
- **Key integration points** are defined in `ph_agent/hooks.py` (document events, scheduled tasks, permission queries, method overrides, installation hooks). Some hooks are already active:
  - `doc_events` for Tool Registry, Chat Session, and Chat Message
  - `app_include_css` for chat styles
  - `page_js` for chat UI components
  Enable additional hooks only when you have implemented the corresponding methods.
- **Directory structure**:
  - `ph_agent/config/` – UI configuration (empty)
  - `ph_agent/patches/` – Database migrations (empty)
  - `ph_agent/ph_agent/doctype/` – DocTypes: `Chat Session`, `Chat Message`, `LLM Provider`, `Tool Registry`
  - `ph_agent/ph_agent/page/chat/` – Chat UI implementation (`chat.js`)
  - `ph_agent/public/` – Front‑end assets (`css/chat.css`)
  - `ph_agent/templates/` – Website pages (empty)
  - `ph_agent/api/` – API endpoints (`chat.py`, `agent_jobs.py`)
  - `ph_agent/ph_agent/agent/` – AI agent implementation (`framework_agent.py`)
  - `ph_agent/ph_agent/agent/tools/` – Tool management (`tool_manager.py`, `calculator_tool.py`, `datetime_tool.py`)
- **Dependencies** are managed via `pyproject.toml`. **Never** add `frappe` as a dependency (it’s installed and managed by bench). Add only app‑specific packages (e.g., `agent‑framework`, `agent‑framework‑openai`, `markitdown[pdf,docx,pptx,xlsx,html]`).
- **Frappe conventions**: Use `@frappe.whitelist()` for API methods; follow Frappe’s document lifecycle.
- **Real‑time communication**: Use `frappe.publish_realtime()` for WebSocket events (agent status, new messages).
- **Background jobs**: Use `frappe.enqueue()` for long‑running tasks (LLM calls, PDF extraction).
- **Session state persistence**: The `AgentSession.state` from Microsoft Agent Framework is persisted to the `Chat Session` DocType after every turn (sync and streaming). It is loaded before each agent run to preserve memory, skills, and RAG context across conversations. State is automatically cleared when a session is closed or archived (see `chat_session.py` `before_save()`). The `FrappeMemoryProvider` reads message history from the DocType and does not write to state, so only data populated by tools/providers persists.

## Build and Test
- **Installation** (see [README.md](../README.md)):
  ```bash
  bench get‑app <url> --branch version‑16
  bench install‑app ph_agent
  ```
- **Development setup**:
  ```bash
  cd apps/ph_agent
  pre‑commit install   # enables pre‑commit hooks
  ```
- **Testing** (no tests yet):
  ```bash
  bench test‑site --app ph_agent
  ```
- **Build system**: Flit (PEP 517/518). Python 3.14+ required (configured in `pyproject.toml`).
- **Code quality**: Pre‑commit hooks run Ruff, ESLint, Prettier, pyupgrade, etc. Always run `pre‑commit install` after cloning.

## Conventions
- **Dependency management**: Add Python packages only to `[project.dependencies]` in `pyproject.toml`. Development dependencies go under `[tool.bench.dev‑dependencies]`. APT dependencies for Frappe Cloud go under `[deploy.dependencies.apt]`.
- **Hooks**: Enable hooks in `hooks.py` only when you have implemented the corresponding methods. Empty hooks will crash the app boot.
- **Database transactions**: Frappe auto‑commits; use explicit rollback where needed.
- **Code quality**: Pre‑commit is mandatory; ensure all hooks pass before committing.
- **Front‑end patterns**:
  - Use `MutationObserver` for DOM manipulation when integrating with third‑party components (e.g., hiding regenerate button on user messages).
  - Handle real‑time events with `frappe.realtime.on()`.
  - Use optimistic UI updates for better user experience.
  - Implement conditional auto‑scroll for streaming responses (see `uiHelpers.js` and `realtimeListeners.js`).
- **Session state**:
  - `Chat Session` has two fields: `session_state` (Code/JSON, read_only) and `last_state_update` (Datetime, read_only).
  - State is serialized via `AgentSession.to_dict()` which preserves `SerializationProtocol` type info for proper round‑trip deserialization (including `InMemoryHistoryProvider` messages).
  - State is restored via `AgentSession.from_dict()` which reconstructs `SerializationProtocol` objects (e.g., `Message` instances) from the stored JSON.
  - State is saved every turn for continuity across requests.
- **Avoid pitfalls**:
  - Do **not** add `frappe` to dependencies.
  - Always decorate API methods with `@frappe.whitelist()`.
  - Do not mix spaces and tabs (Ruff will reject).
  - Do not enable empty hooks.
  - Background jobs should check cancellation flags (`frappe.cache().get_value()`) for cooperative cancellation.
  - Ensure proper locking (`frappe.cache().set_value()`) for per‑session concurrent processing.
  - When working with DeepSeek API, include `additionalProperties: false` in tool schemas and handle `reasoning_content` field for thinking mode.

## Reference Files
| File | Purpose |
|------|---------|
| `pyproject.toml` | Dependencies, build config, Ruff settings |
| `ph_agent/hooks.py` | Frappe integration points (examples) |
| `.pre‑commit‑config.yaml` | Quality gate automation |
| `.editorconfig` | Indentation rules |
| `README.md` | Installation and feature guide |
| `ph_agent/api/chat.py` | Chat session and message API endpoints |
| `ph_agent/api/agent_jobs.py` | Background job for LLM calls |
| `ph_agent/ph_agent/agent/framework_agent.py` | LLM agent implementation |
| `ph_agent/ph_agent/agent/tools/tool_manager.py` | Tool registration and caching |
| `ph_agent/ph_agent/doctype/tool_registry/tool_registry.py` | Tool Registry DocType controller |
| `ph_agent/ph_agent/doctype/chat_session/chat_session.py` | Chat Session DocType controller (state cleanup on close/archive) |
| `ph_agent/ph_agent/page/chat/chat.js` | Chat UI front‑end |
| `ph_agent/public/css/chat.css` | Chat UI styles |

**Link, don’t embed**: Consult the existing documentation (README, license) and Frappe framework documentation for broader context.

## Tool Management
- **Tool Registry**: Register Python functions as AI‑callable tools via the Tool Registry DocType.
- **Tool Manager**: The `ToolManager` class loads, caches, and injects context into tools from the registry.