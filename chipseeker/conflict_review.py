import csv
import hashlib
import os

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
        years = sorted({normalize_text(item["paper"].get("year", "")) for item in group if normalize_text(item["paper"].get("year", ""))})
        dois = sorted({item["doi_key"] for item in group if item["doi_key"]})
        if len(years) > 1:
            conflicts.append(
                {
                    "id": f"title_year::{title_key}",
                    "kind": "same_title_different_year",
                    "headline": group[0]["paper"].get("title", title_key),
                    "summary": f"Same normalized title appears with multiple years: {', '.join(years)}.",
                    "sources": [_source_item(item) for item in group],
                    "signals": {"years": years, "dois": dois},
                }
            )
        if len(dois) > 1:
            conflicts.append(
                {
                    "id": f"title_doi::{title_key}",
                    "kind": "same_title_different_doi",
                    "headline": group[0]["paper"].get("title", title_key),
                    "summary": f"Same normalized title appears with multiple DOIs: {', '.join(dois)}.",
                    "sources": [_source_item(item) for item in group],
                    "signals": {"years": years, "dois": dois},
                }
            )

    for doi_key, group in by_doi.items():
        abstract_hashes = sorted({item["abstract_hash"] for item in group})
        titles = sorted({normalize_text(item["paper"].get("title", "")) for item in group if normalize_text(item["paper"].get("title", ""))})
        if len(group) > 1 and all(_is_book_like_record(item) for item in group):
            continue
        if len(abstract_hashes) > 1:
            conflicts.append(
                {
                    "id": f"doi_abstract::{doi_key}",
                    "kind": "same_doi_different_abstract",
                    "headline": group[0]["paper"].get("doi", doi_key),
                    "summary": "Same DOI appears with materially different abstracts.",
                    "sources": [_source_item(item) for item in group],
                    "signals": {"titles": titles, "abstract_hashes": abstract_hashes},
                }
            )
        if len(titles) > 1:
            conflicts.append(
                {
                    "id": f"doi_title::{doi_key}",
                    "kind": "same_doi_different_title",
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
