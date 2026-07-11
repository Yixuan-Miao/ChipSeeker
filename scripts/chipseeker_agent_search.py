#!/usr/bin/env python3
"""Return ChipSeeker Lite or Pro results as a JSON-only stdout protocol."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chipseeker.agent_search import parse_venues, parse_year_range, run_lite_search, run_pro_search
from chipseeker.config_store import load_app_config
from chipseeker.paths import CONFIG_FILE, DB_FILE, EXAMPLE_CONFIG_FILE, LEGACY_CONFIG_FILE


def build_parser():
    parser = argparse.ArgumentParser(description="Run ChipSeeker for a coding agent and print JSON to stdout.")
    parser.add_argument("--query", required=True, help="Natural-language technical query.")
    parser.add_argument("--mode", choices=("lite", "pro"), default="lite")
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--must-have", default="", help="Optional exact filter. Use / for OR and commas for AND.")
    parser.add_argument("--years", default="", help="Optional YYYY or YYYY:YYYY filter.")
    parser.add_argument("--venue", action="append", default=[], help="Optional unified venue. Repeat or use commas.")
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--llm-model", default="")
    parser.add_argument("--rerank-limit", type=int, default=30)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--abstract-chars", type=int, default=1600)
    return parser


def write_json(payload):
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
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
            if args.mode == "lite":
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
                    top_k=args.top_k,
                    selected_years=years,
                    venues=venues,
                    must_have=args.must_have,
                    abstract_chars=args.abstract_chars,
                    rerank_limit=args.rerank_limit,
                    timeout_seconds=args.timeout_seconds,
                )
    except Exception as exc:
        write_json({"schema": "chipseeker-agent-search/v1", "error": str(exc)})
        return 1

    write_json(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
