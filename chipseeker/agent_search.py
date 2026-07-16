"""Machine-friendly local search functions for coding-agent workflows."""

from __future__ import annotations

import json
import time
from datetime import datetime

from chipseeker.search_ui import (
    KEYWORD_SEARCH_FIELDS,
    filter_search_results,
    keyword_match_details,
    normalize_keyword_fields,
)
from chipseeker.utils import extract_year
from chipseeker.venue_data import analyze_venue
from search_runtime import PaperSearcher


AGENT_SEARCH_SCHEMA = "chipseeker-agent-search/v1"


def parse_year_range(value):
    current_year = datetime.now().year
    if not value:
        return (2000, current_year)
    raw = str(value).strip()
    for separator in (":", "-"):
        if separator in raw:
            start, end = raw.split(separator, 1)
            try:
                years = (int(start), int(end))
            except ValueError as exc:
                raise ValueError("Year range must use YYYY:YYYY, for example 2018:2026.") from exc
            if years[0] > years[1]:
                raise ValueError("Year range start must not exceed the end year.")
            return years
    try:
        year = int(raw)
    except ValueError as exc:
        raise ValueError("Year range must use YYYY or YYYY:YYYY.") from exc
    return (year, year)


def parse_venues(values):
    venues = []
    for value in values or []:
        for item in str(value).split(","):
            normalized = item.strip()
            if normalized and normalized not in venues:
                venues.append(normalized)
    return venues


def parse_keyword_fields(value):
    if isinstance(value, (list, tuple)):
        raw_fields = value
    else:
        raw_fields = str(value or "").split(",") if value else KEYWORD_SEARCH_FIELDS
    return normalize_keyword_fields(raw_fields)


def compact_paper(paper, similarity, rank, abstract_chars):
    abstract = str(paper.get("abstract", "") or "")
    abstract_chars = max(0, int(abstract_chars))
    truncated = len(abstract) > abstract_chars
    authors = paper.get("authors", [])
    if not isinstance(authors, list):
        authors = [item.strip() for item in str(authors).split(";") if item.strip()]
    if not authors:
        authors = [item for item in (paper.get("first_author", ""), paper.get("last_author", "")) if item]

    result = {
        "rank": int(rank),
        "similarity": round(float(similarity), 6),
        "title": str(paper.get("title", "") or ""),
        "abstract": abstract[:abstract_chars] if abstract_chars else "",
        "abstract_truncated": truncated,
        "authors": authors,
        "venue": str(paper.get("venue", "") or ""),
        "year": str(paper.get("year", "") or ""),
        "doi": str(paper.get("doi", "") or ""),
        "pdf_link": str(paper.get("pdf_link", "") or ""),
        "keywords": paper.get("keywords", []) or [],
        "ieee_terms": paper.get("ieee_terms", []) or [],
    }
    if "llm_score" in paper:
        result["llm_score"] = paper["llm_score"]
        result["llm_reason"] = str(paper.get("llm_reason", "") or "")
    return result


def _project_result_view(result, result_view):
    if result_view == "standard":
        return result
    if result_view != "titles":
        raise ValueError("Result view must be 'titles' or 'standard'.")
    allowed = {
        "rank",
        "similarity",
        "title",
        "authors",
        "venue",
        "year",
        "doi",
        "pdf_link",
        "llm_score",
        "llm_reason",
        "exact_score",
        "matched_fields",
        "matched_terms",
    }
    return {key: value for key, value in result.items() if key in allowed}


def build_response(
    query,
    mode,
    model,
    selected_years,
    venues,
    must_have,
    raw_results,
    candidate_count,
    abstract_chars,
    result_view="standard",
):
    results = []
    for rank, item in enumerate(raw_results, start=1):
        compact = compact_paper(item["paper"], item.get("similarity", 0.0), rank, abstract_chars)
        if item.get("llm_score") is not None:
            compact["llm_score"] = item["llm_score"]
            compact["llm_reason"] = str(item.get("llm_reason", "") or "")
        if item.get("exact_score") is not None:
            compact["exact_score"] = item["exact_score"]
        if item.get("matched_fields") is not None:
            compact["matched_fields"] = list(item.get("matched_fields") or [])
        if item.get("matched_terms") is not None:
            compact["matched_terms"] = list(item.get("matched_terms") or [])
        results.append(_project_result_view(compact, result_view))
    return {
        "schema": AGENT_SEARCH_SCHEMA,
        "mode": mode,
        "query": query,
        "model": model,
        "result_view": result_view,
        "filters": {
            "years": list(selected_years),
            "venues": list(venues),
            "must_have": must_have,
        },
        "candidate_count": int(candidate_count),
        "result_count": len(raw_results),
        "results": results,
    }


def run_keyword_search(
    query,
    *,
    db_file,
    top_k=500,
    selected_years=(2000, 2100),
    venues=(),
    fields=KEYWORD_SEARCH_FIELDS,
    abstract_chars=0,
    result_view="standard",
    paper_loader=None,
):
    query = str(query or "").strip()
    if not query:
        raise ValueError("A non-empty exact keyword query is required.")
    fields = parse_keyword_fields(fields)
    venues = list(venues or [])
    if paper_loader is None:
        with open(db_file, "r", encoding="utf-8") as handle:
            papers = json.load(handle)
    else:
        papers = list(paper_loader(db_file))

    field_weights = {
        "title": 100,
        "authors": 90,
        "keywords": 70,
        "ieee_terms": 60,
        "doi": 55,
        "venue": 40,
        "abstract": 25,
        "year": 10,
    }
    exact_hits = []
    for paper in papers:
        year_value = extract_year(paper.get("year", ""))
        if not (selected_years[0] <= year_value <= selected_years[1]):
            continue
        venue_data = analyze_venue(paper.get("venue", ""))
        if venues and venue_data["n"] not in venues:
            continue
        details = keyword_match_details(paper, query, analyze_venue, fields)
        if not details["matched"]:
            continue
        exact_score = sum(field_weights[field] for field in details["matched_fields"])
        exact_hits.append(
            {
                "similarity": 1.0,
                "exact_score": exact_score,
                "matched_fields": details["matched_fields"],
                "matched_terms": details["matched_terms"],
                "paper": paper,
            }
        )

    exact_hits.sort(
        key=lambda item: (
            item["exact_score"],
            extract_year(item["paper"].get("year", "")),
            str(item["paper"].get("title", "") or "").lower(),
        ),
        reverse=True,
    )
    top_k = int(top_k)
    selected = exact_hits if top_k == 0 else exact_hits[: max(1, min(top_k, 5000))]
    response = build_response(
        query,
        "keyword",
        "literal",
        selected_years,
        venues,
        query,
        selected,
        len(papers),
        abstract_chars,
        result_view,
    )
    response["filters"]["fields"] = fields
    response["matched_count"] = len(exact_hits)
    return response


def run_lite_search(
    query,
    *,
    db_file,
    embedding_model,
    embedding_api_key,
    top_k=50,
    selected_years=(2000, 2100),
    venues=(),
    must_have="",
    abstract_chars=1600,
    result_view="standard",
    searcher_factory=PaperSearcher,
):
    query = str(query or "").strip()
    if not query:
        raise ValueError("A non-empty query is required.")
    top_k = max(1, min(int(top_k), 500))
    venues = list(venues or [])
    needs_prefilter = bool(venues or str(must_have or "").strip() or selected_years != (2000, 2100))
    candidate_top_k = min(max(top_k * 10, 200), 2000) if needs_prefilter else top_k

    searcher = searcher_factory(db_file, model_name=embedding_model, api_key=embedding_api_key, scope_key="all")
    raw_hits = searcher.search(query=query, top_k=candidate_top_k)
    filtered = filter_search_results(raw_hits, selected_years, venues, must_have, analyze_venue, extract_year)
    return build_response(
        query,
        "lite",
        embedding_model,
        selected_years,
        venues,
        must_have,
        filtered[:top_k],
        len(raw_hits),
        abstract_chars,
        result_view,
    )


def run_pro_search(
    query,
    *,
    db_file,
    embedding_model,
    embedding_api_key,
    llm_api_key,
    llm_base_url,
    llm_model,
    top_k=50,
    selected_years=(2000, 2100),
    venues=(),
    must_have="",
    abstract_chars=1600,
    result_view="standard",
    rerank_limit=30,
    timeout_seconds=300,
):
    from chipseeker.task_queue import cleanup_task, get_task, submit_llm_powered_search

    query = str(query or "").strip()
    if not query:
        raise ValueError("A non-empty query is required.")
    top_k = max(1, min(int(top_k), 200))
    venues = list(venues or [])
    task_id = submit_llm_powered_search(
        db_file,
        query,
        must_have,
        top_k,
        venues,
        selected_years,
        embedding_model,
        embedding_api_key=embedding_api_key,
        active_scope_key="all",
        active_scope_years=[],
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        rerank_limit=max(5, min(int(rerank_limit), 100)),
        query_state_key="agent-cli",
    )
    deadline = time.monotonic() + max(10, int(timeout_seconds))
    try:
        while time.monotonic() < deadline:
            task = get_task(task_id) or {}
            status = task.get("status")
            if status == "completed":
                result = task.get("result", {})
                return build_response(
                    query,
                    "pro",
                    llm_model,
                    selected_years,
                    venues,
                    must_have,
                    result.get("results", []),
                    result.get("initial_count", 0),
                    abstract_chars,
                    result_view,
                )
            if status in {"failed", "canceled"}:
                raise RuntimeError(task.get("error") or task.get("message") or f"Pro search {status}.")
            time.sleep(0.5)
    finally:
        cleanup_task(task_id)
    raise TimeoutError(f"Pro search exceeded {timeout_seconds} seconds.")
