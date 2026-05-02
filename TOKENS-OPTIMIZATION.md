Architecture Review
Overall Assessment: Solid, with Targeted Optimization Opportunities
The architecture follows standard industry patterns for AI chatbot frameworks: background job queue (RQ), streaming with non-streaming fallback, cooperative cancellation, per-session Redis locking, session state persistence, and sliding-window context management via auto-summarization. The Microsoft Agent Framework integration is clean, and the context provider system (memory, preferences, skills, hook-registered) is well-abstracted.

There are, however, several concrete areas where token consumption and latency can be reduced.

Token Consumption Optimizations
1. ~~Tool Router Makes a Separate API Call Every Turn (Highest Impact)~~ **COMPLETED**
framework_agent.py:444 — _try_route_tools() fires a dedicated LLM call to filter tools before the main agent call. When you have >5 tools, this means every user turn costs 2 API calls instead of 1. The router prompt + tool menu can easily consume 500–1500 input tokens, plus the router's response tokens.

**Implementation:** Replaced the LLM router call with embedding-based cosine similarity selection via `ph_agent/agent/tools/embedding_router.py`. When `embedding_model` is configured on the LLM Provider, tool embeddings are computed once (cached in Redis, 1-hour TTL) and routing runs in single-digit milliseconds. General-group tools are always preserved; top-K (8) non-General tools are selected by similarity. The old LLM router is preserved as fallback when `embedding_model` is not configured. Cache invalidates automatically via version counter when Tool Registry records change (doc_events hook).

2. ~~Reasoning Content Accumulates Unboundedly~~ **COMPLETED**
framework_agent.py:657-668 — All historical reasoning_content is echoed back in every request (required by DeepSeek's thinking mode). If a conversation has 10 turns with thinking mode, each assistant message carries its full reasoning block forward, and the API sees all of them. Reasoning tokens can be 3–10x the visible output tokens.

Recommendation: After auto-summarization or after N turns, strip reasoning content from older messages. Since summaries capture the outcome of reasoning (not the process), old reasoning chains can be safely dropped. Add a configurable max_reasoning_turns threshold.

3. No Prompt Caching Prefix Optimization
framework_agent.py:929-935 — The Agent is built with instructions, tools, and context providers, but the message order isn't optimized for prompt caching. DeepSeek's API supports automatic prefix caching — cached prefixes save 90%+ on input token cost. Currently the system prompt + tool definitions (the most cacheable, static portion) may be interleaved with dynamic content.

Recommendation: Structure the message list so static content (system instructions, tool schemas) always forms a contiguous prefix. The variable portion (conversation history, user message) should come after. This maximizes cache-hit rate without changing behavior. You're already tracking cache_hit_tokens — structuring for cacheability would increase those numbers.

4. Auxiliary API Calls Are Unbatched
Every user turn can trigger up to 4 additional API calls:

Title generation (first turn only) — framework_agent.py:1602
Follow-up suggestions — framework_agent.py:1693
Memory extraction — llm_memory_provider.py:295
Auto-summary — agent_jobs.py:258
Each makes a separate AsyncOpenAI call. Memory extraction uses the same model as the main chat by default (line _get_extraction_model), which is expensive for a background task.

Recommendation:

For memory extraction, always use a cheap model (hardcode gpt-4o-mini or equivalent) — the _DEFAULT_EXTRACTION_MODEL fallback is correct but overridden by the session's primary model at line 285-286.
Batch title + suggestions into a single call with structured output.
Consider skipping memory extraction for very short messages (< 20 chars).
5. Token Estimation Uses Character-Count Heuristics
agent_jobs.py:148-177 — _estimate_system_overhead() divides character counts by 4 (English) or 2 (JSON). This is off by 30-50% compared to actual tokenization, especially for non-English text or code-heavy system prompts. The 20% buffer smooths this but is imprecise — it means auto-summarization triggers either too early (wasting a summary call) or too late (risking context overflow).

Recommendation: Add an optional tiktoken dependency for accurate token counting. Even a lightweight tokenizer would dramatically improve the accuracy of the auto-summary threshold. Alternatively, track actual token counts from API responses and use a rolling average ratio to calibrate the heuristic per-provider.

6. Context Providers Can Dilute the System Prompt
framework_agent.py:903-914 — Four context providers (FrappeMemoryProvider, SkillsProvider, UserPreferenceProvider, LLMMemoryProvider) plus hook-registered providers all inject text via context.extend_instructions(). Each adds to the system prompt, consuming input tokens on every turn.

Recommendation: Add a combined token budget for all context provider injections (e.g., max 2000 tokens total), with priority ordering. LLMMemoryProvider already caps at 15 memories; apply similar caps to skills and preferences.

Architectural Improvements
7. asyncio.run() Creates a New Event Loop Twice Per Turn
framework_agent.py:1134,1136 — _run_agent() calls asyncio.run(_try_route_tools(...)) then asyncio.run(agent.run(...)). Each creates and destroys an event loop. In the streaming path, the producer thread also creates its own loop.

Recommendation: Combine into a single async function:


async def _run_agent_impl(session_name, messages, user, session_state):
    agent = _build_agent(...)
    agent_session = AgentSession(...)
    await _try_route_tools(agent, session_name, user_text)
    result = await agent.run(messages, session=agent_session)
    return result, agent_session
This halves event-loop creation overhead per turn.

8. _extract_approval_data() Rebuilds the Agent Expensively — **REMOVED**
This optimization is no longer applicable. The entire tool approval workflow (including `_extract_approval_data()`, `_build_auto_approval_messages()`, `run_after_approval()`, and the `Tool Approval Request` doctype) has been removed from the codebase. The `_build_agent()` call in `_extract_approval_data()` no longer exists.

9. Cost Calculation Logic Is Triplicated
agent_jobs.py:29-129 — _credit_user_token_usage() and _calculate_message_cost() duplicate the same pricing-resolution logic. framework_agent.py:716-770 — _credit_auxiliary_api_tokens() duplicates it again.

Recommendation: Extract a single _resolve_effective_rates(session_name) -> tuple function used by all three.

10. Streaming Thread Safety
framework_agent.py:1264-1392 — The streaming producer thread calls frappe.init() / frappe.connect() / frappe.destroy() manually. This pattern is fragile — if an exception occurs between init and destroy, the Frappe connection leaks. The finally block helps, but a nested try/finally around the asyncio.run(_consume()) call would be safer.

Summary of Impact
Issue	Impact	Effort
Tool router → embeddings	Saves 1 API call/turn (~500-1500 tokens)	Medium
Strip old reasoning content	Saves 30-70% of conversation tokens	Low
Prompt caching structure	90%+ discount on static prefix tokens	Low
Batch auxiliary calls	Saves 1-2 API calls/turn	Medium
Cheap model for memory extraction	Saves cost on background extraction	Low (1 line)
Accurate token counting	Better compaction timing	Medium
Combine asyncio.run() calls	Small latency improvement	Low
Deduplicate cost logic	Code quality, no runtime change	Low
The highest-ROI changes are prompt cache prefix optimization and stripping old reasoning content — both are low-effort and can significantly reduce token consumption in long conversations.