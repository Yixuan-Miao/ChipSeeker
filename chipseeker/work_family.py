"""Link conference, journal, and follow-up publications without merging them."""

from __future__ import annotations

import hashlib

from chipseeker.keyword_search import (
    normalize_doi_selector,
    normalize_search_text,
    normalize_title_selector,
)
from chipseeker.utils import extract_year


_TITLE_STOPWORDS = {
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


def _title_tokens(paper):
    return {
        token
        for token in normalize_search_text(paper.get("title", "")).split()
        if token not in _TITLE_STOPWORDS and len(token) > 1
    }


def _full_author_keys(paper):
    authors = paper.get("authors", []) or []
    if not isinstance(authors, (list, tuple, set)):
        authors = [item.strip() for item in str(authors).split(";") if item.strip()]
    if not authors:
        authors = [
            value
            for value in (paper.get("first_author", ""), paper.get("last_author", ""))
            if str(value or "").strip()
        ]
    return {
        normalize_search_text(author)
        for author in authors
        if normalize_search_text(author)
    }


def full_author_keys(paper):
    """Return normalized full-author identities for external family tooling."""
    return _full_author_keys(paper)


def _author_keys(paper):
    full_keys = _full_author_keys(paper)
    keys = set(full_keys)
    for normalized in full_keys:
        parts = normalized.split()
        if parts:
            keys.add(parts[-1])
    return keys


def _jaccard(left, right):
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _containment(left, right):
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def publication_key(paper):
    doi = normalize_doi_selector(paper.get("doi", ""))
    if doi:
        return f"doi:{doi}"
    title = normalize_title_selector(paper.get("title", ""))
    year = extract_year(paper.get("year", ""))
    if title and year:
        return f"title_year:{title}|{year}"
    if title:
        return f"title:{title}"
    payload = "|".join(
        str(paper.get(field, "") or "")
        for field in ("authors", "venue", "year", "abstract")
    )
    return "metadata:" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def relation_between(seed, candidate):
    seed_doi = normalize_doi_selector(seed.get("doi", ""))
    candidate_doi = normalize_doi_selector(candidate.get("doi", ""))
    if seed_doi and candidate_doi and seed_doi == candidate_doi:
        return {
            "relation": "same_publication",
            "confidence": 1.0,
            "title_similarity": 1.0,
            "shared_authors": [],
        }

    seed_title = normalize_title_selector(seed.get("title", ""))
    candidate_title = normalize_title_selector(candidate.get("title", ""))
    seed_authors = _full_author_keys(seed)
    candidate_authors = _full_author_keys(candidate)
    shared_authors = sorted(seed_authors & candidate_authors)
    title_tokens = _title_tokens(seed)
    candidate_tokens = _title_tokens(candidate)
    jaccard = _jaccard(title_tokens, candidate_tokens)
    containment = _containment(title_tokens, candidate_tokens)
    title_overlap = len(title_tokens & candidate_tokens)
    seed_year = extract_year(seed.get("year", ""))
    candidate_year = extract_year(candidate.get("year", ""))
    year_gap = abs(seed_year - candidate_year) if seed_year and candidate_year else None

    if seed_title and seed_title == candidate_title:
        relation = "publication_variant"
        confidence = 1.0 if shared_authors else 0.95
    elif shared_authors and containment >= 0.85 and jaccard >= 0.62 and (year_gap is None or year_gap <= 5):
        relation = "likely_extension"
        confidence = min(0.98, 0.55 + 0.25 * containment + 0.15 * jaccard + 0.03 * len(shared_authors))
    elif shared_authors and containment >= 0.65 and jaccard >= 0.42 and (year_gap is None or year_gap <= 7):
        relation = "related_followup"
        confidence = min(0.88, 0.4 + 0.22 * containment + 0.15 * jaccard + 0.02 * len(shared_authors))
    elif (
        len(shared_authors) >= 2
        and title_overlap >= 2
        and jaccard >= 0.22
        and (year_gap is None or year_gap <= 7)
    ):
        relation = "related_followup"
        confidence = min(
            0.84,
            0.36 + 0.05 * len(shared_authors) + 0.12 * containment + 0.12 * jaccard,
        )
    else:
        relation = "unrelated"
        confidence = 0.0

    return {
        "relation": relation,
        "confidence": round(confidence, 4),
        "title_similarity": round(jaccard, 4),
        "title_containment": round(containment, 4),
        "title_overlap": title_overlap,
        "shared_authors": shared_authors,
        "year_gap": year_gap,
    }


def assign_work_families(papers):
    papers = list(papers or [])
    parent = list(range(len(papers)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    title_positions = {}
    author_positions = {}
    for index, paper in enumerate(papers):
        title = normalize_title_selector(paper.get("title", ""))
        if title:
            for other in title_positions.get(title, []):
                union(index, other)
            title_positions.setdefault(title, []).append(index)
        for author in _author_keys(paper):
            if len(author) > 3:
                author_positions.setdefault(author, []).append(index)

    compared = set()
    for positions in author_positions.values():
        if len(positions) > 80:
            continue
        for offset, left in enumerate(positions):
            for right in positions[offset + 1 :]:
                pair = (min(left, right), max(left, right))
                if pair in compared:
                    continue
                compared.add(pair)
                relation = relation_between(papers[left], papers[right])
                if relation["relation"] in {"publication_variant", "likely_extension"}:
                    union(left, right)

    groups = {}
    for index in range(len(papers)):
        groups.setdefault(find(index), []).append(index)

    for indexes in groups.values():
        identity = min(publication_key(papers[index]) for index in indexes)
        family_id = "wf:" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
        for index in indexes:
            papers[index]["work_family_id"] = family_id
            papers[index]["work_family_size"] = len(indexes)
    return papers


def expand_work_family(seed, candidates):
    expanded = []
    seed_key = publication_key(seed)
    seen = set()
    for candidate in candidates or []:
        key = publication_key(candidate)
        if key == seed_key or key in seen:
            continue
        seen.add(key)
        relation = relation_between(seed, candidate)
        if relation["relation"] == "unrelated":
            continue
        item = dict(candidate)
        item["family_relation"] = relation
        expanded.append(item)
    expanded.sort(
        key=lambda item: (
            item["family_relation"]["relation"] == "publication_variant",
            item["family_relation"]["relation"] == "likely_extension",
            item["family_relation"]["confidence"],
            extract_year(item.get("year", "")),
        ),
        reverse=True,
    )
    return expanded


def expand_work_family_closure(seeds, candidates):
    """Expand likely publication variants/extensions until the family set converges."""
    seeds = list(seeds or [])
    candidates = list(candidates or [])
    selected = {publication_key(seed): dict(seed) for seed in seeds}
    remaining = {
        publication_key(candidate): candidate
        for candidate in candidates
        if publication_key(candidate) not in selected
    }
    relation_paths = {}
    rounds = []

    def parent_indexes():
        by_author = {}
        by_title = {}
        for key, paper in selected.items():
            title = normalize_title_selector(paper.get("title", ""))
            if title:
                by_title.setdefault(title, set()).add(key)
            for author in _full_author_keys(paper):
                by_author.setdefault(author, set()).add(key)
        return by_author, by_title

    def possible_parents(candidate, by_author, by_title):
        keys = set()
        title = normalize_title_selector(candidate.get("title", ""))
        if title:
            keys.update(by_title.get(title, ()))
        for author in _full_author_keys(candidate):
            keys.update(by_author.get(author, ()))
        return keys

    while remaining:
        selected_by_author, selected_by_title = parent_indexes()
        additions = {}
        for candidate_key, candidate in remaining.items():
            best = None
            best_parent = None
            for parent_key in possible_parents(candidate, selected_by_author, selected_by_title):
                parent = selected[parent_key]
                relation = relation_between(parent, candidate)
                if relation["relation"] not in {"publication_variant", "likely_extension"}:
                    continue
                if best is None or relation["confidence"] > best["confidence"]:
                    best = relation
                    best_parent = parent_key
            if best is not None:
                additions[candidate_key] = dict(candidate)
                relation_paths[candidate_key] = {
                    "parent_publication_key": best_parent,
                    **best,
                }
        if not additions:
            break
        selected.update(additions)
        for key in additions:
            remaining.pop(key, None)
        rounds.append(
            {
                "round": len(rounds) + 1,
                "added_count": len(additions),
                "added_publication_keys": sorted(additions),
            }
        )

    related = []
    selected_by_author, selected_by_title = parent_indexes()
    for candidate_key, candidate in remaining.items():
        best = None
        best_parent = None
        for parent_key in possible_parents(candidate, selected_by_author, selected_by_title):
            parent = selected[parent_key]
            relation = relation_between(parent, candidate)
            if relation["relation"] != "related_followup":
                continue
            if best is None or relation["confidence"] > best["confidence"]:
                best = relation
                best_parent = parent_key
        if best is not None:
            item = dict(candidate)
            item["family_relation"] = {"parent_publication_key": best_parent, **best}
            related.append(item)

    confirmed = list(selected.values())
    assign_work_families(confirmed)
    for paper in confirmed:
        key = publication_key(paper)
        if key in relation_paths:
            paper["family_relation"] = relation_paths[key]
        else:
            paper["family_relation"] = {"relation": "seed", "confidence": 1.0}
    related.sort(
        key=lambda item: (
            item["family_relation"]["confidence"],
            extract_year(item.get("year", "")),
        ),
        reverse=True,
    )
    return {
        "rounds": rounds,
        "confirmed": confirmed,
        "related_suggestions": related,
    }
