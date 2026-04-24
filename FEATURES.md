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

### ✅ 1. LLM-Driven Memory Provider (replace regex with AI extraction)

**Status**: ✅ **Fully implemented**.

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

### 🔥 4. AgentSession Persistence (survive restarts)

**What**: Persist the full `AgentSession` (including provider state, not just chat messages) so that sessions survive server restarts.

**How**: The `Chat Session` DocType already has a `session_state` field. Use `agent.serialize_session()` and `agent.deserialize_session_async()` to persist/restore session state.
- On `after_run()` or at session close, call `session_state = agent.serialize_session(session)` and store it
- On session resume, call `session = await agent.deserialize_session_async(session_state)`

**Files to modify**: framework_agent.py — `get_agent_response_stream()` or a new middleware

**Why high value**: Currently, in-memory history (`InMemoryHistoryProvider`) is lost on restart. Service restart means the agent forgets the current conversation.

---

### 🔥 5. Mem0 Integration (third-party memory service)

**What**: Use the `Mem0ContextProvider` from `agent-framework-mem0` for persistent, cross-session memory with automatic extraction and retrieval.

**How**: 
```bash
pip install agent-framework-mem0
```
Then add to context providers:
```python
from agent_framework.mem0 import Mem0ContextProvider

agent = Agent(
    ...,
    context_providers=[
        ...,
        Mem0ContextProvider("user-memory", api_key=..., agent_id="ph-agent"),
    ],
)
```

**Why high value**: Mem0 is a managed memory service that handles embedding, storage, and relevance retrieval automatically. Zero regex maintenance.

---

### 🟢 6. Audit Trail History Provider (lower effort)

**What**: Add a second `HistoryProvider` (after your `FrappeMemoryProvider`) with `store_context_messages=True` to log everything — including context injected by other providers.

**How**: Just add another provider to the list:
```python
audit_provider = FrappeMemoryProvider(source_id="audit", load_messages=False, store_context_messages=True)
```

**Why useful**: Debugging and compliance — you can see exactly what context the LLM received.

---

## Priority Matrix

| Feature | Effort | Impact | Dependencies |
|---|---|---|---|
| **1. LLM Memory Provider** | ✅ **Done** | 🔥🔥🔥🔥🔥 | LLM provider (already have) |
| **2. RAG Search Tool** | Medium-High | 🔥🔥🔥🔥🔥 | Vector DB or Semantic Kernel |
| **3. Auto-Compaction** | ✅ **Done** | 🔥🔥🔥🔥 | — |
| **4. Session Persistence** | Low | 🔥🔥🔥 | Already have `session_state` field |
| **5. Mem0** | Low (just `pip install`) | 🔥🔥🔥🔥 | API key, external service |
| **6. Audit Trail** | Very Low | 🔥🔥 | None |

---

**Now that #1 (LLM Memory Provider) and #3 (Auto-Compaction)** are both fully implemented, the recommended next priorities are **#5 (Mem0)** for a managed memory service and **#4 (Session Persistence)** for low-effort resilience gains.

Would you like me to dive deeper into the design for any of these?