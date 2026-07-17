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


AGENT_COLLECT_SCHEMA = "chipseeker-agent-collect/v3"

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
    for field in (
        "doi",
        "doi_link",
        "pdf_link",
        "source_links",
        "source_in_current_corpus",
        "abstract_kind",
        "authors",
        "venue",
        "year",
    ):
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


def _saturation_signal(searches, family_stats, has_screening=False):
    if not searches:
        return "insufficient"
    metric = "new_retained_family_count" if has_screening else "new_unique_count"
    zero_yield_tail = 0
    for search in reversed(searches):
        if search.get("status", "completed") != "completed":
            continue
        if int(search.get(metric, 0) or 0) != 0:
            break
        zero_yield_tail += 1
    family_metric = "new_retained_family_count" if has_screening else "new_unique_count"
    productive_families = sum(1 for item in family_stats.values() if item.get(family_metric, 0) > 0)
    if len(family_stats) >= 4 and productive_families >= 2 and zero_yield_tail >= 2:
        return "strong"
    if len(family_stats) >= 3 and zero_yield_tail >= 1:
        return "moderate"
    return "weak"


def _is_retained(decision):
    return str(decision or "").strip().lower() in {"include", "included", "retain", "retained"}


def merge_search_responses(responses, screening_decisions=None):
    responses = list(responses or [])
    screening_decisions = dict(screening_decisions or {})
    has_screening = bool(screening_decisions)
    query_families = _infer_query_families(responses)
    merged = {}
    doi_index = {}
    title_index = {}
    raw_result_count = 0
    searches = []
    result_views = set()
    family_stats = {}
    role_stats = {}
    coverage_stats = {}
    failed_search_count = 0

    for response, family_id in zip(responses, query_families):
        mode = str(response.get("mode", "") or "")
        query = str(response.get("query", "") or "")
        query_id = str(response.get("query_id", "") or "")
        query_role = str(response.get("query_role", "general") or "general")
        coverage = response.get("coverage", {}) or {}
        status = str(response.get("status", "completed") or "completed")
        result_views.add(str(response.get("result_view", "standard") or "standard"))
        new_unique_count = 0
        search_publications = set()
        introduced_publications = set()
        for paper in response.get("results", []) or []:
            raw_result_count += 1
            key = _resolve_publication_key(paper, merged, doi_index, title_index)
            is_new = key not in merged
            if is_new:
                item = copy.deepcopy(paper)
                item["retrievals"] = []
                merged[key] = item
                new_unique_count += 1
                introduced_publications.add(key)
            item = merged[key]
            search_publications.add(key)
            retrieval = {
                "mode": mode,
                "query": query,
                "query_family": family_id,
                "query_id": query_id,
                "query_role": query_role,
                "coverage": copy.deepcopy(coverage),
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
            "query_id": query_id,
            "query_role": query_role,
            "coverage": copy.deepcopy(coverage),
            "query_family": family_id,
            "status": status,
            "result_count": int(response.get("result_count", 0) or 0),
            "candidate_count": int(response.get("candidate_count", 0) or 0),
            "new_unique_count": new_unique_count,
            "deduplicated_result_count": len(search_publications),
            "duration_seconds": float(response.get("duration_seconds", 0.0) or 0.0),
            "_publication_keys": search_publications,
            "_introduced_keys": introduced_publications,
        }
        if response.get("error"):
            search_record["error"] = str(response["error"])
        if response.get("pro_attempts") is not None:
            search_record["pro_attempts"] = copy.deepcopy(response["pro_attempts"])
        if response.get("batch_retry") is not None:
            search_record["batch_retry"] = copy.deepcopy(response["batch_retry"])
        if response.get("batch_error"):
            search_record["batch_error"] = str(response["batch_error"])
        if status != "completed":
            failed_search_count += 1
        searches.append(search_record)
        stats = family_stats.setdefault(
            family_id,
            {
                "query_family": family_id,
                "search_count": 0,
                "raw_result_count": 0,
                "new_unique_count": 0,
                "publication_keys": set(),
                "new_retained_count": 0,
                "new_retained_family_count": 0,
            },
        )
        stats["search_count"] += 1
        stats["raw_result_count"] += int(response.get("result_count", 0) or 0)
        stats["new_unique_count"] += new_unique_count
        stats["publication_keys"].update(search_publications)
        role = role_stats.setdefault(
            query_role,
            {"query_role": query_role, "search_count": 0, "raw_result_count": 0, "publication_keys": set()},
        )
        role["search_count"] += 1
        role["raw_result_count"] += int(response.get("result_count", 0) or 0)
        role["publication_keys"].update(search_publications)
        for dimension, values in coverage.items():
            dimension_stats = coverage_stats.setdefault(str(dimension), {})
            for value in values or []:
                ids = dimension_stats.setdefault(str(value), [])
                if query_id not in ids:
                    ids.append(query_id)

    results = list(merged.values())
    assign_work_families(results)
    for item in results:
        decision = screening_decisions.get(publication_key(item))
        if decision:
            for field in (
                "screening_decision",
                "screening_reason",
                "evidence_matrix",
                "record_type",
                "evidence_category",
                "technology_process",
                "physical_temperature",
                "frequency_range_ghz",
                "frequency_relation",
            ):
                if field in decision:
                    item[field] = copy.deepcopy(decision[field])
        item["retrieval_count"] = len(item["retrievals"])
        item["retrieval_family_count"] = len(
            {source["query_family"] for source in item["retrievals"]}
        )
        item["retrieval_mode_count"] = len({source["mode"] for source in item["retrievals"]})
        item["publication_key"] = publication_key(item)

    if has_screening:
        seen_retained_families = set()
        for search in searches:
            introduced = [merged[key] for key in search.pop("_introduced_keys")]
            searched = [merged[key] for key in search.pop("_publication_keys")]
            retained_introduced = [item for item in introduced if _is_retained(item.get("screening_decision"))]
            retained_families = {
                item.get("work_family_id")
                for item in searched
                if _is_retained(item.get("screening_decision")) and item.get("work_family_id")
            }
            new_families = retained_families - seen_retained_families
            search["new_retained_count"] = len(retained_introduced)
            search["new_retained_family_count"] = len(new_families)
            seen_retained_families.update(retained_families)
            stats = family_stats[search["query_family"]]
            stats["new_retained_count"] += len(retained_introduced)
            stats["new_retained_family_count"] += len(new_families)
    else:
        for search in searches:
            search.pop("_introduced_keys")
            search.pop("_publication_keys")
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

    serializable_role_stats = []
    for stats in role_stats.values():
        stats = dict(stats)
        stats["deduplicated_result_count"] = len(stats.pop("publication_keys"))
        serializable_role_stats.append(stats)

    zero_yield_tail = 0
    for search in reversed(searches):
        metric = "new_retained_family_count" if has_screening else "new_unique_count"
        if search.get("status", "completed") != "completed":
            continue
        if int(search.get(metric, 0) or 0) != 0:
            break
        zero_yield_tail += 1
    screening_summary = None
    if has_screening:
        decision_counts = {}
        for item in results:
            decision = str(item.get("screening_decision", "unscreened") or "unscreened")
            decision_counts[decision] = decision_counts.get(decision, 0) + 1
        screening_summary = {
            "decision_counts": decision_counts,
            "retained_count": sum(
                1 for item in results if _is_retained(item.get("screening_decision"))
            ),
        }
    return {
        "schema": AGENT_COLLECT_SCHEMA,
        "result_view": result_views.pop() if len(result_views) == 1 else "mixed",
        "search_count": len(searches),
        "query_family_count": len(family_stats),
        "query_role_count": len(role_stats),
        "failed_search_count": failed_search_count,
        "searches": searches,
        "query_families": serializable_family_stats,
        "query_roles": serializable_role_stats,
        "query_coverage": coverage_stats,
        "raw_result_count": raw_result_count,
        "deduplicated_count": len(results),
        "screening": screening_summary,
        "saturation": {
            "signal": _saturation_signal(searches, family_stats, has_screening=has_screening),
            "basis": "retained_work_families" if has_screening else "raw_unique_candidates",
            "provisional": not has_screening,
            "zero_yield_search_tail": zero_yield_tail,
            "last_search_new_unique_count": searches[-1].get("new_unique_count", 0) if searches else 0,
            "last_search_new_retained_family_count": searches[-1].get("new_retained_family_count") if searches else None,
        },
        "results": results,
    }
