#!/usr/bin/env python3
"""Expand every retained ChipSeeker publication until work families converge."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chipseeker.agent_records import deduplicate_papers, load_paper_files
from chipseeker.agent_search import compact_paper
from chipseeker.config_store import load_app_config
from chipseeker.keyword_search import normalize_title_selector
from chipseeker.paths import CONFIG_FILE, DB_FILE, EXAMPLE_CONFIG_FILE, LEGACY_CONFIG_FILE
from chipseeker.work_family import expand_work_family_closure, full_author_keys, publication_key
from search_runtime import PaperSearcher


SCHEMA = "chipseeker-agent-work-family-closure/v1"
MAX_SINGLE_AUTHOR_CANDIDATES = 200


def build_parser():
    parser = argparse.ArgumentParser(description="Close work families for all retained papers.")
    parser.add_argument("--input", action="append", required=True, help="Retained paper JSON; repeat as needed.")
    parser.add_argument("--semantic-top-k", type=int, default=100)
    parser.add_argument("--query-workers", type=int, default=4)
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--abstract-chars", type=int, default=4000)
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


def _build_indexes(papers):
    title_index = defaultdict(list)
    author_index = defaultdict(list)
    for paper in papers:
        title = normalize_title_selector(paper.get("title", ""))
        if title:
            title_index[title].append(paper)
        for author in full_author_keys(paper):
            author_index[author].append(paper)
    return title_index, author_index


def _literal_family_candidates(paper, title_index, author_index):
    candidates = {}
    title = normalize_title_selector(paper.get("title", ""))
    for candidate in title_index.get(title, []):
        candidates[publication_key(candidate)] = candidate

    author_buckets = []
    skipped_common = []
    for author in full_author_keys(paper):
        bucket = author_index.get(author, [])
        author_buckets.append(bucket)
        if len(bucket) <= MAX_SINGLE_AUTHOR_CANDIDATES:
            for candidate in bucket:
                candidates[publication_key(candidate)] = candidate
        else:
            skipped_common.append({"author": author, "candidate_count": len(bucket)})

    if len(author_buckets) >= 2:
        shared_counts = defaultdict(int)
        shared_papers = {}
        for bucket in author_buckets:
            for candidate in bucket:
                key = publication_key(candidate)
                shared_counts[key] += 1
                shared_papers[key] = candidate
        for key, count in shared_counts.items():
            if count >= 2:
                candidates[key] = shared_papers[key]
    return candidates, skipped_common


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        seeds, sources = load_paper_files(args.input)
        seeds = deduplicate_papers(seeds)
        if not seeds:
            raise ValueError("No seed papers were found in the input files.")
        with open(DB_FILE, "r", encoding="utf-8") as handle:
            corpus = json.load(handle)
        title_index, author_index = _build_indexes(corpus)
        config = load_app_config((CONFIG_FILE, LEGACY_CONFIG_FILE, EXAMPLE_CONFIG_FILE))
        searcher = None
        semantic_enabled = args.semantic_top_k > 0
        if semantic_enabled:
            with contextlib.redirect_stdout(sys.stderr):
                searcher = PaperSearcher(
                    DB_FILE,
                    model_name=args.embedding_model or config["embedding_model"],
                    api_key=config.get("emb_api_key", ""),
                    papers_override=corpus,
                    scope_key="all",
                )

        seed_keys = {publication_key(seed) for seed in seeds}
        candidates = {publication_key(seed): seed for seed in seeds}
        expanded_keys = set()
        frontier = list(seeds)
        retrieval_rounds = []
        warnings = []
        common_author_skips = {}

        while frontier:
            round_candidates = {}
            for paper in frontier:
                literal_candidates, skipped = _literal_family_candidates(paper, title_index, author_index)
                round_candidates.update(literal_candidates)
                for item in skipped:
                    common_author_skips[item["author"]] = item["candidate_count"]

            semantic_query_count = 0
            if semantic_enabled and searcher is not None:
                query_papers = [paper for paper in frontier if str(paper.get("title", "") or "").strip()]
                if query_papers:
                    semantic_query_count = len(query_papers)
                    try:
                        with contextlib.redirect_stdout(sys.stderr):
                            batches = searcher.search_many(
                                [paper["title"] for paper in query_papers],
                                top_k=max(20, min(int(args.semantic_top_k), 500)),
                                query_workers=args.query_workers,
                            )
                        for batch in batches:
                            for hit in batch:
                                candidate = hit["paper"]
                                round_candidates[publication_key(candidate)] = candidate
                    except Exception as exc:
                        warnings.append(f"Semantic family expansion disabled after failure: {exc}")
                        semantic_enabled = False

            before_count = len(candidates)
            candidates.update(round_candidates)
            expanded_keys.update(publication_key(paper) for paper in frontier)
            closure = expand_work_family_closure(seeds, candidates.values())
            confirmed = {publication_key(paper): paper for paper in closure["confirmed"]}
            frontier = [paper for key, paper in confirmed.items() if key not in expanded_keys]
            retrieval_rounds.append(
                {
                    "round": len(retrieval_rounds) + 1,
                    "expanded_seed_count": len(expanded_keys),
                    "semantic_query_count": semantic_query_count,
                    "new_candidate_count": len(candidates) - before_count,
                    "confirmed_family_member_count": len(confirmed),
                    "next_frontier_count": len(frontier),
                }
            )

        closure = expand_work_family_closure(seeds, candidates.values())
        confirmed_results = []
        for rank, paper in enumerate(closure["confirmed"], start=1):
            compact = compact_paper(paper, 0.0, rank, max(1, args.abstract_chars))
            compact["family_relation"] = paper.get("family_relation", {})
            compact["work_family_id"] = paper.get("work_family_id", "")
            compact["work_family_size"] = paper.get("work_family_size", 1)
            compact["was_input_seed"] = publication_key(paper) in seed_keys
            confirmed_results.append(compact)
        related_results = []
        for rank, paper in enumerate(closure["related_suggestions"], start=1):
            compact = compact_paper(paper, 0.0, rank, max(1, args.abstract_chars))
            compact["family_relation"] = paper.get("family_relation", {})
            related_results.append(compact)

        payload = {
            "schema": SCHEMA,
            "input_sources": sources,
            "seed_count": len(seeds),
            "candidate_count": len(candidates),
            "confirmed_count": len(confirmed_results),
            "new_confirmed_count": sum(not item["was_input_seed"] for item in confirmed_results),
            "related_suggestion_count": len(related_results),
            "retrieval_rounds": retrieval_rounds,
            "closure_rounds": closure["rounds"],
            "warnings": warnings,
            "common_author_buckets_skipped": [
                {"author": author, "candidate_count": count}
                for author, count in sorted(common_author_skips.items())
            ],
            "results": confirmed_results,
            "related_suggestions": related_results,
        }
    except Exception as exc:
        write_json({"schema": SCHEMA, "error": str(exc)}, args.output)
        return 1
    write_json(payload, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
