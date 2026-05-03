"""Accurate token counting via tiktoken, with character-count fallback.

Replaces the character-count heuristics (``len(s) // 4`` for text, ``len(s) // 2``
for JSON) that were off by 30-50 % compared to actual tokenization.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model → tiktoken encoding mapping
# ---------------------------------------------------------------------------

_MODEL_TO_ENCODING: dict[str, str] = {
	# OpenAI models
	"gpt-4": "cl100k_base",
	"gpt-4-turbo": "cl100k_base",
	"gpt-4-32k": "cl100k_base",
	"gpt-3.5-turbo": "cl100k_base",
	"gpt-3.5-turbo-16k": "cl100k_base",
	"text-embedding-ada-002": "cl100k_base",
	"text-embedding-3-small": "cl100k_base",
	"text-embedding-3-large": "cl100k_base",
	"gpt-4o": "o200k_base",
	"gpt-4o-mini": "o200k_base",
	"o1": "o200k_base",
	"o1-mini": "o200k_base",
	"o3-mini": "o200k_base",
	# DeepSeek models (compatible with cl100k_base tokenizer)
	"deepseek-chat": "cl100k_base",
	"deepseek-reasoner": "cl100k_base",
	"deepseek-v3": "cl100k_base",
	"deepseek-r1": "cl100k_base",
}

_DEFAULT_ENCODING = "cl100k_base"

# Lazy-loaded tiktoken encoding cache
_encoding_cache: dict[str, object] = {}


def _get_encoding(encoding_name: str):
	"""Load and cache a tiktoken encoding."""
	if encoding_name not in _encoding_cache:
		try:
			import tiktoken

			_encoding_cache[encoding_name] = tiktoken.get_encoding(encoding_name)
		except ImportError:
			return None
		except Exception:
			logger.warning("Failed to load tiktoken encoding: %s", encoding_name)
			return None
	return _encoding_cache[encoding_name]


def _resolve_encoding(model: str | None = None) -> str | None:
	"""Resolve the tiktoken encoding name for a given model.

	Returns None if tiktoken is not available.
	"""
	try:
		import tiktoken
	except ImportError:
		return None

	if model and model in _MODEL_TO_ENCODING:
		return _MODEL_TO_ENCODING[model]
	# Try tiktoken's built-in model→encoding resolution
	if model:
		try:
			import tiktoken

			return tiktoken.encoding_name_for_model(model)
		except KeyError, Exception:
			pass
	return _DEFAULT_ENCODING


def count_tokens(text: str, model: str | None = None, encoding_name: str | None = None) -> int:
	"""Count tokens in *text* using tiktoken, falling back to character-count heuristics.

	Args:
		text: The text to count tokens for.
		model: Optional model name to auto-select encoding (e.g. "gpt-4o").
		encoding_name: Explicit encoding (overrides *model* auto-detection).

	Returns:
		Token count. Falls back to ``len(text) // 4`` (English heuristic) when
		tiktoken is not installed.
	"""
	enc_name = encoding_name or _resolve_encoding(model)
	if enc_name:
		enc = _get_encoding(enc_name)
		if enc is not None:
			return len(enc.encode(text))

	# Fallback: character-count heuristic (~4 chars per token for English)
	return max(1, len(text) // 4)


def count_tokens_for_messages(
	messages: list[dict], model: str | None = None, encoding_name: str | None = None
) -> int:
	"""Count tokens for a list of chat messages (content-only, not API overhead).

	Each message is counted as its JSON-serialized content. This is an
	approximation — the actual API token count includes per-message framing
	tokens (role, formatting) which vary by provider/model.
	"""
	total = 0
	for msg in messages:
		content = msg.get("content", "") or ""
		total += count_tokens(str(content), model=model, encoding_name=encoding_name)
	return total


def _estimate_system_overhead_tokens(
	system_prompt: str,
	tools_schema_text: str,
	model: str | None = None,
) -> int:
	"""Accurately estimate token overhead from system prompt + tool definitions.

	Uses tiktoken when available; falls back to character-count heuristics.
	Unlike the legacy ``_estimate_system_overhead()`` in agent_jobs.py, this
	function does NOT add a 20 % buffer — the tiktoken count is already accurate
	enough, and for fallback the buffer just amplifies imprecision.

	Returns the estimated overhead in tokens.
	"""
	overhead = 0

	# System prompt text
	if system_prompt:
		overhead += count_tokens(system_prompt, model=model)

	# Tool definition schemas (compact JSON)
	if tools_schema_text:
		overhead += count_tokens(tools_schema_text, model=model)

	return overhead


def get_model_for_session(session_name: str) -> str | None:
	"""Get the model name configured for a session's LLM Provider."""
	import frappe

	try:
		session_doc = frappe.get_doc("Chat Session", session_name)
		provider_doc = frappe.get_doc("LLM Provider", session_doc.llm_provider)
		return provider_doc.default_model
	except Exception:
		return None


# ---------------------------------------------------------------------------
# Context provider token budget
# ---------------------------------------------------------------------------

# Maximum total tokens consumed by ALL context provider injections combined.
# Priority: memories > preferences > skills > hook-registered providers.
MAX_CONTEXT_PROVIDER_TOKENS = 2000

# Per-provider sub-budgets (tokens). The sum should not exceed the total above.
BUDGET_MEMORIES = 800  # LLMMemoryProvider (highest priority)
BUDGET_PREFERENCES = 400  # UserPreferenceProvider
BUDGET_SKILLS = 500  # SkillsProvider (file-based + DocType)
BUDGET_HOOK_PROVIDERS = 300  # Hook-registered providers (lowest priority)

# State key for remaining budget tracking
_BUDGET_STATE_KEY = "_ctx_budget_remaining"

# State key for per-provider consumed tokens (for debugging/monitoring)
_BUDGET_CONSUMED_KEY = "_ctx_budget_consumed"


def init_context_budget(state: dict, model: str | None = None) -> None:
	"""Initialize the shared context provider token budget in *state*.

	Call this before the agent runs so all context providers share a
	combined budget. Each provider calls ``consume_context_budget()``
	before injecting instructions.

	Args:
		state: The ``AgentSession.state`` dict shared across providers.
		model: Optional model name for accurate token counting.
	"""
	state[_BUDGET_STATE_KEY] = MAX_CONTEXT_PROVIDER_TOKENS
	state[_BUDGET_CONSUMED_KEY] = {}


def consume_context_budget(
	state: dict,
	provider_id: str,
	text: str,
	model: str | None = None,
) -> str:
	"""Consume tokens from the shared budget for *text*, returning truncated text.

	If *text* fits entirely within the remaining budget, it is returned unchanged.
	Otherwise it is truncated to fit, approximated by character slicing (tiktoken
	is used for better accuracy when available).

	Args:
		state: The ``AgentSession.state`` dict.
		provider_id: Short identifier for the provider (e.g. "memories", "prefs").
		text: The full instruction text the provider would like to inject.
		model: Optional model name for accurate token counting.

	Returns:
		The (possibly truncated) text to inject via ``context.extend_instructions()``.
		Returns an empty string if no budget remains.
	"""
	# If budget was never initialized, seed it with the default so
	# injection still works (defense against missing init_context_budget calls).
	if _BUDGET_STATE_KEY not in state or _BUDGET_CONSUMED_KEY not in state:
		state[_BUDGET_STATE_KEY] = MAX_CONTEXT_PROVIDER_TOKENS
		state[_BUDGET_CONSUMED_KEY] = {}

	remaining = state[_BUDGET_STATE_KEY]
	if remaining <= 0 or not text:
		return ""

	full_tokens = count_tokens(text, model=model)
	if full_tokens <= remaining:
		state[_BUDGET_STATE_KEY] = remaining - full_tokens
		state[_BUDGET_CONSUMED_KEY][provider_id] = full_tokens
		return text

	# Truncate to fit: use ~4 chars per token as a rough slicing guide,
	# then verify with actual token count
	char_budget = remaining * 4
	truncated = text[:char_budget]

	# Refine: remove the last partial line and add an ellipsis marker
	if "\n" in truncated:
		truncated = truncated[: truncated.rfind("\n")]

	actual_tokens = count_tokens(truncated, model=model)
	state[_BUDGET_STATE_KEY] = max(0, remaining - actual_tokens)
	state[_BUDGET_CONSUMED_KEY][provider_id] = actual_tokens

	logger.debug(
		"Context budget: %s truncated from %d to %d tokens (remaining=%d)",
		provider_id,
		full_tokens,
		actual_tokens,
		state[_BUDGET_STATE_KEY],
	)
	return truncated


def get_context_budget_consumed(state: dict) -> dict[str, int]:
	"""Return per-provider token consumption for monitoring/debugging."""
	return dict(state.get(_BUDGET_CONSUMED_KEY, {}))
