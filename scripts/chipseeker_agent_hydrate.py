#!/usr/bin/env python3
"""Hydrate candidate JSON files with local-corpus abstracts and metadata."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chipseeker.agent_hydrate import HYDRATE_SCHEMA, hydrate_candidates
from chipseeker.agent_records import deduplicate_papers, load_paper_files
from chipseeker.paths import DB_FILE


def build_parser():
    parser = argparse.ArgumentParser(description="Hydrate ChipSeeker title-first candidates.")
    parser.add_argument("--input", action="append", required=True, help="Candidate JSON; repeat as needed.")
    parser.add_argument("--abstract-chars", type=int, default=10000)
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
    try:
        candidates, sources = load_paper_files(args.input)
        candidates = deduplicate_papers(candidates)
        with open(DB_FILE, "r", encoding="utf-8") as handle:
            corpus = json.load(handle)
        response = hydrate_candidates(candidates, corpus, abstract_chars=max(1, args.abstract_chars))
        response["input_sources"] = sources
    except Exception as exc:
        write_json({"schema": HYDRATE_SCHEMA, "error": str(exc)}, args.output)
        return 1
    write_json(response, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
