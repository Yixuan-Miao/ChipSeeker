#!/usr/bin/env python3
"""Run several ChipSeeker retrieval passes and emit one deduplicated JSON set."""

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

from chipseeker.agent_collect import merge_search_responses
from chipseeker.agent_search import (
    parse_keyword_fields,
    parse_venues,
    parse_year_range,
    run_filtered_lite_searches,
    run_keyword_search,
    run_lite_searches,
    run_pro_search,
)
from chipseeker.config_store import load_app_config
from chipseeker.keyword_search import KeywordSearchIndex
from chipseeker.paths import CONFIG_FILE, DB_FILE, EXAMPLE_CONFIG_FILE, LEGACY_CONFIG_FILE
from chipseeker.utils import extract_year
from chipseeker.venue_data import analyze_venue
from search_runtime import PaperSearcher


def build_parser():
    parser = argparse.ArgumentParser(description="Collect and deduplicate multiple ChipSeeker searches.")
    parser.add_argument("--lite-query", action="append", default=[], help="Repeat for broad semantic recall.")
    parser.add_argument("--keyword-query", action="append", default=[], help="Repeat for exact AND/OR recall.")
    parser.add_argument(
        "--filtered-lite-query",
        action="append",
        default=[],
        help="Repeat for semantic ranking inside one shared hard-filtered subset.",
    )
    parser.add_argument("--pro-query", action="append", default=[], help="Repeat only for focused LLM reranking.")
    parser.add_argument("--lite-top-k", type=int, default=200)
    parser.add_argument("--keyword-top-k", type=int, default=0, help="0 returns every exact match.")
    parser.add_argument("--pro-top-k", type=int, default=30)
    parser.add_argument("--fields", default="", help="Fields used by every keyword query.")
    parser.add_argument(
        "--keyword-expression",
        default="",
        help="Hard expression shared by structured keyword and filtered-lite searches.",
    )
    parser.add_argument("--all-term", action="append", default=[])
    parser.add_argument("--any-term", action="append", default=[])
    parser.add_argument("--exact-title", action="append", default=[])
    parser.add_argument("--doi", action="append", default=[])
    parser.add_argument("--author", action="append", default=[])
    parser.add_argument("--years", default="")
    parser.add_argument("--venue", action="append", default=[])
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--llm-model", default="")
    parser.add_argument("--rerank-limit", type=int, default=30)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument(
        "--query-workers",
        type=int,
        default=4,
        help="Concurrent remote embedding requests; local models still use one batch.",
    )
    parser.add_argument(
        "--abstract-chars",
        type=int,
        default=0,
        help="Use 0 for the low-token title-first collection stage.",
    )
    parser.add_argument("--result-view", choices=("titles", "standard"), default="titles")
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


def main(argv=None):
    args = build_parser().parse_args(argv)
    has_structured_query = bool(
        args.keyword_expression
        or args.all_term
        or args.any_term
        or args.exact_title
        or args.doi
        or args.author
    )
    if not (
        args.lite_query
        or args.keyword_query
        or args.filtered_lite_query
        or args.pro_query
        or has_structured_query
    ):
        write_json({"schema": "chipseeker-agent-collect/v2", "error": "At least one query is required."}, args.output)
        return 1

    try:
        config = load_app_config((CONFIG_FILE, LEGACY_CONFIG_FILE, EXAMPLE_CONFIG_FILE))
        years = parse_year_range(args.years)
        venues = parse_venues(args.venue)
        fields = parse_keyword_fields(args.fields)
        embedding_model = args.embedding_model or config["embedding_model"]
        responses = []
        with contextlib.redirect_stdout(sys.stderr):
            needs_papers = bool(
                args.keyword_query
                or args.filtered_lite_query
                or has_structured_query
                or args.lite_query
            )
            papers = None
            keyword_index = None
            searcher = None
            if needs_papers:
                with open(DB_FILE, "r", encoding="utf-8") as handle:
                    papers = json.load(handle)
            if args.keyword_query or args.filtered_lite_query or has_structured_query:
                keyword_index = KeywordSearchIndex(papers, analyze_venue, extract_year)
            if args.lite_query or args.filtered_lite_query:
                searcher = PaperSearcher(
                    DB_FILE,
                    model_name=embedding_model,
                    api_key=config.get("emb_api_key", ""),
                    papers_override=papers,
                    scope_key="all",
                )

            if args.lite_query:
                responses.extend(
                    run_lite_searches(
                        args.lite_query,
                        db_file=DB_FILE,
                        embedding_model=embedding_model,
                        embedding_api_key=config.get("emb_api_key", ""),
                        top_k=args.lite_top_k,
                        selected_years=years,
                        venues=venues,
                        abstract_chars=args.abstract_chars,
                        result_view=args.result_view,
                        searcher=searcher,
                        query_workers=args.query_workers,
                    )
                )
            keyword_queries = list(args.keyword_query)
            if has_structured_query and not keyword_queries and not args.filtered_lite_query:
                keyword_queries.append("")
            for query in keyword_queries:
                responses.append(
                    run_keyword_search(
                        ",".join(
                            value
                            for value in (query.strip(), args.keyword_expression.strip())
                            if value
                        ),
                        db_file=DB_FILE,
                        top_k=args.keyword_top_k,
                        selected_years=years,
                        venues=venues,
                        fields=fields,
                        abstract_chars=args.abstract_chars,
                        result_view=args.result_view,
                        keyword_index=keyword_index,
                        all_terms=args.all_term,
                        any_terms=args.any_term,
                        exact_titles=args.exact_title,
                        dois=args.doi,
                        authors=args.author,
                    )
                )
            if args.filtered_lite_query:
                responses.extend(
                    run_filtered_lite_searches(
                        args.filtered_lite_query,
                        db_file=DB_FILE,
                        embedding_model=embedding_model,
                        embedding_api_key=config.get("emb_api_key", ""),
                        top_k=args.lite_top_k,
                        selected_years=years,
                        venues=venues,
                        fields=fields,
                        abstract_chars=args.abstract_chars,
                        result_view=args.result_view,
                        searcher=searcher,
                        keyword_index=keyword_index,
                        expression=args.keyword_expression,
                        all_terms=args.all_term,
                        any_terms=args.any_term,
                        exact_titles=args.exact_title,
                        dois=args.doi,
                        authors=args.author,
                        query_workers=args.query_workers,
                    )
                )
            for query in args.pro_query:
                responses.append(
                    run_pro_search(
                        query,
                        db_file=DB_FILE,
                        embedding_model=embedding_model,
                        embedding_api_key=config.get("emb_api_key", ""),
                        llm_api_key=config.get("llm_api_key", ""),
                        llm_base_url=config.get("llm_base_url", ""),
                        llm_model=args.llm_model or config.get("llm_model", ""),
                        top_k=args.pro_top_k,
                        selected_years=years,
                        venues=venues,
                        abstract_chars=args.abstract_chars,
                        result_view=args.result_view,
                        rerank_limit=args.rerank_limit,
                        timeout_seconds=args.timeout_seconds,
                    )
                )
        response = merge_search_responses(responses)
    except Exception as exc:
        write_json({"schema": "chipseeker-agent-collect/v2", "error": str(exc)}, args.output)
        return 1

    write_json(response, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
