#!/usr/bin/env python3
"""Return ChipSeeker Lite or Pro results as a JSON-only stdout protocol."""

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

from chipseeker.agent_search import (
    parse_keyword_fields,
    parse_venues,
    parse_year_range,
    run_filtered_lite_search,
    run_keyword_search,
    run_lite_search,
    run_pro_search,
)
from chipseeker.config_store import load_app_config
from chipseeker.paths import CONFIG_FILE, DB_FILE, EXAMPLE_CONFIG_FILE, LEGACY_CONFIG_FILE


def build_parser():
    parser = argparse.ArgumentParser(description="Run ChipSeeker for a coding agent and print JSON to stdout.")
    parser.add_argument("--query", default="", help="Natural-language query, or a legacy expression in keyword mode.")
    parser.add_argument("--mode", choices=("lite", "pro", "keyword", "filtered-lite"), default="lite")
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--must-have", default="", help="Optional exact filter. Use / for OR and commas for AND.")
    parser.add_argument(
        "--keyword-expression",
        default="",
        help="Legacy AND/OR expression used as the hard prefilter in filtered-lite mode.",
    )
    parser.add_argument("--all-term", action="append", default=[], help="Required literal term. Repeat for AND.")
    parser.add_argument("--any-term", action="append", default=[], help="Alternative literal term. Repeat for OR.")
    parser.add_argument("--exact-title", action="append", default=[], help="Exact normalized title selector.")
    parser.add_argument("--doi", action="append", default=[], help="Exact DOI selector; DOI slashes remain literal.")
    parser.add_argument("--author", action="append", default=[], help="Author selector. Repeat for alternatives.")
    parser.add_argument(
        "--fields",
        default="",
        help="Keyword mode fields, comma-separated: title,abstract,authors,venue,year,keywords,ieee_terms,doi.",
    )
    parser.add_argument("--years", default="", help="Optional YYYY or YYYY:YYYY filter.")
    parser.add_argument("--venue", action="append", default=[], help="Optional unified venue. Repeat or use commas.")
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--llm-model", default="")
    parser.add_argument("--pro-fallback-model", action="append", default=[])
    parser.add_argument("--rerank-limit", type=int, default=30)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--abstract-chars", type=int, default=1600)
    parser.add_argument("--result-view", choices=("titles", "standard"), default="standard")
    parser.add_argument("--output", default="", help="Optional UTF-8 JSON file written atomically in addition to stdout.")
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
    try:
        config = load_app_config((CONFIG_FILE, LEGACY_CONFIG_FILE, EXAMPLE_CONFIG_FILE))
        years = parse_year_range(args.years)
        venues = parse_venues(args.venue)
        embedding_model = args.embedding_model or config["embedding_model"]

        # Search runtime progress belongs on stderr; stdout remains parseable JSON.
        with contextlib.redirect_stdout(sys.stderr):
            if args.mode == "keyword":
                keyword_query = ",".join(
                    value
                    for value in (
                        args.query.strip(),
                        args.keyword_expression.strip(),
                        args.must_have.strip(),
                    )
                    if value
                )
                response = run_keyword_search(
                    keyword_query,
                    db_file=DB_FILE,
                    top_k=args.top_k,
                    selected_years=years,
                    venues=venues,
                    fields=parse_keyword_fields(args.fields),
                    abstract_chars=args.abstract_chars,
                    result_view=args.result_view,
                    all_terms=args.all_term,
                    any_terms=args.any_term,
                    exact_titles=args.exact_title,
                    dois=args.doi,
                    authors=args.author,
                )
            elif args.mode == "filtered-lite":
                response = run_filtered_lite_search(
                    args.query,
                    db_file=DB_FILE,
                    embedding_model=embedding_model,
                    embedding_api_key=config.get("emb_api_key", ""),
                    top_k=args.top_k,
                    selected_years=years,
                    venues=venues,
                    fields=parse_keyword_fields(args.fields),
                    abstract_chars=args.abstract_chars,
                    result_view=args.result_view,
                    expression=args.keyword_expression or args.must_have,
                    all_terms=args.all_term,
                    any_terms=args.any_term,
                    exact_titles=args.exact_title,
                    dois=args.doi,
                    authors=args.author,
                )
            elif args.mode == "lite":
                response = run_lite_search(
                    args.query,
                    db_file=DB_FILE,
                    embedding_model=embedding_model,
                    embedding_api_key=config.get("emb_api_key", ""),
                    top_k=args.top_k,
                    selected_years=years,
                    venues=venues,
                    must_have=args.must_have,
                    abstract_chars=args.abstract_chars,
                    result_view=args.result_view,
                )
            else:
                response = run_pro_search(
                    args.query,
                    db_file=DB_FILE,
                    embedding_model=embedding_model,
                    embedding_api_key=config.get("emb_api_key", ""),
                    llm_api_key=config.get("llm_api_key", ""),
                    llm_base_url=config.get("llm_base_url", ""),
                    llm_model=args.llm_model or config.get("llm_model", ""),
                    fallback_models=args.pro_fallback_model or ["deepseek-v4-flash"],
                    top_k=args.top_k,
                    selected_years=years,
                    venues=venues,
                    must_have=args.must_have,
                    abstract_chars=args.abstract_chars,
                    result_view=args.result_view,
                    rerank_limit=args.rerank_limit,
                    timeout_seconds=args.timeout_seconds,
                )
    except Exception as exc:
        payload = {"schema": "chipseeker-agent-search/v1", "error": str(exc)}
        if getattr(exc, "attempts", None):
            payload["pro_attempts"] = list(exc.attempts)
        write_json(payload, args.output)
        return 1

    write_json(response, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
