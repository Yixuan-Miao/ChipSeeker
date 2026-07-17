#!/usr/bin/env python3
"""Audit Ultra Search candidates, evidence coverage, corpus freshness, and regressions."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chipseeker.agent_records import deduplicate_papers, load_paper_files
from chipseeker.paths import DB_FILE
from chipseeker.ultra_audit import ULTRA_AUDIT_SCHEMA, audit_candidates


def build_parser():
    parser = argparse.ArgumentParser(description="Audit ChipSeeker Ultra Search candidates.")
    parser.add_argument("--input", action="append", required=True, help="Current candidate/result JSON.")
    parser.add_argument("--prior", action="append", default=[], help="Prior result JSON; repeat as needed.")
    parser.add_argument("--target-band", default="", help="Positive-width overlap target, e.g. 4:8.")
    parser.add_argument("--skip-corpus-coverage", action="store_true")
    parser.add_argument("--output", default="")
    return parser


def write_json(payload, output_path=""):
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
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
        candidates, sources = load_paper_files(args.input)
        candidates = deduplicate_papers(candidates)
        prior = None
        prior_sources = []
        if args.prior:
            prior, prior_sources = load_paper_files(args.prior)
            prior = deduplicate_papers(prior)
        corpus = None
        if not args.skip_corpus_coverage:
            with open(DB_FILE, "r", encoding="utf-8") as handle:
                corpus = json.load(handle)
        response = audit_candidates(
            candidates,
            target_band=args.target_band or None,
            prior=prior,
            corpus=corpus,
        )
        response["input_sources"] = sources
        response["prior_sources"] = prior_sources
    except Exception as exc:
        write_json({"schema": ULTRA_AUDIT_SCHEMA, "error": str(exc)}, args.output)
        return 1
    write_json(response, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
