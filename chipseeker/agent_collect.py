"""Deduplicate and annotate results from multiple ChipSeeker retrieval passes."""

from __future__ import annotations

import copy

from chipseeker.keyword_search import (
    normalize_doi_selector,
    normalize_search_text,
    normalize_title_selector,
)
from chipseeker.utils import extract_year
from chipseeker.work_family import assign_work_families, publication_key


AGENT_COLLECT_SCHEMA = "chipseeker-agent-collect/v2"

_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "using",
    "with",
}


def normalized_title(value):
    return normalize_title_selector(value)


def paper_identity(paper):
    return publication_key(paper)


def _query_tokens(query):
    normalized = normalize_search_text(query)
    normalized = normalized.replace("low noise amplifier", "lna")
    return {
        token
        for token in normalized.split()
        if token not in _QUERY_STOPWORDS and len(token) > 1
    }


def _query_similarity(left, right):
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    jaccard = intersection / len(left | right)
    containment = intersection / min(len(left), len(right))
    return max(jaccard, containment)


def _infer_query_families(responses):
    representatives = []
    families = []
    for response in responses:
        explicit = str(response.get("query_family", "") or "").strip()
        mode = str(response.get("mode", "") or "")
        query = str(response.get("query", "") or "")
        structured = (response.get("filters", {}) or {}).get("structured", {}) or {}
        if explicit:
            family_id = explicit
        elif structured.get("exact_titles") or structured.get("dois"):
            family_id = "identity"
        elif structured.get("authors"):
            author_key = normalize_search_text(" ".join(structured["authors"]))
            family_id = f"author:{author_key}"
        else:
            structured_text = " ".join(
                [
                    str(structured.get("expression", "") or ""),
                    " ".join(structured.get("all_terms", []) or []),
                    " ".join(structured.get("any_terms", []) or []),
                ]
            )
            tokens = _query_tokens(f"{query} {structured_text}")
            family_id = ""
            family_mode = "semantic" if mode in {"lite", "filtered_lite", "pro"} else "keyword"
            for representative in representatives:
                if representative["mode"] != family_mode:
                    continue
                if _query_similarity(tokens, representative["tokens"]) >= 0.62:
                    family_id = representative["id"]
                    break
            if not family_id:
                family_id = f"{family_mode}:{len(representatives) + 1}"
                representatives.append({"id": family_id, "mode": family_mode, "tokens": tokens})
        families.append(family_id)
    return families


def _compatible_publication(existing, incoming):
    existing_doi = normalize_doi_selector(existing.get("doi", ""))
    incoming_doi = normalize_doi_selector(incoming.get("doi", ""))
    if existing_doi and incoming_doi:
        return existing_doi == incoming_doi
    existing_title = normalized_title(existing.get("title", ""))
    incoming_title = normalized_title(incoming.get("title", ""))
    if not existing_title or existing_title != incoming_title:
        return False
    existing_year = extract_year(existing.get("year", ""))
    incoming_year = extract_year(incoming.get("year", ""))
    return not existing_year or not incoming_year or existing_year == incoming_year


def _resolve_publication_key(paper, merged, doi_index, title_index):
    doi = normalize_doi_selector(paper.get("doi", ""))
    title = normalized_title(paper.get("title", ""))
    year = extract_year(paper.get("year", ""))
    if doi and doi in doi_index:
        return doi_index[doi]
    compatible_keys = [
        key
        for key in title_index.get((title, year), [])
        if _compatible_publication(merged[key], paper)
    ]
    if not doi:
        candidate_dois = {
            normalize_doi_selector(merged[key].get("doi", ""))
            for key in compatible_keys
            if normalize_doi_selector(merged[key].get("doi", ""))
        }
        if len(candidate_dois) > 1:
            compatible_keys = []
    if compatible_keys:
        return compatible_keys[0]
    if title and year:
        for key in title_index.get((title, 0), []):
            if _compatible_publication(merged[key], paper):
                return key
    if title and not year:
        for (indexed_title, _indexed_year), keys in title_index.items():
            if indexed_title != title:
                continue
            for key in keys:
                if _compatible_publication(merged[key], paper):
                    return key
    return f"publication:{len(merged) + 1}"


def _merge_metadata(item, paper):
    for field in ("doi", "pdf_link", "authors", "venue", "year"):
        if not item.get(field) and paper.get(field):
            item[field] = copy.deepcopy(paper[field])
    if len(str(paper.get("abstract", "") or "")) > len(str(item.get("abstract", "") or "")):
        item["abstract"] = paper.get("abstract", "")
        item["abstract_truncated"] = paper.get("abstract_truncated", False)
    item["similarity"] = max(
        float(item.get("similarity", 0.0) or 0.0),
        float(paper.get("similarity", 0.0) or 0.0),
    )
    combined_fields = list(item.get("matched_fields", []) or [])
    for field in paper.get("matched_fields", []) or []:
        if field not in combined_fields:
            combined_fields.append(field)
    if combined_fields:
        item["matched_fields"] = combined_fields


def _saturation_signal(searches, family_stats):
    if not searches:
        return "insufficient"
    zero_yield_tail = 0
    for search in reversed(searches):
        if search["new_unique_count"] != 0:
            break
        zero_yield_tail += 1
    productive_families = sum(1 for item in family_stats.values() if item["new_unique_count"] > 0)
    if len(family_stats) >= 4 and productive_families >= 2 and zero_yield_tail >= 2:
        return "strong"
    if len(family_stats) >= 3 and zero_yield_tail >= 1:
        return "moderate"
    return "weak"


def merge_search_responses(responses):
    responses = list(responses or [])
    query_families = _infer_query_families(responses)
    merged = {}
    doi_index = {}
    title_index = {}
    raw_result_count = 0
    searches = []
    result_views = set()
    family_stats = {}

    for response, family_id in zip(responses, query_families):
        mode = str(response.get("mode", "") or "")
        query = str(response.get("query", "") or "")
        result_views.add(str(response.get("result_view", "standard") or "standard"))
        new_unique_count = 0
        search_publications = set()
        for paper in response.get("results", []) or []:
            raw_result_count += 1
            key = _resolve_publication_key(paper, merged, doi_index, title_index)
            is_new = key not in merged
            if is_new:
                item = copy.deepcopy(paper)
                item["retrievals"] = []
                merged[key] = item
                new_unique_count += 1
            item = merged[key]
            search_publications.add(key)
            retrieval = {
                "mode": mode,
                "query": query,
                "query_family": family_id,
                "rank": int(paper.get("rank", 0) or 0),
            }
            if mode in {"keyword", "filtered_lite"}:
                retrieval["matched_fields"] = list(paper.get("matched_fields", []) or [])
            if mode != "keyword":
                retrieval["similarity"] = float(paper.get("similarity", 0.0) or 0.0)
            item["retrievals"].append(retrieval)
            if not is_new:
                _merge_metadata(item, paper)

            doi = normalize_doi_selector(item.get("doi", ""))
            title = normalized_title(item.get("title", ""))
            year = extract_year(item.get("year", ""))
            if doi:
                doi_index[doi] = key
            if title:
                keys = title_index.setdefault((title, year), [])
                if key not in keys:
                    keys.append(key)

        search_record = {
            "mode": mode,
            "query": query,
            "query_family": family_id,
            "result_count": int(response.get("result_count", 0) or 0),
            "candidate_count": int(response.get("candidate_count", 0) or 0),
            "new_unique_count": new_unique_count,
            "deduplicated_result_count": len(search_publications),
        }
        searches.append(search_record)
        stats = family_stats.setdefault(
            family_id,
            {
                "query_family": family_id,
                "search_count": 0,
                "raw_result_count": 0,
                "new_unique_count": 0,
                "publication_keys": set(),
            },
        )
        stats["search_count"] += 1
        stats["raw_result_count"] += int(response.get("result_count", 0) or 0)
        stats["new_unique_count"] += new_unique_count
        stats["publication_keys"].update(search_publications)

    results = list(merged.values())
    assign_work_families(results)
    for item in results:
        item["retrieval_count"] = len(item["retrievals"])
        item["retrieval_family_count"] = len(
            {source["query_family"] for source in item["retrievals"]}
        )
        item["retrieval_mode_count"] = len({source["mode"] for source in item["retrievals"]})
        item["publication_key"] = publication_key(item)
    results.sort(
        key=lambda item: (
            item["retrieval_family_count"],
            item["retrieval_mode_count"],
            any(source["mode"] in {"keyword", "filtered_lite"} for source in item["retrievals"]),
            float(item.get("similarity", 0.0) or 0.0),
            extract_year(item.get("year", "")),
        ),
        reverse=True,
    )
    for rank, item in enumerate(results, start=1):
        item["rank"] = rank

    serializable_family_stats = []
    for stats in family_stats.values():
        stats = dict(stats)
        stats["deduplicated_result_count"] = len(stats.pop("publication_keys"))
        serializable_family_stats.append(stats)

    zero_yield_tail = 0
    for search in reversed(searches):
        if search["new_unique_count"] != 0:
            break
        zero_yield_tail += 1
    return {
        "schema": AGENT_COLLECT_SCHEMA,
        "result_view": result_views.pop() if len(result_views) == 1 else "mixed",
        "search_count": len(searches),
        "query_family_count": len(family_stats),
        "searches": searches,
        "query_families": serializable_family_stats,
        "raw_result_count": raw_result_count,
        "deduplicated_count": len(results),
        "saturation": {
            "signal": _saturation_signal(searches, family_stats),
            "zero_yield_search_tail": zero_yield_tail,
            "last_search_new_unique_count": searches[-1]["new_unique_count"] if searches else 0,
        },
        "results": results,
    }
