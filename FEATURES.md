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

### 🔥 1. LLM-Driven Memory Provider (replace regex with AI extraction)

**What**: Replace or augment the regex-based `UserPreferenceProvider` with a provider that uses the LLM itself to extract and store arbitrary facts — names, preferences, project details, decisions, etc.

**How**: Build a `UserMemoryProvider` (separate from `UserPreferenceProvider`) that:
- In `after_run()`, asks the LLM: *"What facts about the user can you extract from this conversation turn?"*
- Stores extracted facts as structured JSON in a new **User Memory** DocType (or the existing `User Preference` DocType)
- In `before_run()`, retrieves relevant facts (using keyword matching or embedding similarity) and injects them as system instructions

**Files to create**:
- `ph_agent/agent/context/user_memory_provider.py` — new `ContextProvider`
- `ph_agent/ph_agent/doctype/user_memory/` — new DocType for arbitrary key-value memories

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

### 🔥 3. Conversation Compaction / Summarization Pipeline

**What**: The Microsoft docs show `MessageCountingChatReducer`. Your app already has `generate_conversation_summary()`, but it's not fully integrated into the provider pipeline.

**How**: Enhance `FrappeMemoryProvider` to:
- Automatically detect when conversation tokens approach the context limit (already tracked in `estimated_conversation_tokens`)
- Trigger summarization **transparently** via `after_run()` (not as a separate API call)
- Store the summary as a `Chat Message` with `message_type = "Summary"`
- Serve only the summary + recent messages in subsequent `get_messages()`

**Already partially done**: `last_summary_message` and `generate_conversation_summary()` exist, but the auto-triggering isn't wired into the provider pipeline.

**Why high value**: Long sessions hit context limits and the user gets an error. Auto-compaction fixes this.

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
| **1. LLM Memory Provider** | Medium | 🔥🔥🔥🔥🔥 | LLM provider (already have) |
| **2. RAG Search Tool** | Medium-High | 🔥🔥🔥🔥🔥 | Vector DB or Semantic Kernel |
| **3. Auto-Compaction** | Low-Medium | 🔥🔥🔥🔥 | Already partially built |
| **4. Session Persistence** | Low | 🔥🔥🔥 | Already have `session_state` field |
| **5. Mem0** | Low (just `pip install`) | 🔥🔥🔥🔥 | API key, external service |
| **6. Audit Trail** | Very Low | 🔥🔥 | None |

---

**My recommendation**: Start with **#3 (Auto-Compaction)** since it's already half-built and solves a real pain point (context limit errors). Then **#1 (LLM Memory Provider)** for the biggest leap in capability. Add **#4 (Session Persistence)** alongside both as it's low effort.

Would you like me to dive deeper into the design for any of these?