Microsoft Agent References.
https://learn.microsoft.com/en-us/agent-framework/
https://learn.microsoft.com/en-us/agent-framework/agents/rag?pivots=programming-language-python
https://learn.microsoft.com/en-us/agent-framework/get-started/memory?pivots=programming-language-python

---

## What the Microsoft Agent Framework Recommends

Based on the documentation, there are **four key capability areas**:

### 1. Memory via Context Providers (already partially done)
The docs show `UserMemoryProvider` as a pattern — you inject personalization in `before_run` and extract facts in `after_run`. Your `UserPreferenceProvider` already implements this pattern, but with **regex-based extraction only**.

### 2. RAG via VectorStore (not implemented)
Semantic Kernel's `VectorStoreCollection.create_search_function()` bridges to Agent Framework tools with `.as_agent_framework_tool()`. This lets you give agents knowledge base search capabilities using any vector store (Azure AI Search, Qdrant, Pinecone, Redis, In-Memory, etc.).

### 3. Session Persistence via `agent.serialize_session()` (not implemented)
The framework supports serializing/deserializing the full `AgentSession` (including state) to survive restarts. Your `Chat Session` DocType's `session_state` field is already there — but it may not be fully wired for this.

### 4. Mem0 Integration (not implemented)
There's an `agent-framework-mem0` package that provides `Mem0ContextProvider` — an LLM-driven memory system that automatically extracts, stores, and retrieves memories based on conversation content (beyond regex matching).

---

## Suggested Features to Implement

Here are the **highest-value features** ranked by impact vs. effort:

---

### ✅ 1. LLM-Driven Memory Provider

**Status**: ✅ **Fully implemented — extraction + relevance-filtered retrieval + cross-session context**.

**What**: Replaces/augments the regex-based `UserPreferenceProvider` with a provider that uses the LLM itself to extract and store arbitrary facts — names, preferences, project details, decisions, etc.

**How it works**:
- `LLMMemoryProvider.before_run()` — loads memories with confidence ≥ 0.6 from **User Memory** DocType and injects them as system instructions into the agent's context
- `LLMMemoryProvider.after_run()` — gets the LLM client from the session's `LLM Provider`, calls the LLM with an extraction system prompt, parses the JSON response, deduplicates against existing records, and persists new/updated memories to the **User Memory** DocType
- Rate-limited to one extraction per 30 seconds per session to avoid excessive API calls
- Extraction prompt focuses on: personal details, goals/tasks, preferences, facts/context, and relationship information
- Deduplication merges by exact (user, fact) match: increments `encounter_count`, boosts `confidence` by +0.05, updates `last_encountered_at`

**Files created**:
- `ph_agent/agent/context/llm_memory_provider.py` — the `ContextProvider` implementation (~330 lines)
- `ph_agent/ph_agent/doctype/user_memory/user_memory.json` — User Memory DocType schema with fields: `user`, `fact`, `category`, `confidence`, `source_session`, `source_message`, `last_encountered_at`, `encounter_count`
- `ph_agent/ph_agent/doctype/user_memory/user_memory.py` — DocType controller (normalizes fact, sets timestamps)
- `ph_agent/ph_agent/doctype/user_memory/__init__.py` — package init

**Files modified**:
- `ph_agent/agent/framework_agent.py` — registered `LLMMemoryProvider()` in the `context_providers` list after `UserPreferenceProvider`

**Why high value**: Regex can only detect 6 fixed patterns. LLM-driven extraction can learn *anything* the user says — preferred units, industry, company name, feature requests, past decisions, etc.

### ✅ Resolved — The "Dilution Problem"

**Previous behavior**: `_load_memories()` retrieved ALL memories, causing dilution as sessions accumulated.

**Fix applied**: Relevance-filtered retrieval with word-overlap scoring, capped at 15 most-relevant memories per turn. See **Feature 1b** below for implementation details.

---

### 🔥 2. RAG / Knowledge Base Search Tool

**What**: Let the agent search Frappe documents or uploaded files as a knowledge base.

**How**: Use Semantic Kernel's vector store connectors (or a simpler Frappe-native approach):
- Define a `FrappeDocVectorStore` that chunks and embeds Frappe DocType records (e.g., `Sales Invoice`, `Customer`, etc.)
- Create a `search_knowledge_base` tool using `create_search_function().as_agent_framework_tool()`
- Register it in `ToolManager` so the agent can query its own knowledge base

**Simpler alternative** (no vector DB needed):
- Create a tool that does `frappe.db.get_list()` with full-text search across configured DocTypes
- The LLM decides which DocType to search based on the question

**Files to create**:
- `ph_agent/agent/tools/knowledge_search_tool.py`

**Why high value**: The agent can answer questions about the user's own data without you pre-programming queries.

---

### ✅ 2a. Schema Discovery Tool (schema blindness fix)

**Status**: ✅ **Fully implemented** — LLM can now discover DocTypes and their fields before querying.

**What**: A `discover_frappe_schema` tool that bridges the "schema blindness" gap — the LLM already had `query_frappe_data` but didn't know *which* DocTypes or fields exist.

**Two operations**:

| Operation | What it does | Key API |
|---|---|---|
| `list_doctypes` | Search for DocTypes matching a name pattern | `frappe.get_all("DocType", filters={"name": ["like", …]})` |
| `get_schema` | Get all field metadata for a specific DocType | `frappe.get_meta(doctype)` → iterate `meta.fields` |

**Per-field metadata returned**: `fieldname`, `label`, `fieldtype`, `reqd`, `read_only`, `hidden`, `description`. Plus type-specific extras: Link→target doctype, Select→options list, Table→child doctype, default values.

**Example LLM workflow**:
```
User: "how many open support tickets?"
  → discover_frappe_schema(list_doctypes, pattern="ticket") → finds "Issue"
  → discover_frappe_schema(get_schema, doctype="Issue") → sees "status" field
  → query_frappe_data(doctype="Issue", filters='{"status":"Open"}', operation="count")
  → "You have 7 open support tickets."
```

**Files created**:
- `ph_agent/agent/tools/schema_discovery_tool.py` — the `@tool` implementation (~174 lines)

**Files modified**:
- `ph_agent/patches/v16_0/seed_tool_registry.py` — registered `discover_frappe_schema` in Tool Registry

**Why high value**: Without schema discovery, the LLM blind-guesses DocTypes/fields. With it, the existing query/CRUD tools become reliably usable. Solves 80% of data-access scenarios for 1 day of work.

---

### ✅ 1b. Relevance-Based Memory Retrieval (fix dilution problem)

**Status**: ✅ **Fully implemented** — keyword-level relevance scoring + hard cap + cross-session context continuity.

**What**: Instead of loading ALL memories, only retrieve memories with word overlap against the current query, capped at 15 per turn. Also injects previous session summaries when creating new sessions.

**Implementation details**:

- `_load_memories(user, query, top_k=15)` — scores all memories by word overlap (`re.findall(r"\b\w+\b")` on both query and fact), sorts by (overlap DESC, confidence DESC), returns top-K. Falls back to top-K by confidence when query is empty.
- `_MAX_INJECTED_MEMORIES = 15` — hard cap on number of memories injected per turn, with defense-in-depth cap in `_format_memories()`.
- `_MAX_INJECTED_PREFERENCES = 20` — same cap applied to `UserPreferenceProvider` for defensive consistency.
- `_get_recent_session_context(user, limit=3)` — reads `last_summary_message` from the user's 3 most recent sessions, strips `*📋 Summary*` header, injects as `[Previous conversation context]` block into the system prompt on `create_session()`. Falls back to the first user message if no summary exists.
- Context injection block is prefixed with "use for continuity but do not mention explicitly" so the agent doesn't awkwardly reference old sessions.

**Files modified**:
- `ph_agent/agent/context/llm_memory_provider.py` — `before_run()` passes user query to `_load_memories()`; `_load_memories()` now does relevance scoring
- `ph_agent/agent/context/user_preference_provider.py` — `_MAX_INJECTED_PREFERENCES` cap in `_format_preferences()`
- `ph_agent/api/chat.py` — `_get_recent_session_context()` + injection in `create_session()`

**Why high value**: Without this, the more you use ph_agent, the *worse* it gets. With relevance filtering, it behaves like Copilot — staying focused and learning over time.

---

### ✅ 3. Conversation Compaction / Summarization Pipeline (Completed)

**Status**: ✅ **Fully implemented** — all 9 steps across 3 phases are complete.

**What was built**:

#### Phase 1: Core Auto-Compaction Pipeline
- **Post-response auto-compaction check** — after the LLM response token counts are updated, automatically triggers summarization if the threshold is now exceeded (`_call_agent_background` → async enqueue of `_perform_auto_summary`)
- **Shared auto-summary helper** — `_perform_auto_summary(session, enqueued_by, emit_status, is_async)` extracted as a reusable function returning `bool`
- **Rate-limiting** — `_is_recently_summarized(session, min_interval_seconds=60)` prevents auto-summary from running more than once per minute

#### Phase 2: Robustness & Edge Cases
- **Progressive thresholds** — 4-tier system: Normal (0-69%), Warning (70-84%), Critical (85-94%), Emergency (≥95%)
- **Emergency compaction fallback** — `_emergency_prune_messages(session)` deletes oldest non-summary messages when LLM fails at ≥95% tokens, preserving at least 4 messages (2 turns)
- **Accurate token estimation** — `_estimate_system_overhead()` accounts for system prompt, tool schemas (JSON ~2 chars/token), and a 20% conversation structure buffer
- **Stacked summaries** — LLM prompt instructs: *"build upon previous summaries, focus on new discussion since last summary point"*

#### Phase 3: Frontend & UX
- **Collapsible summary styling** — `.ph-summary-collapsible` with arrow indicator, light blue gradient background, border-left accent
- **Manual Summarize button** — hidden by default, appears when token % > 20%, calls `summarize_conversation` API with loading spinner
- **Color-coded token thresholds** — dark red + pulse (>95%), red (>85%), amber (>70%), gray (normal)
- **Real-time visibility** — `token_update` event drives Summarize button show/hide

**Key files modified**:
- `ph_agent/api/agent_jobs.py` — all Phase 1 & 2 logic
- `ph_agent/agent/framework_agent.py` — stacked summary prompt
- `ph_agent/public/js/chat/modules/realtimeListeners.js` — progressive threshold colors
- `ph_agent/public/css/chat.css` — collapsible summary + pulse animation styles
- `ph_agent/ph_agent/page/chat/chat.js` — Summarize button + real-time visibility
- `ph_agent/public/js/chat/modules/roomService.js` — `summarizeSession()` method

---

### ✅ 4. AgentSession Persistence (survive restarts)

**Status**: ✅ **Fully implemented**.

**What**: Persist the full `AgentSession` (including provider state, not just chat messages) so that sessions survive server restarts.

**How it works**:
- `_load_session_state()` now uses `AgentSession.from_dict()` to restore `SerializationProtocol` objects (e.g., `Message` instances from `InMemoryHistoryProvider`) with proper type metadata
- `_save_session_state()` now uses `AgentSession.to_dict()` for proper round-trip serialization of all provider state — including `in_memory` messages (previously stripped)
- `_run_agent()` and `_run_agent_stream()` return the `AgentSession` object instead of just the state dict
- `run_after_approval()` reconstructs the `AgentSession` from stored approval data to get properly deserialized state
- Removed custom `_make_json_serializable()` and `_filter_session_state()` utilities — no longer needed

**Files modified**:
- `ph_agent/agent/framework_agent.py` — all 8 functions updated
- `.github/copilot-instructions.md` — documentation updated

**Why high value**: Previously, `InMemoryHistoryProvider` messages were explicitly stripped from saved state. After a server restart, the agent forgot the current conversation context. Now all provider state survives restarts with proper object deserialization.

---

### ❌ 5. Mem0 Integration (decided against)

**What**: Would use the `Mem0ContextProvider` from `agent-framework-mem0` for managed memory.

**Why decided against**:
- **Duplicates existing LLMMemoryProvider** — extraction, storage, retrieval already implemented
- **External dependency** — requires API key and managed service
- **Semantic retrieval gap will be filled by RAG** — embedding infrastructure built for #2 (RAG) will be reused for memory retrieval, replacing keyword scoring with semantic scoring in `_load_memories()`
- **Mem0 is best when you have NO memory system** — but you've already built a solid one

**Verdict**: Semantic memory retrieval will come as Phase B of #1b when RAG embedding infra is built.

---

### ❌ 6. Audit Trail History Provider (decided against)

**What**: Would add a second `HistoryProvider` with `store_context_messages=True` to log all context injected by other providers.

**Why decided against**: 
- **Performance cost**: 5-10 extra DB writes per response turn
- **Data bloat**: 3-5x faster Chat Message table growth from non-conversation records
- **Better alternative exists**: `frappe.log_error()` provides structured, searchable, targeted logging without any of the downsides. When debugging RAG (#2), targeted log calls at retrieval/injection points are far more useful than a noisy audit trail intermixed with real chat messages.

**Verdict**: Use `frappe.log_error()` for targeted debugging. No code changes needed.

---

### ✅ 7. Saved Prompts with Variable Substitution

**Status**: ✅ **Fully implemented**.

**What**: Per-user saved prompt library (like Open WebUI) where users can save reusable prompt templates with `{{variable}}` placeholders. A 📋 button appears in the chat input footer (via Vue Advanced Chat's `textareaActionEnabled` slot). Clicking it opens a Frappe Dialog to browse/search saved prompts. Prompts with `{{variables}}` trigger a second dialog for filling values before insertion into the textarea.

**How it works**:
- **Saved Prompt DocType** — stores prompts per-user with fields: `user`, `title`, `content` (Text Editor), `category` (free-text Data), `is_favorite` (Check), `usage_count` (Int, read-only)
- **API endpoints** in `ph_agent/api/chat.py`:
  - `list_saved_prompts(category)` — user's prompts, sorted favorites-first then by usage
  - `save_prompt(title, content, category, is_favorite, prompt_id)` — create or update
  - `delete_prompt(prompt_id)` — owner-checked delete
  - `get_prompt(prompt_id)` — single prompt details
  - `increment_prompt_usage(prompt_id)` — track usage count
- **Frontend module** (`promptManager.js`):
  - `openPromptLibrary()` — Frappe Dialog with search, grouped list (⭐Favorites / Category / Other), click-to-select
  - `selectPrompt(prompt)` — parses `{{variable}}` patterns, shows fill dialog if variables detected, inserts directly if none
  - `openManageDialog()` — full CRUD (new, edit, delete prompts)
  - `openEditDialog()` — create/edit form with title, content (Text Editor), category, favorite checkbox
- **Variable substitution**: Regex `/\{\{(\w+)\}\}/g` extracts variable names. Fill dialog shows a preview with highlighted placeholders and one input per variable. On "Insert", replaces all `{{var}}` with user values and inserts into textarea via shadow DOM.

**Files created**:
- `ph_agent/ph_agent/doctype/saved_prompt/saved_prompt.json` — DocType schema
- `ph_agent/ph_agent/doctype/saved_prompt/saved_prompt.py` — DocType controller
- `ph_agent/ph_agent/doctype/saved_prompt/__init__.py` — package init
- `ph_agent/public/js/chat/modules/promptManager.js` — full prompt management module (~430 lines)

**Files modified**:
- `ph_agent/api/chat.py` — added 5 saved prompt API endpoints
- `ph_agent/public/js/chat/loader.js` — registered `promptManager.js` in module load order
- `ph_agent/ph_agent/page/chat/chat.js` — enabled `textarea-action-enabled`, initialized promptManager
- `ph_agent/public/js/chat/modules/eventHandlers.js` — bound `textarea-action-handler` event
- `ph_agent/public/css/chat.css` — added prompt library, card, badge, variable placeholder, and manage dialog styles

**Why high value**: Users can save frequently-used prompts (e.g., "Write a professional email about {{topic}}", "Summarize this {{document_type}}") and quickly insert them with variable substitution — dramatically reducing repetitive typing.

---

## Priority Matrix

| Feature | Effort | Impact | Dependencies |
|---|---|---|---|
| **1. LLM Memory Provider** | ✅ **Done** | 🔥🔥🔥🔥🔥 | LLM provider (already have) |
| **1b. Relevance Retrieval** | ✅ **Done** | 🔥🔥🔥🔥🔥 | LLM provider, User Memory DocType |
| **2a. Schema Discovery** | ✅ **Done** | 🔥🔥🔥🔥🔥 | Frappe ORM |
| **2. RAG Search Tool** | Medium-High | 🔥🔥🔥🔥🔥 | Vector DB or Semantic Kernel |
| **3. Auto-Compaction** | ✅ **Done** | 🔥🔥🔥🔥 | — |
| **4. Session Persistence** | ✅ **Done** | 🔥🔥🔥 | Already have `session_state` field |
| **5. Mem0** | ❌ Skipped | — | Duplicates LLMMemoryProvider; semantic gap filled by RAG embedding infra |
| **6. Audit Trail** | ❌ Skipped | — | Use `frappe.log_error()` instead |

---

**Now that #1, #1b, #2a, #3, and #4** are all complete and **#5 and #6 are deferred**, the only remaining feature is **#2 (Full RAG)** for semantic search across record content and files.