"""
Embedding-based tool router — replaces per-turn LLM router call with cosine similarity.

Eliminates the second API call per turn by pre-computing tool embeddings once
and selecting relevant tools via embedding similarity instead of an LLM call.

Used by :func:`_try_route_tools` in ``framework_agent.py`` when the LLM Provider
has ``embedding_model`` configured. Falls back to the LLM router otherwise.
"""

import hashlib
import json
import logging
import math
from typing import Any

import frappe
from openai import AsyncOpenAI

from ph_agent.utils.debug_logger import debug_log

logger = logging.getLogger(__name__)

# Top-K non-General tools to return per turn.
_ROUTING_TOP_K = 8

# Cache key prefix for tool embeddings in Redis.
_EMBEDDING_CACHE_KEY_PREFIX = "ph_agent:tool_embeddings:v2"

# Version counter key — bumped on Tool Registry changes to invalidate caches.
_EMBEDDING_CACHE_VERSION_KEY = "ph_agent:tool_embeddings:cache_version"

# TTL for cached tool embeddings (seconds). Auto-expires stale entries.
_EMBEDDING_CACHE_TTL = 3600


# ---------------------------------------------------------------------------
# Cosine similarity (pure Python — no numpy dependency)
# ---------------------------------------------------------------------------


def _cosine_similarity_scores(query_emb: list[float], tool_embeddings: list[list[float]]) -> list[float]:
	"""Compute cosine similarity between a query vector and multiple tool vectors.

	Returns a list of scores, one per tool embedding, in the same order.
	Pure Python implementation — fast enough for <100 vectors of ~1536 dims.
	"""
	if not query_emb or not tool_embeddings:
		return []

	# Normalize query vector (pre-compute once)
	q_norm = math.sqrt(sum(v * v for v in query_emb))
	if q_norm == 0.0:
		return [0.0] * len(tool_embeddings)
	q = [v / q_norm for v in query_emb]

	scores = []
	for tool_emb in tool_embeddings:
		t_norm = math.sqrt(sum(v * v for v in tool_emb))
		if t_norm == 0.0:
			scores.append(0.0)
		else:
			# Dot product of normalized vectors = cosine similarity
			sim = sum(a * b for a, b in zip(q, [v / t_norm for v in tool_emb]))
			scores.append(sim)

	return scores


# ---------------------------------------------------------------------------
# Embedding API helpers
# ---------------------------------------------------------------------------


async def _compute_embedding(text: str, api_key: str, api_url: str, model: str) -> list[float] | None:
	"""Compute a single embedding via OpenAI-compatible API.  Returns None on failure."""
	try:
		client = AsyncOpenAI(api_key=api_key, base_url=api_url)
		response = await client.embeddings.create(model=model, input=text)
		return response.data[0].embedding
	except Exception as e:
		logger.warning("[embedding_router] Embedding API call failed: %s", e)
		return None


async def _compute_embeddings_batch(
	texts: list[str], api_key: str, api_url: str, model: str
) -> list[list[float]] | None:
	"""Compute embeddings for multiple texts in a single API call.  Returns None on failure."""
	try:
		client = AsyncOpenAI(api_key=api_key, base_url=api_url)
		response = await client.embeddings.create(model=model, input=texts)
		indexed = {item.index: item.embedding for item in response.data}
		return [indexed[i] for i in range(len(texts))]
	except Exception as e:
		logger.warning("[embedding_router] Batch embedding API call failed: %s", e)
		return None


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------


def _get_cache_key(tools: list, model: str, api_url: str) -> str:
	"""Generate a content-addressed cache key from the tool set.

	Sorted tool names + descriptions are hashed so that any tool
	addition/removal/rename/description-change produces a new key.
	"""
	tool_texts = sorted(
		f"{getattr(t, 'name', 'unknown')}:{(getattr(t, 'description', '') or '').split(chr(10))[0][:200]}"
		for t in tools
	)
	combined = "||".join(tool_texts)
	content_hash = hashlib.md5(combined.encode("utf-8")).hexdigest()
	api_hash = hashlib.md5(api_url.encode("utf-8")).hexdigest()

	# Include cache version so bumping the counter invalidates all entries.
	version = frappe.cache().get_value(_EMBEDDING_CACHE_VERSION_KEY) or 0
	return f"{_EMBEDDING_CACHE_KEY_PREFIX}:{model}:{api_hash}:{content_hash}:v{version}"


async def _get_tool_embeddings(
	tools: list, api_key: str, api_url: str, model: str
) -> dict[str, list[float]] | None:
	"""Get embeddings for all tools, from cache or freshly computed.

	Returns ``{tool_name: embedding_vector}`` or None on failure.
	"""
	cache_key = _get_cache_key(tools, model, api_url)

	# Try Redis cache first
	try:
		cached = frappe.cache().get_value(cache_key)
		if cached is not None:
			logger.debug("[embedding_router] Cache hit for %s (%d tools)", cache_key, len(tools))
			if isinstance(cached, str):
				cached = json.loads(cached)
			return cached
	except Exception:
		pass

	logger.info("[embedding_router] Computing embeddings for %d tools", len(tools))

	# Build text for each tool: "name: first-line-of-description"
	tool_texts = []
	tool_names = []
	for t in tools:
		name = getattr(t, "name", "unknown")
		desc = (getattr(t, "description", "") or "").split("\n")[0][:200]
		tool_texts.append(f"{name}: {desc}")
		tool_names.append(name)

	embeddings = await _compute_embeddings_batch(tool_texts, api_key, api_url, model)
	if embeddings is None:
		return None

	result = dict(zip(tool_names, embeddings))

	# Cache in Redis (best-effort, non-critical)
	try:
		frappe.cache().set_value(cache_key, result, expires_in_sec=_EMBEDDING_CACHE_TTL)
	except Exception:
		pass

	return result


def clear_tool_embedding_cache(doc, method=None) -> None:
	"""Invalidate all cached tool embeddings by bumping the version counter.

	Called from ``doc_events`` hook whenever a Tool Registry record is
	created, updated, or deleted.
	"""
	try:
		version = frappe.cache().get_value(_EMBEDDING_CACHE_VERSION_KEY) or 0
		frappe.cache().set_value(_EMBEDDING_CACHE_VERSION_KEY, version + 1)
		logger.info("[embedding_router] Bumped cache version to %d", version + 1)
	except Exception as e:
		logger.warning("[embedding_router] Failed to bump cache version: %s", e)


# ---------------------------------------------------------------------------
# Main routing entry point
# ---------------------------------------------------------------------------


async def route_tools_by_embedding(agent, session_name: str, user_query: str) -> bool:
	"""Filter agent tools using embedding-based cosine similarity.

	Always preserves ``tool_group == "General"`` tools. Selects top-K
	non-General tools by similarity between the user query embedding
	and each tool's name+description embedding.

	Returns True if routing was performed (tools were filtered), False if
	it was skipped (e.g., no embedding model configured, too few tools,
	or an error occurred).

	On any failure, leaves tools unchanged (safety-first).
	"""
	import time

	start = time.time()

	tools = agent.default_options.get("tools", [])
	if not tools:
		return False

	# Resolve embedding config from LLM Provider
	try:
		session_doc = frappe.get_doc("Chat Session", session_name)
		provider_doc = frappe.get_doc("LLM Provider", session_doc.llm_provider)
	except Exception:
		logger.warning("[embedding_router] Failed to load session/provider doc")
		return False

	embedding_model = provider_doc.get("embedding_model")
	if not embedding_model:
		logger.debug("[embedding_router] No embedding_model configured on provider")
		return False

	api_key = provider_doc.get_password("api_key")
	if not api_key:
		return False

	embedding_api_url = (
		provider_doc.get("embedding_api_url") or provider_doc.api_url or "https://api.openai.com/v1"
	)
	if not embedding_api_url.endswith("/"):
		embedding_api_url += "/"

	# Separate General tools (always kept) from candidates
	general_tools = [t for t in tools if getattr(t, "tool_group", "General") == "General"]
	candidate_tools = [t for t in tools if getattr(t, "tool_group", "General") != "General"]

	if not candidate_tools:
		return False  # Nothing to filter

	# Get tool embeddings (cached)
	name_to_embedding = await _get_tool_embeddings(tools, api_key, embedding_api_url, embedding_model)
	if name_to_embedding is None:
		logger.warning("[embedding_router] Failed to get tool embeddings, keeping all tools")
		return False

	# Compute query embedding
	query_emb = await _compute_embedding(user_query, api_key, embedding_api_url, embedding_model)
	if query_emb is None:
		logger.warning("[embedding_router] Failed to compute query embedding, keeping all tools")
		return False

	# Build embedding matrix for candidate tools (maintain order)
	candidate_embs = []
	valid_candidates = []
	for t in candidate_tools:
		emb = name_to_embedding.get(t.name)
		if emb is not None:
			candidate_embs.append(emb)
			valid_candidates.append(t)

	if not candidate_embs:
		return False

	# Compute cosine similarity scores
	scores = _cosine_similarity_scores(query_emb, candidate_embs)

	# Select top-K candidates
	top_k = min(_ROUTING_TOP_K, len(valid_candidates))
	if top_k < len(valid_candidates):
		# Get indices of top-K scores (descending)
		indexed = list(enumerate(scores))
		indexed.sort(key=lambda x: x[1], reverse=True)
		top_indices = {i for i, _ in indexed[:top_k]}
		selected_candidates = [valid_candidates[i] for i in range(len(valid_candidates)) if i in top_indices]
	else:
		selected_candidates = valid_candidates

	# Build filtered list: General + top-K candidates
	filtered = general_tools + selected_candidates
	agent.default_options["tools"] = filtered

	elapsed = time.time() - start
	debug_log(
		"route_tools_by_embedding success",
		f"Session: {session_name}, Tools: {len(tools)} -> {len(filtered)} "
		f"(top-{top_k} non-General), Elapsed: {elapsed:.3f}s",
		session=session_name,
	)

	return True
