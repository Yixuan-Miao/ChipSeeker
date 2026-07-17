import csv
import hashlib
import os
import re
from difflib import SequenceMatcher

from chipseeker.data_sync import build_paper_from_row, is_junk_paper
from chipseeker.utils import load_json, normalize_doi, normalize_text, normalize_title, save_json


def collect_source_records(source_csv_files, logger=None):
    records = []
    for file in source_csv_files:
        try:
            with open(file, mode="r", encoding="utf-8-sig", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row_number, row in enumerate(reader, start=2):
                    title = normalize_text(row.get("Document Title", ""))
                    abstract = normalize_text(row.get("Abstract", ""))
                    if not title or not abstract or is_junk_paper(title, abstract):
                        continue
                    paper = build_paper_from_row(row)
                    records.append(
                        {
                            "paper": paper,
                            "source_file": file,
                            "row_number": row_number,
                            "title_key": normalize_title(paper.get("title", "")),
                            "doi_key": normalize_doi(paper.get("doi", "")),
                            "abstract_hash": hashlib.sha1(abstract.encode("utf-8")).hexdigest()[:10],
                            "abstract_text": abstract,
                        }
                    )
        except Exception as exc:
            if logger:
                logger.warning("Failed to parse conflict candidates from %s: %s", file, exc)
    return records


def _source_item(record):
    paper = record["paper"]
    return {
        "title": paper.get("title", ""),
        "year": paper.get("year", ""),
        "doi": paper.get("doi", ""),
        "venue": paper.get("venue", ""),
        "abstract_preview": paper.get("abstract", "")[:220],
        "source_file": record["source_file"],
        "row_number": record["row_number"],
    }


def _is_book_like_record(record):
    paper = record["paper"]
    venue = normalize_text(paper.get("venue", "")).lower()
    title = normalize_text(paper.get("title", "")).lower()
    book_tokens = ("textbook", "book", "chapter", "appendix", "handbook", "monograph", "lecture notes")
    chapter_prefixes = ("chapter ", "appendix ", "part ", "section ")
    return any(token in venue for token in book_tokens) or any(token in title for token in book_tokens) or title.startswith(chapter_prefixes)


def _abstracts_materially_different(group):
    abstracts = []
    for item in group:
        abstract = normalize_text(item.get("abstract_text", ""))
        if abstract and abstract not in abstracts:
            abstracts.append(abstract)
    for index, left in enumerate(abstracts):
        for right in abstracts[index + 1:]:
            shorter, longer = sorted((left, right), key=len)
            if shorter in longer and len(shorter) >= 120:
                continue
            left_terms = set(re.findall(r"\w+", left.lower()))
            right_terms = set(re.findall(r"\w+", right.lower()))
            union = left_terms | right_terms
            similarity = len(left_terms & right_terms) / max(1, len(union))
            if similarity < 0.55:
                return True
    return False


def _comparable_title(value):
    return re.sub(r"[^a-z0-9]+", " ", normalize_title(value)).strip()


def _titles_materially_different(titles):
    comparable = []
    for title in titles:
        normalized = _comparable_title(title)
        if normalized and normalized not in comparable:
            comparable.append(normalized)
    for index, left in enumerate(comparable):
        for right in comparable[index + 1:]:
            if SequenceMatcher(None, left, right, autojunk=False).ratio() < 0.82:
                return True
    return False


def detect_conflicts(records):
    conflicts = []

    by_title = {}
    by_doi = {}
    for record in records:
        if record["title_key"]:
            by_title.setdefault(record["title_key"], []).append(record)
        if record["doi_key"]:
            by_doi.setdefault(record["doi_key"], []).append(record)

    for title_key, group in by_title.items():
        no_doi_group = [item for item in group if not item["doi_key"]]
        years = sorted(
            {
                normalize_text(item["paper"].get("year", ""))
                for item in no_doi_group
                if normalize_text(item["paper"].get("year", ""))
            }
        )
        if len(years) > 1:
            conflicts.append(
                {
                    "id": f"title_year::{title_key}",
                    "kind": "same_title_different_year",
                    "severity": "medium",
                    "headline": group[0]["paper"].get("title", title_key),
                    "summary": f"Same normalized title appears with multiple years: {', '.join(years)}.",
                    "sources": [_source_item(item) for item in no_doi_group],
                    "signals": {"years": years, "dois": []},
                }
            )

    for doi_key, group in by_doi.items():
        abstract_hashes = sorted({item["abstract_hash"] for item in group})
        titles = sorted({normalize_text(item["paper"].get("title", "")) for item in group if normalize_text(item["paper"].get("title", ""))})
        normalized_titles = {_comparable_title(title) for title in titles if _comparable_title(title)}
        if len(group) > 1 and all(_is_book_like_record(item) for item in group):
            continue
        if len(abstract_hashes) > 1 and _abstracts_materially_different(group):
            conflicts.append(
                {
                    "id": f"doi_abstract::{doi_key}",
                    "kind": "same_doi_different_abstract",
                    "severity": "high",
                    "headline": group[0]["paper"].get("doi", doi_key),
                    "summary": "Same DOI appears with materially different abstracts.",
                    "sources": [_source_item(item) for item in group],
                    "signals": {"titles": titles, "abstract_hashes": abstract_hashes},
                }
            )
        if len(normalized_titles) > 1 and _titles_materially_different(titles):
            conflicts.append(
                {
                    "id": f"doi_title::{doi_key}",
                    "kind": "same_doi_different_title",
                    "severity": "high",
                    "headline": group[0]["paper"].get("doi", doi_key),
                    "summary": "Same DOI appears under different titles.",
                    "sources": [_source_item(item) for item in group],
                    "signals": {"titles": titles, "abstract_hashes": abstract_hashes},
                }
            )

    conflicts.sort(key=lambda item: (item["kind"], item["headline"].lower()))
    return conflicts


def load_conflict_resolutions(path, logger=None):
    payload = load_json(path, {"dismissed": []})
    if not isinstance(payload, dict):
        payload = {"dismissed": []}
    payload.setdefault("dismissed", [])
    return payload


def save_conflict_resolutions(path, payload):
    save_json(path, payload)


def dismiss_conflict(path, conflict_id):
    payload = load_conflict_resolutions(path)
    dismissed = set(payload.get("dismissed", []))
    dismissed.add(conflict_id)
    payload["dismissed"] = sorted(dismissed)
    save_conflict_resolutions(path, payload)


def restore_conflicts(path):
    save_conflict_resolutions(path, {"dismissed": []})
