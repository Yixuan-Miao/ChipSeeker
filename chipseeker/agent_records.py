"""Shared record loading and identity helpers for agent workflows."""

from __future__ import annotations

import json
from pathlib import Path

from chipseeker.work_family import publication_key


def extract_papers(payload):
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for field in ("results", "papers", "decisions"):
        value = payload.get(field)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def load_paper_files(paths):
    papers = []
    sources = []
    for value in paths or []:
        path = Path(value)
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        extracted = extract_papers(payload)
        papers.extend(extracted)
        sources.append({"path": str(path.resolve()), "paper_count": len(extracted)})
    return papers, sources


def deduplicate_papers(papers):
    merged = {}
    order = []
    for paper in papers or []:
        key = publication_key(paper)
        if key not in merged:
            merged[key] = dict(paper)
            order.append(key)
            continue
        existing = merged[key]
        for field, value in paper.items():
            if field not in existing or not existing[field]:
                existing[field] = value
            elif field == "abstract" and len(str(value or "")) > len(str(existing[field] or "")):
                existing[field] = value
    return [merged[key] for key in order]


def index_screening_decisions(records):
    decisions = {}
    for record in records or []:
        decision = str(record.get("screening_decision", record.get("decision", "")) or "").strip().lower()
        if not decision:
            continue
        item = dict(record)
        item["screening_decision"] = decision
        decisions[publication_key(item)] = item
    return decisions
