"""Structured literal search over ChipSeeker paper metadata."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache


KEYWORD_SEARCH_FIELDS = (
    "title",
    "abstract",
    "authors",
    "venue",
    "year",
    "keywords",
    "ieee_terms",
    "doi",
)

_SYMBOL_TRANSLATION = str.maketrans(
    {
        "µ": "u",
        "μ": "u",
        "Ω": " ohm ",
        "Ω": " ohm ",
        "ω": " omega ",
        "×": "x",
        "–": "-",
        "—": "-",
        "−": "-",
        "‑": "-",
    }
)


def normalize_search_text(value):
    text = unicodedata.normalize("NFKD", str(value or "").translate(_SYMBOL_TRANSLATION))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"(?<=[a-zA-Z])(?=\d)|(?<=\d)(?=[a-zA-Z])", " ", text)
    return re.sub(r"[^a-z0-9+]+", " ", text.lower()).strip()


def normalize_doi_selector(value):
    doi = str(value or "").strip().lower()
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi)
    return doi.strip()


def normalize_title_selector(value):
    return normalize_search_text(value)


def normalize_keyword_fields(fields):
    aliases = {
        "author": "authors",
        "keyword": "keywords",
        "ieee": "ieee_terms",
        "terms": "ieee_terms",
    }
    normalized = []
    for field in fields or KEYWORD_SEARCH_FIELDS:
        field = aliases.get(str(field or "").strip().lower(), str(field or "").strip().lower())
        if field not in KEYWORD_SEARCH_FIELDS:
            raise ValueError(
                f"Unknown keyword field '{field}'. Choose from: {', '.join(KEYWORD_SEARCH_FIELDS)}."
            )
        if field not in normalized:
            normalized.append(field)
    return normalized


def parse_legacy_groups(expression):
    groups = []
    for group in re.split(r"\s*(?:,|&|\band\b)\s*", str(expression or ""), flags=re.IGNORECASE):
        alternatives = [
            normalize_search_text(word.strip().strip('"'))
            for word in re.split(r"\s*/\s*", group)
            if word.strip()
        ]
        alternatives = [word for word in alternatives if word]
        if alternatives:
            groups.append(list(dict.fromkeys(alternatives)))
    return groups


def _normalized_term_matches(normalized_term, normalized_corpus):
    if not normalized_term:
        return False
    if " " in normalized_term:
        return f" {normalized_term} " in f" {normalized_corpus} "
    return re.search(r"\b" + re.escape(normalized_term) + r"\b", normalized_corpus) is not None


def term_matches_normalized(term, normalized_corpus):
    return _normalized_term_matches(normalize_search_text(term), normalized_corpus)


def _list_text(value):
    if isinstance(value, (list, tuple, set)):
        return " ".join(str(item) for item in value if str(item).strip())
    return str(value or "")


def paper_field_texts(paper, analyze_venue):
    authors = paper.get("authors", [])
    author_text = _list_text(authors)
    if not author_text.strip():
        author_text = f"{paper.get('first_author', '')} {paper.get('last_author', '')}"
    venue_data = analyze_venue(paper.get("venue", ""))
    venue_text = " ".join(
        [
            str(paper.get("venue", "")),
            str(venue_data.get("n", "")),
            str(venue_data.get("t", "")),
            _list_text(venue_data.get("d", [])),
        ]
    )
    return {
        "title": str(paper.get("title", "") or ""),
        "abstract": str(paper.get("abstract", "") or ""),
        "authors": author_text,
        "venue": venue_text,
        "year": str(paper.get("year", "") or ""),
        "keywords": _list_text(paper.get("keywords", [])),
        "ieee_terms": _list_text(paper.get("ieee_terms", [])),
        "doi": str(paper.get("doi", "") or ""),
    }, venue_data


@dataclass(frozen=True)
class StructuredKeywordQuery:
    expression: str = ""
    all_terms: tuple[str, ...] = ()
    any_terms: tuple[str, ...] = ()
    exact_titles: tuple[str, ...] = ()
    dois: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()

    @property
    def has_constraints(self):
        return bool(
            self.expression
            or self.all_terms
            or self.any_terms
            or self.exact_titles
            or self.dois
            or self.authors
        )

    def as_dict(self):
        return {
            "expression": self.expression,
            "all_terms": list(self.all_terms),
            "any_terms": list(self.any_terms),
            "exact_titles": list(self.exact_titles),
            "dois": list(self.dois),
            "authors": list(self.authors),
        }


def build_structured_query(
    expression="",
    *,
    all_terms=(),
    any_terms=(),
    exact_titles=(),
    dois=(),
    authors=(),
):
    return StructuredKeywordQuery(
        expression=str(expression or "").strip(),
        all_terms=tuple(dict.fromkeys(str(value).strip() for value in all_terms or () if str(value).strip())),
        any_terms=tuple(dict.fromkeys(str(value).strip() for value in any_terms or () if str(value).strip())),
        exact_titles=tuple(
            dict.fromkeys(str(value).strip() for value in exact_titles or () if str(value).strip())
        ),
        dois=tuple(dict.fromkeys(str(value).strip() for value in dois or () if str(value).strip())),
        authors=tuple(dict.fromkeys(str(value).strip() for value in authors or () if str(value).strip())),
    )


@lru_cache(maxsize=512)
def _query_match_plan(query):
    return {
        "legacy_groups": tuple(tuple(group) for group in parse_legacy_groups(query.expression)),
        "all_terms": tuple((term, normalize_search_text(term)) for term in query.all_terms),
        "any_terms": tuple((term, normalize_search_text(term)) for term in query.any_terms),
        "exact_titles": frozenset(normalize_title_selector(value) for value in query.exact_titles),
        "dois": frozenset(normalize_doi_selector(value) for value in query.dois),
        "authors": tuple((value, normalize_search_text(value)) for value in query.authors),
    }


def _match_indexed_fields(indexed_fields, query, selected_fields):
    matched_fields = set()
    matched_terms = []
    plan = _query_match_plan(query)

    identity_requested = bool(query.exact_titles or query.dois)
    if identity_requested:
        title_match = indexed_fields["title"] in plan["exact_titles"]
        doi_match = indexed_fields["doi"] in plan["dois"]
        if not (title_match or doi_match):
            return {"matched": False, "matched_fields": [], "matched_terms": []}
        if title_match:
            matched_fields.add("title")
            matched_terms.append({"selector": "exact_title"})
        if doi_match:
            matched_fields.add("doi")
            matched_terms.append({"selector": "doi"})

    if query.authors:
        author_matches = [
            value
            for value, normalized_value in plan["authors"]
            if _normalized_term_matches(normalized_value, indexed_fields["authors"])
        ]
        if not author_matches:
            return {"matched": False, "matched_fields": [], "matched_terms": []}
        matched_fields.add("authors")
        matched_terms.append({"selector": "author", "term": author_matches[0]})

    for group in plan["legacy_groups"]:
        group_match = None
        for term in group:
            term_fields = [
                field
                for field in selected_fields
                if _normalized_term_matches(term, indexed_fields[field])
            ]
            if term_fields:
                group_match = {"selector": "expression", "term": term, "fields": term_fields}
                matched_fields.update(term_fields)
                break
        if group_match is None:
            return {"matched": False, "matched_fields": [], "matched_terms": []}
        matched_terms.append(group_match)

    for term, normalized_term in plan["all_terms"]:
        term_fields = [
            field
            for field in selected_fields
            if _normalized_term_matches(normalized_term, indexed_fields[field])
        ]
        if not term_fields:
            return {"matched": False, "matched_fields": [], "matched_terms": []}
        matched_fields.update(term_fields)
        matched_terms.append({"selector": "all_term", "term": term, "fields": term_fields})

    if plan["any_terms"]:
        any_match = None
        for term, normalized_term in plan["any_terms"]:
            term_fields = [
                field
                for field in selected_fields
                if _normalized_term_matches(normalized_term, indexed_fields[field])
            ]
            if term_fields:
                any_match = {"selector": "any_term", "term": term, "fields": term_fields}
                matched_fields.update(term_fields)
                break
        if any_match is None:
            return {"matched": False, "matched_fields": [], "matched_terms": []}
        matched_terms.append(any_match)

    ordered_fields = list(selected_fields)
    for field in ("title", "doi", "authors"):
        if field in matched_fields and field not in ordered_fields:
            ordered_fields.append(field)
    return {
        "matched": True,
        "matched_fields": [field for field in ordered_fields if field in matched_fields],
        "matched_terms": matched_terms,
    }


def match_paper(paper, query, analyze_venue, fields=None):
    selected_fields = normalize_keyword_fields(fields)
    field_text, _venue_data = paper_field_texts(paper, analyze_venue)
    indexed_fields = {field: normalize_search_text(value) for field, value in field_text.items()}
    indexed_fields["doi"] = normalize_doi_selector(field_text["doi"])
    return _match_indexed_fields(indexed_fields, query, selected_fields)


class KeywordSearchIndex:
    def __init__(self, papers, analyze_venue, extract_year):
        self.papers = list(papers or [])
        self.entries = []
        self.doi_positions = {}
        self.title_positions = {}
        for index, paper in enumerate(self.papers):
            field_text, venue_data = paper_field_texts(paper, analyze_venue)
            indexed_fields = {
                "title": normalize_title_selector(field_text["title"]),
                "doi": normalize_doi_selector(field_text["doi"]),
            }
            entry = {
                "paper": paper,
                "fields": indexed_fields,
                "raw_fields": field_text,
                "year": extract_year(paper.get("year", "")),
                "venue": venue_data.get("n", ""),
            }
            self.entries.append(entry)
            doi = indexed_fields["doi"]
            title = normalize_title_selector(field_text["title"])
            if doi:
                self.doi_positions.setdefault(doi, []).append(index)
            if title:
                self.title_positions.setdefault(title, []).append(index)

    def _candidate_positions(self, query):
        if not (query.exact_titles or query.dois):
            return range(len(self.entries))
        positions = set()
        for doi in query.dois:
            positions.update(self.doi_positions.get(normalize_doi_selector(doi), []))
        for title in query.exact_titles:
            positions.update(self.title_positions.get(normalize_title_selector(title), []))
        return sorted(positions)

    @staticmethod
    def _ensure_query_fields(entry, query, selected_fields):
        required_fields = set()
        if query.expression or query.all_terms or query.any_terms:
            required_fields.update(selected_fields)
        if query.authors:
            required_fields.add("authors")
        if query.exact_titles:
            required_fields.add("title")
        if query.dois:
            required_fields.add("doi")
        for field in required_fields:
            if field not in entry["fields"]:
                entry["fields"][field] = normalize_search_text(entry["raw_fields"][field])

    def search(self, query, *, selected_years=(0, 9999), venues=(), fields=None):
        selected_fields = normalize_keyword_fields(fields)
        venues = set(venues or [])
        matches = []
        scanned_count = 0
        for position in self._candidate_positions(query):
            entry = self.entries[position]
            if not (selected_years[0] <= entry["year"] <= selected_years[1]):
                continue
            if venues and entry["venue"] not in venues:
                continue
            scanned_count += 1
            self._ensure_query_fields(entry, query, selected_fields)
            details = _match_indexed_fields(entry["fields"], query, selected_fields)
            if details["matched"]:
                matches.append(
                    {
                        "paper": entry["paper"],
                        "matched_fields": details["matched_fields"],
                        "matched_terms": details["matched_terms"],
                    }
                )
        return matches, scanned_count
