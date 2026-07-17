"""Hydrate title-first ChipSeeker candidates from the local corpus."""

from __future__ import annotations

from collections import defaultdict

from chipseeker.agent_search import compact_paper
from chipseeker.keyword_search import normalize_doi_selector, normalize_title_selector
from chipseeker.utils import extract_year
from chipseeker.work_family import publication_key


HYDRATE_SCHEMA = "chipseeker-agent-hydrate/v1"


def _indexes(papers):
    by_doi = defaultdict(list)
    by_title_year = defaultdict(list)
    by_title = defaultdict(list)
    for paper in papers or []:
        doi = normalize_doi_selector(paper.get("doi", ""))
        title = normalize_title_selector(paper.get("title", ""))
        year = extract_year(paper.get("year", ""))
        if doi:
            by_doi[doi].append(paper)
        if title:
            by_title_year[(title, year)].append(paper)
            by_title[title].append(paper)
    return by_doi, by_title_year, by_title


def _resolve_candidate(candidate, indexes):
    by_doi, by_title_year, by_title = indexes
    doi = normalize_doi_selector(candidate.get("doi", ""))
    title = normalize_title_selector(candidate.get("title", ""))
    year = extract_year(candidate.get("year", ""))
    if doi:
        unique = {publication_key(paper): paper for paper in by_doi.get(doi, [])}
        if len(unique) == 1:
            return next(iter(unique.values())), "doi", []
        if len(unique) > 1:
            return None, "ambiguous", list(unique.values())
        return None, "missing", []
    strategies = []
    if title and year:
        strategies.append(("title_year", by_title_year.get((title, year), [])))
    if title:
        strategies.append(("exact_title", by_title.get(title, [])))
    for matched_by, matches in strategies:
        unique = {publication_key(paper): paper for paper in matches}
        if len(unique) == 1:
            return next(iter(unique.values())), matched_by, []
        if len(unique) > 1:
            return None, "ambiguous", list(unique.values())
    return None, "missing", []


def hydrate_candidates(candidates, corpus_papers, abstract_chars=10000):
    indexes = _indexes(corpus_papers)
    hydrated = []
    unresolved = []
    seen = set()
    for candidate in candidates or []:
        candidate_key = publication_key(candidate)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        paper, matched_by, ambiguous = _resolve_candidate(candidate, indexes)
        if paper is None:
            unresolved.append(
                {
                    "publication_key": candidate_key,
                    "title": str(candidate.get("title", "") or ""),
                    "year": str(candidate.get("year", "") or ""),
                    "doi": str(candidate.get("doi", "") or ""),
                    "status": matched_by,
                    "candidate_matches": [publication_key(item) for item in ambiguous],
                }
            )
            continue
        compact = compact_paper(
            paper,
            float(candidate.get("similarity", 0.0) or 0.0),
            len(hydrated) + 1,
            abstract_chars,
        )
        for field in (
            "retrievals",
            "retrieval_count",
            "retrieval_family_count",
            "retrieval_mode_count",
            "query_role",
            "work_family_id",
            "work_family_size",
            "screening_decision",
            "screening_reason",
        ):
            if field in candidate:
                compact[field] = candidate[field]
        compact["hydration"] = {
            "status": "matched",
            "matched_by": matched_by,
            "source_in_current_corpus": True,
        }
        hydrated.append(compact)
    return {
        "schema": HYDRATE_SCHEMA,
        "requested_count": len(seen),
        "matched_count": len(hydrated),
        "unresolved_count": len(unresolved),
        "results": hydrated,
        "unresolved": unresolved,
    }
