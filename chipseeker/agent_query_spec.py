"""Validate structured, per-query plans for ChipSeeker agent collection."""

from __future__ import annotations

import json
from pathlib import Path

from chipseeker.agent_search import parse_keyword_fields, parse_venues, parse_year_range


QUERY_SPEC_SCHEMA = "chipseeker-agent-query-spec/v1"
SUPPORTED_MODES = {"lite", "keyword", "filtered_lite", "pro"}


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if str(item or "").strip()]
    return [value] if str(value or "").strip() else []


def _pick(entry, defaults, name, fallback=None):
    if name in entry:
        return entry[name]
    if name in defaults:
        return defaults[name]
    return fallback


def load_query_spec(path):
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Query spec must be a JSON object.")
    schema = str(payload.get("schema", QUERY_SPEC_SCHEMA) or QUERY_SPEC_SCHEMA)
    if schema != QUERY_SPEC_SCHEMA:
        raise ValueError(f"Unsupported query spec schema: {schema}")
    if not isinstance(payload.get("queries"), list) or not payload["queries"]:
        raise ValueError("Query spec requires a non-empty queries array.")
    if payload.get("defaults") is not None and not isinstance(payload["defaults"], dict):
        raise ValueError("Query spec defaults must be an object.")
    return payload


def normalize_query_spec(payload, runtime_defaults=None):
    runtime_defaults = dict(runtime_defaults or {})
    defaults = dict(runtime_defaults)
    defaults.update(payload.get("defaults", {}) or {})
    normalized = []
    seen_ids = set()

    for position, raw_entry in enumerate(payload.get("queries", []), start=1):
        if not isinstance(raw_entry, dict):
            raise ValueError(f"Query #{position} must be an object.")
        if raw_entry.get("enabled", True) is False:
            continue
        entry = dict(raw_entry)
        mode = str(_pick(entry, defaults, "mode", "lite") or "lite").strip().lower().replace("-", "_")
        if mode not in SUPPORTED_MODES:
            raise ValueError(f"Query #{position} uses unsupported mode: {mode}")
        query_id = str(entry.get("id", f"query-{position:03d}") or "").strip()
        if not query_id:
            raise ValueError(f"Query #{position} has an empty id.")
        if query_id in seen_ids:
            raise ValueError(f"Duplicate query id: {query_id}")
        seen_ids.add(query_id)

        query = str(entry.get("query", "") or "").strip()
        expression = str(entry.get("expression", entry.get("keyword_expression", "")) or "").strip()
        selectors = {
            "all_terms": [str(item) for item in _as_list(entry.get("all_terms"))],
            "any_terms": [str(item) for item in _as_list(entry.get("any_terms"))],
            "exact_titles": [str(item) for item in _as_list(entry.get("exact_titles"))],
            "dois": [str(item) for item in _as_list(entry.get("dois"))],
            "authors": [str(item) for item in _as_list(entry.get("authors"))],
        }
        has_selectors = bool(expression or any(selectors.values()))
        if mode in {"lite", "filtered_lite", "pro"} and not query:
            raise ValueError(f"Query {query_id} requires non-empty query text.")
        if mode == "keyword" and not (query or has_selectors):
            raise ValueError(f"Keyword query {query_id} requires text or structured selectors.")
        if mode == "filtered_lite" and not has_selectors:
            raise ValueError(f"Filtered Lite query {query_id} requires structured selectors.")

        mode_top_k_name = "keyword_top_k" if mode == "keyword" else f"{mode.split('_')[0]}_top_k"
        top_k = _pick(entry, defaults, "top_k", _pick(entry, defaults, mode_top_k_name, 0 if mode == "keyword" else 200))
        years = parse_year_range(_pick(entry, defaults, "years", ""))
        venues = parse_venues(_as_list(_pick(entry, defaults, "venues", _pick(entry, defaults, "venue", []))))
        fields = parse_keyword_fields(_pick(entry, defaults, "fields", ""))
        fallback_models = _as_list(
            _pick(entry, defaults, "fallback_models", _pick(entry, defaults, "pro_fallback_models", []))
        )
        top_k = int(top_k)
        abstract_chars = int(_pick(entry, defaults, "abstract_chars", 0))
        rerank_limit = int(_pick(entry, defaults, "rerank_limit", 30))
        timeout_seconds = int(_pick(entry, defaults, "timeout_seconds", 300))
        result_view = str(_pick(entry, defaults, "result_view", "titles") or "titles")
        if top_k < 0 or (mode != "keyword" and top_k == 0):
            raise ValueError(f"Query {query_id} top_k must be positive; Keyword may use 0 for all matches.")
        if abstract_chars < 0:
            raise ValueError(f"Query {query_id} abstract_chars must not be negative.")
        if rerank_limit <= 0 or timeout_seconds <= 0:
            raise ValueError(f"Query {query_id} rerank_limit and timeout_seconds must be positive.")
        if result_view not in {"titles", "standard"}:
            raise ValueError(f"Query {query_id} result_view must be titles or standard.")
        raw_coverage = entry.get("coverage", entry.get("covers", {})) or {}
        if not isinstance(raw_coverage, dict):
            raise ValueError(f"Query {query_id} coverage must be an object.")
        coverage = {
            str(dimension): [str(item) for item in _as_list(values)]
            for dimension, values in raw_coverage.items()
            if str(dimension or "").strip()
        }

        normalized.append(
            {
                "id": query_id,
                "mode": mode,
                "query": query,
                "query_family": str(entry.get("query_family", entry.get("family", "")) or ""),
                "query_role": str(entry.get("query_role", entry.get("role", "general")) or "general"),
                "coverage": coverage,
                "top_k": top_k,
                "years": years,
                "venues": venues,
                "fields": fields,
                "expression": expression,
                **selectors,
                "must_have": str(_pick(entry, defaults, "must_have", "") or ""),
                "embedding_model": str(_pick(entry, defaults, "embedding_model", "") or ""),
                "llm_model": str(_pick(entry, defaults, "llm_model", "") or ""),
                "fallback_models": [str(item) for item in fallback_models],
                "rerank_limit": rerank_limit,
                "timeout_seconds": timeout_seconds,
                "abstract_chars": abstract_chars,
                "result_view": result_view,
            }
        )

    if not normalized:
        raise ValueError("Query spec has no enabled queries.")
    return normalized
