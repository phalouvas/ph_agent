"""
ToolRouterContextProvider — per-turn LLM tool selection.

Reduces input token overhead by using a cheap LLM call to select only the
tools relevant to the current user query from the persona's allowed set.

Only activated when:
  1. The persona has ``enable_tool_routing = 1``.
  2. The current tool count exceeds ``_ROUTING_THRESHOLD`` (default 5).

If routing fails for any reason the full tool list is kept (safety-first).
"""

import json
import logging
from typing import Any

import frappe
from agent_framework import ContextProvider, AgentSession, SessionContext
from agent_framework_openai import OpenAIChatCompletionClient
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Skip routing when there are this many tools or fewer — not worth the extra call.
_ROUTING_THRESHOLD = 5

# Max tokens consumed by the router response (tool name list is tiny).
_ROUTER_MAX_TOKENS = 300

# System prompt sent to the cheap router model.
_ROUTER_SYSTEM_PROMPT = (
    "You are a tool router. Given a user message and a list of available tools "
    "(each with a name and one-line description), return ONLY the names of the "
    "tools that could plausibly help answer the message.\n\n"
    "Rules:\n"
    "- When a specialized tool exists for the task (e.g. exchange_rate for "
    "currency conversion, yahoo_finance for stock data, wikipedia for "
    "encyclopedic knowledge), prefer it over a general-purpose tool like "
    "web_search.\n"
    "- Only include tools that are clearly relevant. When in doubt, leave it out.\n"
    "- If no tools are needed, return {\"tool_names\": []}.\n\n"
    "Respond with a JSON object in this exact format: "
    '{\"tool_names\": [\"name1\", \"name2\"]}. '
    "Do NOT include any explanation or extra text."
)


class ToolRouterContextProvider(ContextProvider):
    """Per-turn context provider that filters ``context.tools`` using a cheap
    LLM call so the main agent only receives tools relevant to the current query.

    The provider reads the latest user message from the running context,
    asks a lightweight LLM to pick the right tools, then replaces
    ``context.tools`` with only the selected subset.

    Always preserves tools whose ``tool_group`` attribute is ``"General"``
    as a baseline (datetime, calculate, etc.) so they are never accidentally
    dropped.
    """

    def __init__(self, session_name: str, persona: str) -> None:
        super().__init__("tool_router")
        self._session_name = session_name
        self._persona = persona

    # ------------------------------------------------------------------
    # ContextProvider interface
    # ------------------------------------------------------------------

    async def before_run(
        self,
        *,
        agent,
        session: AgentSession,
        context: SessionContext,
        state: dict[str, Any],
    ) -> None:
        tools = list(getattr(context, "tools", None) or [])
        if len(tools) <= _ROUTING_THRESHOLD:
            logger.debug(
                "[tool_router] Skipping routing — only %d tools (threshold=%d)",
                len(tools), _ROUTING_THRESHOLD
            )
            return

        # Extract the latest user message text
        user_query = self._get_latest_user_message(context)
        if not user_query:
            logger.debug("[tool_router] No user message found, skipping routing")
            return

        # Separate General tools (always kept) from candidates
        general_tools = [t for t in tools if getattr(t, "tool_group", "General") == "General"]
        candidate_tools = [t for t in tools if getattr(t, "tool_group", "General") != "General"]

        if not candidate_tools:
            return  # Nothing to filter

        # Build compact tool menu for the router
        tool_menu = self._build_tool_menu(candidate_tools)

        # Ask the router LLM which tools are needed
        selected_names = await self._call_router(user_query, tool_menu)

        if selected_names is None:
            # Router failed — keep all tools (safety fallback)
            logger.warning("[tool_router] Router call failed, keeping all %d tools", len(tools))
            return

        # Build the filtered list: General tools + selected candidates
        selected_set = set(selected_names)
        selected_candidates = [t for t in candidate_tools if t.name in selected_set]
        filtered = general_tools + selected_candidates

        logger.debug(
            "[tool_router] Routed %d → %d tools for query '%s...' (selected: %s)",
            len(tools), len(filtered), user_query[:60],
            sorted(selected_set)
        )

        # Replace context.tools with the filtered list
        context.tools = filtered

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_latest_user_message(self, context: SessionContext) -> str:
        """Extract the latest user message text from context chat messages."""
        try:
            # context.chat contains the accumulated messages for this invocation
            messages = list(getattr(context, "chat", None) or [])
            for msg in reversed(messages):
                if getattr(msg, "role", None) == "user":
                    contents = getattr(msg, "contents", None)
                    if contents:
                        for c in reversed(contents):
                            text = getattr(c, "text", None) or (c if isinstance(c, str) else None)
                            if text:
                                return str(text).strip()
        except Exception as e:
            logger.debug("[tool_router] Failed to extract user message: %s", e)
        return ""

    def _build_tool_menu(self, tools: list) -> str:
        """Build a compact newline-separated tool menu: 'name: description'."""
        lines = []
        for t in tools:
            name = getattr(t, "name", "unknown")
            desc = (getattr(t, "description", "") or "").split("\n")[0][:120]
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)

    async def _call_router(self, user_query: str, tool_menu: str) -> list[str] | None:
        """Call the router LLM and return selected tool names, or None on error."""
        try:
            session_doc = frappe.get_doc("Chat Session", self._session_name)
            provider_doc = frappe.get_doc("LLM Provider", session_doc.llm_provider)
            api_key = provider_doc.get_password("api_key")
            if not api_key:
                return None

            openai_client = AsyncOpenAI(
                api_key=api_key,
                base_url=provider_doc.api_url or "https://api.openai.com/v1",
            )

            user_content = (
                f"User message: {user_query}\n\n"
                f"Available tools:\n{tool_menu}\n\n"
                "Which tools are needed? Respond only with the JSON object."
            )

            response = await openai_client.chat.completions.create(
                model=provider_doc.default_model,
                messages=[
                    {"role": "system", "content": _ROUTER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=_ROUTER_MAX_TOKENS,
                temperature=0.0,
            )

            raw = (response.choices[0].message.content or "").strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            data = json.loads(raw)
            names = data.get("tool_names", [])
            if isinstance(names, list):
                return [str(n) for n in names]
            return []

        except Exception as e:
            logger.warning("[tool_router] Router LLM call failed: %s", e)
            return None
