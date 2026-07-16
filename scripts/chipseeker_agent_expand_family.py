#!/usr/bin/env python3
"""Expand one publication into likely conference, journal, and follow-up works."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chipseeker.agent_search import compact_paper
from chipseeker.config_store import load_app_config
from chipseeker.keyword_search import KeywordSearchIndex, build_structured_query
from chipseeker.paths import CONFIG_FILE, DB_FILE, EXAMPLE_CONFIG_FILE, LEGACY_CONFIG_FILE
from chipseeker.utils import extract_year
from chipseeker.venue_data import analyze_venue
from chipseeker.work_family import expand_work_family, publication_key
from search_runtime import PaperSearcher


SCHEMA = "chipseeker-agent-work-family/v1"


def build_parser():
    parser = argparse.ArgumentParser(description="Expand one ChipSeeker paper into its work family.")
    selectors = parser.add_mutually_exclusive_group(required=True)
    selectors.add_argument("--doi", default="")
    selectors.add_argument("--exact-title", default="")
    parser.add_argument("--semantic-top-k", type=int, default=200)
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--abstract-chars", type=int, default=1600)
    parser.add_argument("--output", default="")
    return parser


def write_json(payload, output_path=""):
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(encoded)
        os.replace(temporary, path)
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def _authors(paper):
    authors = paper.get("authors", []) or []
    if isinstance(authors, list):
        normalized = authors
    else:
        normalized = [item.strip() for item in str(authors).split(";") if item.strip()]
    if normalized:
        return normalized
    return [
        value
        for value in (paper.get("first_author", ""), paper.get("last_author", ""))
        if str(value or "").strip()
    ]


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        config = load_app_config((CONFIG_FILE, LEGACY_CONFIG_FILE, EXAMPLE_CONFIG_FILE))
        with open(DB_FILE, "r", encoding="utf-8") as handle:
            papers = json.load(handle)
        index = KeywordSearchIndex(papers, analyze_venue, extract_year)
        seed_query = build_structured_query(
            exact_titles=[args.exact_title] if args.exact_title else [],
            dois=[args.doi] if args.doi else [],
        )
        seed_matches, _ = index.search(seed_query)
        if not seed_matches:
            raise ValueError("No local-corpus paper matched the exact title or DOI.")
        seed_matches.sort(
            key=lambda item: extract_year(item["paper"].get("year", "")),
            reverse=True,
        )
        seed = seed_matches[0]["paper"]

        candidate_by_key = {}
        for match in seed_matches:
            candidate_by_key[publication_key(match["paper"])] = match["paper"]
        authors = _authors(seed)
        if authors:
            author_query = build_structured_query(authors=authors)
            author_matches, _ = index.search(author_query, fields=["authors"])
            for match in author_matches:
                candidate_by_key[publication_key(match["paper"])] = match["paper"]

        warnings = []
        with contextlib.redirect_stdout(sys.stderr):
            try:
                searcher = PaperSearcher(
                    DB_FILE,
                    model_name=args.embedding_model or config["embedding_model"],
                    api_key=config.get("emb_api_key", ""),
                    papers_override=papers,
                    scope_key="all",
                )
                semantic_hits = searcher.search(
                    str(seed.get("title", "") or ""),
                    top_k=max(20, min(int(args.semantic_top_k), 500)),
                )
                for hit in semantic_hits:
                    candidate_by_key[publication_key(hit["paper"])] = hit["paper"]
            except Exception as exc:
                warnings.append(f"Semantic family expansion failed; exact-title and author expansion still ran: {exc}")

        expanded = expand_work_family(seed, candidate_by_key.values())
        results = []
        for rank, paper in enumerate(expanded, start=1):
            compact = compact_paper(paper, 0.0, rank, args.abstract_chars)
            compact["family_relation"] = paper["family_relation"]
            results.append(compact)
        payload = {
            "schema": SCHEMA,
            "seed": compact_paper(seed, 1.0, 1, args.abstract_chars),
            "seed_match_count": len(seed_matches),
            "candidate_count": len(candidate_by_key),
            "result_count": len(results),
            "warnings": warnings,
            "results": results,
        }
    except Exception as exc:
        write_json({"schema": SCHEMA, "error": str(exc)}, args.output)
        return 1
    write_json(payload, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
