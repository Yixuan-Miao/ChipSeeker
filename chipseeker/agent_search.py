"""Machine-friendly local search functions for coding-agent workflows."""

from __future__ import annotations

import json
import time
from datetime import datetime
from urllib.parse import quote

from chipseeker.keyword_search import (
    KEYWORD_SEARCH_FIELDS,
    KeywordSearchIndex,
    build_structured_query,
    normalize_doi_selector,
    normalize_keyword_fields,
    normalize_title_selector,
)
from chipseeker.search_ui import (
    filter_search_results,
)
from chipseeker.utils import extract_year
from chipseeker.venue_data import analyze_venue
from search_runtime import PaperSearcher


AGENT_SEARCH_SCHEMA = "chipseeker-agent-search/v1"


class ProSearchError(RuntimeError):
    def __init__(self, message, attempts):
        super().__init__(message)
        self.attempts = list(attempts or [])


def _doi_link(value):
    doi = normalize_doi_selector(value)
    return f"https://doi.org/{quote(doi, safe='/():._-')}" if doi else ""


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

    doi = str(paper.get("doi", "") or "")
    pdf_link = str(paper.get("pdf_link", "") or "")
    result = {
        "rank": int(rank),
        "similarity": round(float(similarity), 6),
        "title": str(paper.get("title", "") or ""),
        "abstract": abstract[:abstract_chars] if abstract_chars else "",
        "abstract_truncated": truncated,
        "authors": authors,
        "venue": str(paper.get("venue", "") or ""),
        "year": str(paper.get("year", "") or ""),
        "doi": doi,
        "doi_link": _doi_link(doi),
        "pdf_link": pdf_link,
        "source_links": {
            "doi": _doi_link(doi),
            "pdf": pdf_link,
        },
        "source_in_current_corpus": True,
        "abstract_kind": "source_abstract" if abstract else "missing",
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
        "doi_link",
        "pdf_link",
        "source_links",
        "source_in_current_corpus",
        "abstract_kind",
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
    extra_filters=None,
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
    filters = {
        "years": list(selected_years),
        "venues": list(venues),
        "must_have": must_have,
    }
    filters.update(extra_filters or {})
    return {
        "schema": AGENT_SEARCH_SCHEMA,
        "mode": mode,
        "query": query,
        "model": model,
        "result_view": result_view,
        "filters": filters,
        "candidate_count": int(candidate_count),
        "result_count": len(raw_results),
        "results": results,
    }


def _load_papers(db_file, paper_loader=None):
    if paper_loader is None:
        with open(db_file, "r", encoding="utf-8") as handle:
            return json.load(handle)
    return list(paper_loader(db_file))


def _keyword_index(db_file, *, keyword_index=None, papers=None, paper_loader=None):
    if keyword_index is not None:
        return keyword_index
    papers = list(papers) if papers is not None else _load_papers(db_file, paper_loader)
    return KeywordSearchIndex(papers, analyze_venue, extract_year)


def _exact_score(fields):
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
    return sum(field_weights.get(field, 0) for field in fields)


def _paper_lookup_key(paper):
    doi = normalize_doi_selector(paper.get("doi", ""))
    if doi:
        return f"doi:{doi}"
    title = normalize_title_selector(paper.get("title", ""))
    return f"title_year:{title}|{extract_year(paper.get('year', ''))}"


def run_keyword_search(
    query="",
    *,
    db_file,
    top_k=500,
    selected_years=(2000, 2100),
    venues=(),
    fields=KEYWORD_SEARCH_FIELDS,
    abstract_chars=0,
    result_view="standard",
    paper_loader=None,
    papers=None,
    keyword_index=None,
    all_terms=(),
    any_terms=(),
    exact_titles=(),
    dois=(),
    authors=(),
):
    query = str(query or "").strip()
    structured_query = build_structured_query(
        query,
        all_terms=all_terms,
        any_terms=any_terms,
        exact_titles=exact_titles,
        dois=dois,
        authors=authors,
    )
    if not structured_query.has_constraints:
        raise ValueError("At least one keyword expression or structured selector is required.")
    fields = parse_keyword_fields(fields)
    venues = list(venues or [])
    index = _keyword_index(
        db_file,
        keyword_index=keyword_index,
        papers=papers,
        paper_loader=paper_loader,
    )
    matches, scanned_count = index.search(
        structured_query,
        selected_years=selected_years,
        venues=venues,
        fields=fields,
    )
    exact_hits = []
    for match in matches:
        exact_hits.append(
            {
                "similarity": 1.0,
                "exact_score": _exact_score(match["matched_fields"]),
                "matched_fields": match["matched_fields"],
                "matched_terms": match["matched_terms"],
                "paper": match["paper"],
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
        query or "structured keyword query",
        "keyword",
        "literal",
        selected_years,
        venues,
        "",
        selected,
        len(index.papers),
        abstract_chars,
        result_view,
        extra_filters={
            "fields": fields,
            "structured": structured_query.as_dict(),
        },
    )
    response["matched_count"] = len(exact_hits)
    response["scanned_count"] = scanned_count
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
    searcher=None,
):
    query = str(query or "").strip()
    if not query:
        raise ValueError("A non-empty query is required.")
    top_k = max(1, min(int(top_k), 500))
    venues = list(venues or [])
    needs_prefilter = bool(venues or str(must_have or "").strip() or selected_years != (2000, 2100))
    candidate_top_k = min(max(top_k * 10, 200), 2000) if needs_prefilter else top_k

    searcher = searcher or searcher_factory(
        db_file,
        model_name=embedding_model,
        api_key=embedding_api_key,
        scope_key="all",
    )
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


def run_lite_searches(
    queries,
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
    searcher=None,
    query_workers=None,
):
    queries = [str(query or "").strip() for query in queries or []]
    if not queries or any(not query for query in queries):
        raise ValueError("Every Lite query must be non-empty.")
    top_k = max(1, min(int(top_k), 500))
    venues = list(venues or [])
    needs_prefilter = bool(venues or str(must_have or "").strip() or selected_years != (2000, 2100))
    candidate_top_k = min(max(top_k * 10, 200), 2000) if needs_prefilter else top_k
    searcher = searcher or searcher_factory(
        db_file,
        model_name=embedding_model,
        api_key=embedding_api_key,
        scope_key="all",
    )
    if hasattr(searcher, "search_many"):
        if query_workers is None:
            raw_batches = searcher.search_many(queries, top_k=candidate_top_k)
        else:
            raw_batches = searcher.search_many(
                queries,
                top_k=candidate_top_k,
                query_workers=query_workers,
            )
    else:
        raw_batches = [searcher.search(query=query, top_k=candidate_top_k) for query in queries]

    responses = []
    for query, raw_hits in zip(queries, raw_batches):
        filtered = filter_search_results(
            raw_hits,
            selected_years,
            venues,
            must_have,
            analyze_venue,
            extract_year,
        )
        responses.append(
            build_response(
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
        )
    return responses


def run_filtered_lite_searches(
    queries,
    *,
    db_file,
    embedding_model,
    embedding_api_key,
    top_k=50,
    selected_years=(2000, 2100),
    venues=(),
    fields=KEYWORD_SEARCH_FIELDS,
    abstract_chars=1600,
    result_view="standard",
    searcher_factory=PaperSearcher,
    searcher=None,
    paper_loader=None,
    papers=None,
    keyword_index=None,
    query_workers=None,
    expression="",
    all_terms=(),
    any_terms=(),
    exact_titles=(),
    dois=(),
    authors=(),
):
    queries = [str(query or "").strip() for query in queries or []]
    if not queries or any(not query for query in queries):
        raise ValueError("Every filtered Lite query must be non-empty.")
    structured_query = build_structured_query(
        expression,
        all_terms=all_terms,
        any_terms=any_terms,
        exact_titles=exact_titles,
        dois=dois,
        authors=authors,
    )
    if not structured_query.has_constraints:
        raise ValueError("Filtered Lite requires at least one keyword expression or structured selector.")
    fields = parse_keyword_fields(fields)
    venues = list(venues or [])
    top_k = max(1, min(int(top_k), 500))
    index = _keyword_index(
        db_file,
        keyword_index=keyword_index,
        papers=papers,
        paper_loader=paper_loader,
    )
    matches, scanned_count = index.search(
        structured_query,
        selected_years=selected_years,
        venues=venues,
        fields=fields,
    )
    candidate_papers = [match["paper"] for match in matches]
    match_details = {_paper_lookup_key(match["paper"]): match for match in matches}
    searcher = searcher or searcher_factory(
        db_file,
        model_name=embedding_model,
        api_key=embedding_api_key,
        scope_key="all",
    )
    if hasattr(searcher, "search_candidates_many"):
        if query_workers is None:
            raw_batches = searcher.search_candidates_many(
                queries,
                candidate_papers,
                top_k=top_k,
            )
        else:
            raw_batches = searcher.search_candidates_many(
                queries,
                candidate_papers,
                top_k=top_k,
                query_workers=query_workers,
            )
    else:
        raw_batches = [
            searcher.search_candidates(query, candidate_papers, top_k=top_k)
            for query in queries
        ]

    responses = []
    for query, raw_hits in zip(queries, raw_batches):
        enriched_hits = []
        for hit in raw_hits:
            details = match_details.get(_paper_lookup_key(hit["paper"]), {})
            enriched = dict(hit)
            enriched["exact_score"] = _exact_score(details.get("matched_fields", []))
            enriched["matched_fields"] = details.get("matched_fields", [])
            enriched["matched_terms"] = details.get("matched_terms", [])
            enriched_hits.append(enriched)
        response = build_response(
            query,
            "filtered_lite",
            embedding_model,
            selected_years,
            venues,
            "",
            enriched_hits,
            len(candidate_papers),
            abstract_chars,
            result_view,
            extra_filters={
                "fields": fields,
                "structured": structured_query.as_dict(),
            },
        )
        response["matched_count"] = len(candidate_papers)
        response["scanned_count"] = scanned_count
        responses.append(response)
    return responses


def run_filtered_lite_search(query, **kwargs):
    return run_filtered_lite_searches([query], **kwargs)[0]


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
    fallback_models=(),
):
    models = []
    for model in (llm_model, *(fallback_models or ())):
        normalized = str(model or "").strip()
        if normalized and normalized not in models:
            models.append(normalized)
    if not models:
        raise ValueError("At least one Pro LLM model is required.")

    attempts = []
    last_error = None
    for attempt_index, model in enumerate(models):
        attempt_rerank_limit = min(int(rerank_limit), 25) if attempt_index else int(rerank_limit)
        started_at = time.monotonic()
        try:
            response = _run_pro_search_once(
                query,
                db_file=db_file,
                embedding_model=embedding_model,
                embedding_api_key=embedding_api_key,
                llm_api_key=llm_api_key,
                llm_base_url=llm_base_url,
                llm_model=model,
                top_k=top_k,
                selected_years=selected_years,
                venues=venues,
                must_have=must_have,
                abstract_chars=abstract_chars,
                result_view=result_view,
                rerank_limit=attempt_rerank_limit,
                timeout_seconds=timeout_seconds,
            )
            attempts.append(
                {
                    "model": model,
                    "status": "completed",
                    "rerank_limit": attempt_rerank_limit,
                    "duration_seconds": round(time.monotonic() - started_at, 3),
                }
            )
            response["pro_attempts"] = attempts
            response["pro_fallback_used"] = attempt_index > 0
            return response
        except Exception as exc:
            last_error = exc
            attempts.append(
                {
                    "model": model,
                    "status": "failed",
                    "rerank_limit": attempt_rerank_limit,
                    "duration_seconds": round(time.monotonic() - started_at, 3),
                    "error": str(exc),
                }
            )
    details = "; ".join(f"{item['model']}: {item['error']}" for item in attempts)
    raise ProSearchError(f"All Pro search models failed ({details}).", attempts) from last_error


def _run_pro_search_once(
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
