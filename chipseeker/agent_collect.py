"""Deduplicate and annotate results from multiple ChipSeeker retrieval passes."""

from __future__ import annotations

import copy
import re


AGENT_COLLECT_SCHEMA = "chipseeker-agent-collect/v1"


def normalized_title(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def paper_identity(paper):
    doi = str(paper.get("doi", "") or "").strip().lower()
    title = normalized_title(paper.get("title", ""))
    return f"doi:{doi}" if doi else f"title:{title}"


def merge_search_responses(responses):
    merged = {}
    doi_index = {}
    title_index = {}
    raw_result_count = 0
    searches = []
    result_views = set()
    for response in responses:
        mode = str(response.get("mode", "") or "")
        query = str(response.get("query", "") or "")
        result_views.add(str(response.get("result_view", "standard") or "standard"))
        searches.append(
            {
                "mode": mode,
                "query": query,
                "result_count": int(response.get("result_count", 0) or 0),
                "candidate_count": int(response.get("candidate_count", 0) or 0),
            }
        )
        for paper in response.get("results", []) or []:
            raw_result_count += 1
            doi = str(paper.get("doi", "") or "").strip().lower()
            title = normalized_title(paper.get("title", ""))
            key = doi_index.get(doi) if doi else None
            key = key or (title_index.get(title) if title else None)
            key = key or paper_identity(paper)
            retrieval = {
                "mode": mode,
                "query": query,
                "rank": int(paper.get("rank", 0) or 0),
            }
            if mode == "keyword":
                retrieval["matched_fields"] = list(paper.get("matched_fields", []) or [])
            else:
                retrieval["similarity"] = float(paper.get("similarity", 0.0) or 0.0)

            if key not in merged:
                item = copy.deepcopy(paper)
                item["retrievals"] = [retrieval]
                merged[key] = item
                if doi:
                    doi_index[doi] = key
                if title:
                    title_index[title] = key
                continue

            item = merged[key]
            if doi:
                doi_index[doi] = key
            if title:
                title_index[title] = key
            item["retrievals"].append(retrieval)
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

    results = list(merged.values())
    for item in results:
        item["retrieval_count"] = len(item["retrievals"])
    results.sort(
        key=lambda item: (
            item["retrieval_count"],
            any(source["mode"] == "keyword" for source in item["retrievals"]),
            float(item.get("similarity", 0.0) or 0.0),
            str(item.get("year", "") or ""),
        ),
        reverse=True,
    )
    for rank, item in enumerate(results, start=1):
        item["rank"] = rank

    return {
        "schema": AGENT_COLLECT_SCHEMA,
        "result_view": result_views.pop() if len(result_views) == 1 else "mixed",
        "search_count": len(searches),
        "searches": searches,
        "raw_result_count": raw_result_count,
        "deduplicated_count": len(results),
        "results": results,
    }
