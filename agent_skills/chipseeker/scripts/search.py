#!/usr/bin/env python3
"""Run the configured local ChipSeeker agent search from any working directory."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(r"F:\Papers_Embedding\SearchPaperByEmbedding-main")
PROJECT_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
AGENT_CLI = PROJECT_ROOT / "scripts" / "chipseeker_agent_search.py"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search the configured local ChipSeeker corpus.")
    parser.add_argument("query", nargs="?", default="", help="Natural-language technical query.")
    parser.add_argument("--mode", choices=("lite", "pro", "keyword", "filtered-lite"), default="lite")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--must-have", default="")
    parser.add_argument("--keyword-expression", default="")
    parser.add_argument("--all-term", action="append", default=[])
    parser.add_argument("--any-term", action="append", default=[])
    parser.add_argument("--exact-title", action="append", default=[])
    parser.add_argument("--doi", action="append", default=[])
    parser.add_argument("--author", action="append", default=[])
    parser.add_argument("--fields", default="")
    parser.add_argument("--years", default="")
    parser.add_argument("--venue", action="append", default=[])
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--llm-model", default="")
    parser.add_argument("--pro-fallback-model", action="append", default=[])
    parser.add_argument("--rerank-limit", type=int, default=30)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--abstract-chars", type=int, default=1600)
    parser.add_argument("--result-view", choices=("titles", "standard"), default="standard")
    parser.add_argument("--output", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    missing = [str(path) for path in (PROJECT_PYTHON, AGENT_CLI) if not path.is_file()]
    if missing:
        print("ChipSeeker is not ready; missing: " + ", ".join(missing), file=sys.stderr)
        return 2

    command = [
        str(PROJECT_PYTHON), str(AGENT_CLI), "--query", args.query,
        "--mode", args.mode, "--top-k", str(args.top_k),
        "--rerank-limit", str(args.rerank_limit),
        "--timeout-seconds", str(args.timeout_seconds),
        "--abstract-chars", str(args.abstract_chars),
        "--result-view", args.result_view,
    ]
    for option, value in (
        ("--must-have", args.must_have),
        ("--keyword-expression", args.keyword_expression),
        ("--fields", args.fields),
        ("--years", args.years),
        ("--embedding-model", args.embedding_model),
        ("--llm-model", args.llm_model),
        ("--output", args.output),
    ):
        if value:
            command.extend((option, str(value)))
    for option, values in (
        ("--venue", args.venue),
        ("--all-term", args.all_term),
        ("--any-term", args.any_term),
        ("--exact-title", args.exact_title),
        ("--doi", args.doi),
        ("--author", args.author),
        ("--pro-fallback-model", args.pro_fallback_model),
    ):
        for value in values:
            command.extend((option, value))
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
