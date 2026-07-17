#!/usr/bin/env python3
"""Run several ChipSeeker retrieval passes and emit one deduplicated JSON set."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chipseeker.agent_collect import merge_search_responses
from chipseeker.agent_query_spec import load_query_spec, normalize_query_spec
from chipseeker.agent_records import index_screening_decisions, load_paper_files
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
    parser.add_argument("--query-spec", action="append", default=[], help="Structured per-query JSON plan.")
    parser.add_argument("--screening-decisions", action="append", default=[], help="Optional screening JSON for retained-yield saturation.")
    parser.add_argument("--checkpoint-dir", default="", help="Write one atomic JSON checkpoint per query.")
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
    parser.add_argument("--pro-fallback-model", action="append", default=[])
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


def _legacy_entries(args, config):
    years = parse_year_range(args.years)
    venues = parse_venues(args.venue)
    fields = parse_keyword_fields(args.fields)
    embedding_model = args.embedding_model or config["embedding_model"]
    llm_model = args.llm_model or config.get("llm_model", "")
    fallbacks = args.pro_fallback_model or ["deepseek-v4-flash"]
    common = {
        "years": years,
        "venues": venues,
        "fields": fields,
        "embedding_model": embedding_model,
        "llm_model": llm_model,
        "fallback_models": fallbacks,
        "rerank_limit": args.rerank_limit,
        "timeout_seconds": args.timeout_seconds,
        "abstract_chars": args.abstract_chars,
        "result_view": args.result_view,
        "must_have": "",
        "expression": args.keyword_expression,
        "all_terms": list(args.all_term),
        "any_terms": list(args.any_term),
        "exact_titles": list(args.exact_title),
        "dois": list(args.doi),
        "authors": list(args.author),
        "query_family": "",
        "query_role": "general",
        "coverage": {},
    }
    entries = []

    def append(mode, query, top_k, position):
        entries.append(
            {
                **common,
                "id": f"legacy-{mode.replace('_', '-')}-{position:03d}",
                "mode": mode,
                "query": query,
                "top_k": top_k,
            }
        )

    for position, query in enumerate(args.lite_query, start=1):
        append("lite", query, args.lite_top_k, position)
    keyword_queries = list(args.keyword_query)
    has_structured = bool(
        args.keyword_expression or args.all_term or args.any_term or args.exact_title or args.doi or args.author
    )
    if has_structured and not keyword_queries and not args.filtered_lite_query:
        keyword_queries.append("")
    for position, query in enumerate(keyword_queries, start=1):
        append("keyword", query, args.keyword_top_k, position)
    for position, query in enumerate(args.filtered_lite_query, start=1):
        append("filtered_lite", query, args.lite_top_k, position)
    for position, query in enumerate(args.pro_query, start=1):
        append("pro", query, args.pro_top_k, position)
    return entries


def _annotate(response, entry, duration_seconds):
    response = dict(response)
    response["query_id"] = entry["id"]
    response["query_role"] = entry.get("query_role", "general")
    response["coverage"] = entry.get("coverage", {})
    if entry.get("query_family"):
        response["query_family"] = entry["query_family"]
    response["status"] = "completed"
    response["duration_seconds"] = round(float(duration_seconds), 3)
    return response


def _failed_response(entry, exc, duration_seconds):
    response = {
        "schema": "chipseeker-agent-search/v1",
        "mode": entry["mode"],
        "query": entry.get("query", ""),
        "query_id": entry["id"],
        "query_role": entry.get("query_role", "general"),
        "coverage": entry.get("coverage", {}),
        "model": entry.get("llm_model", "") if entry["mode"] == "pro" else entry.get("embedding_model", ""),
        "result_view": entry.get("result_view", "titles"),
        "status": "failed",
        "error": str(exc),
        "duration_seconds": round(float(duration_seconds), 3),
        "candidate_count": 0,
        "result_count": 0,
        "results": [],
    }
    if entry.get("query_family"):
        response["query_family"] = entry["query_family"]
    if getattr(exc, "attempts", None):
        response["pro_attempts"] = list(exc.attempts)
    return response


def _write_checkpoint(response, checkpoint_dir):
    if not checkpoint_dir:
        return
    directory = Path(checkpoint_dir)
    directory.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", str(response.get("query_id", "query")))[:100]
    path = directory / f"{safe_id}.json"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(response, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _run_entries(entries, args, config):
    response_by_id = {}

    def store(entry, response):
        response_by_id[entry["id"]] = response
        _write_checkpoint(response, args.checkpoint_dir)

    needs_papers = any(entry["mode"] in {"lite", "keyword", "filtered_lite"} for entry in entries)
    papers = None
    keyword_index = None
    searchers = {}
    if needs_papers:
        with open(DB_FILE, "r", encoding="utf-8") as handle:
            papers = json.load(handle)
    if any(entry["mode"] in {"keyword", "filtered_lite"} for entry in entries):
        keyword_index = KeywordSearchIndex(papers, analyze_venue, extract_year)

    def get_searcher(model):
        model = model or config["embedding_model"]
        if model not in searchers:
            searchers[model] = PaperSearcher(
                DB_FILE,
                model_name=model,
                api_key=config.get("emb_api_key", ""),
                papers_override=papers,
                scope_key="all",
            )
        return searchers[model]

    lite_groups = defaultdict(list)
    filtered_groups = defaultdict(list)
    for entry in entries:
        if entry["mode"] == "lite":
            key = (
                entry["embedding_model"], entry["top_k"], tuple(entry["years"]), tuple(entry["venues"]),
                entry["must_have"], entry["abstract_chars"], entry["result_view"],
            )
            lite_groups[key].append(entry)
        elif entry["mode"] == "filtered_lite":
            key = (
                entry["embedding_model"], entry["top_k"], tuple(entry["years"]), tuple(entry["venues"]),
                tuple(entry["fields"]), entry["expression"], tuple(entry["all_terms"]), tuple(entry["any_terms"]),
                tuple(entry["exact_titles"]), tuple(entry["dois"]), tuple(entry["authors"]),
                entry["abstract_chars"], entry["result_view"],
            )
            filtered_groups[key].append(entry)

    for group in lite_groups.values():
        started = time.monotonic()
        try:
            first = group[0]
            responses = run_lite_searches(
                [entry["query"] for entry in group],
                db_file=DB_FILE,
                embedding_model=first["embedding_model"] or config["embedding_model"],
                embedding_api_key=config.get("emb_api_key", ""),
                top_k=first["top_k"],
                selected_years=first["years"],
                venues=first["venues"],
                must_have=first["must_have"],
                abstract_chars=first["abstract_chars"],
                result_view=first["result_view"],
                searcher=get_searcher(first["embedding_model"]),
                query_workers=args.query_workers,
            )
            elapsed = (time.monotonic() - started) / max(1, len(group))
            for entry, response in zip(group, responses):
                store(entry, _annotate(response, entry, elapsed))
        except Exception as exc:
            for entry in group:
                retry_started = time.monotonic()
                try:
                    response = run_lite_searches(
                        [entry["query"]],
                        db_file=DB_FILE,
                        embedding_model=entry["embedding_model"] or config["embedding_model"],
                        embedding_api_key=config.get("emb_api_key", ""),
                        top_k=entry["top_k"],
                        selected_years=entry["years"],
                        venues=entry["venues"],
                        must_have=entry["must_have"],
                        abstract_chars=entry["abstract_chars"],
                        result_view=entry["result_view"],
                        searcher=get_searcher(entry["embedding_model"]),
                        query_workers=1,
                    )[0]
                    response["batch_retry"] = {"status": "completed", "batch_error": str(exc)}
                    store(entry, _annotate(response, entry, time.monotonic() - retry_started))
                except Exception as retry_exc:
                    failure = _failed_response(entry, retry_exc, time.monotonic() - retry_started)
                    failure["batch_error"] = str(exc)
                    store(entry, failure)

    for entry in (item for item in entries if item["mode"] == "keyword"):
        started = time.monotonic()
        try:
            expression = ",".join(value for value in (entry["query"], entry["expression"]) if value)
            response = run_keyword_search(
                expression,
                db_file=DB_FILE,
                top_k=entry["top_k"],
                selected_years=entry["years"],
                venues=entry["venues"],
                fields=entry["fields"],
                abstract_chars=entry["abstract_chars"],
                result_view=entry["result_view"],
                keyword_index=keyword_index,
                all_terms=entry["all_terms"],
                any_terms=entry["any_terms"],
                exact_titles=entry["exact_titles"],
                dois=entry["dois"],
                authors=entry["authors"],
            )
            store(entry, _annotate(response, entry, time.monotonic() - started))
        except Exception as exc:
            store(entry, _failed_response(entry, exc, time.monotonic() - started))

    for group in filtered_groups.values():
        started = time.monotonic()
        try:
            first = group[0]
            responses = run_filtered_lite_searches(
                [entry["query"] for entry in group],
                db_file=DB_FILE,
                embedding_model=first["embedding_model"] or config["embedding_model"],
                embedding_api_key=config.get("emb_api_key", ""),
                top_k=first["top_k"],
                selected_years=first["years"],
                venues=first["venues"],
                fields=first["fields"],
                abstract_chars=first["abstract_chars"],
                result_view=first["result_view"],
                searcher=get_searcher(first["embedding_model"]),
                keyword_index=keyword_index,
                expression=first["expression"],
                all_terms=first["all_terms"],
                any_terms=first["any_terms"],
                exact_titles=first["exact_titles"],
                dois=first["dois"],
                authors=first["authors"],
                query_workers=args.query_workers,
            )
            elapsed = (time.monotonic() - started) / max(1, len(group))
            for entry, response in zip(group, responses):
                store(entry, _annotate(response, entry, elapsed))
        except Exception as exc:
            for entry in group:
                retry_started = time.monotonic()
                try:
                    response = run_filtered_lite_searches(
                        [entry["query"]],
                        db_file=DB_FILE,
                        embedding_model=entry["embedding_model"] or config["embedding_model"],
                        embedding_api_key=config.get("emb_api_key", ""),
                        top_k=entry["top_k"],
                        selected_years=entry["years"],
                        venues=entry["venues"],
                        fields=entry["fields"],
                        abstract_chars=entry["abstract_chars"],
                        result_view=entry["result_view"],
                        searcher=get_searcher(entry["embedding_model"]),
                        keyword_index=keyword_index,
                        expression=entry["expression"],
                        all_terms=entry["all_terms"],
                        any_terms=entry["any_terms"],
                        exact_titles=entry["exact_titles"],
                        dois=entry["dois"],
                        authors=entry["authors"],
                        query_workers=1,
                    )[0]
                    response["batch_retry"] = {"status": "completed", "batch_error": str(exc)}
                    store(entry, _annotate(response, entry, time.monotonic() - retry_started))
                except Exception as retry_exc:
                    failure = _failed_response(entry, retry_exc, time.monotonic() - retry_started)
                    failure["batch_error"] = str(exc)
                    store(entry, failure)

    for entry in (item for item in entries if item["mode"] == "pro"):
        started = time.monotonic()
        try:
            response = run_pro_search(
                entry["query"],
                db_file=DB_FILE,
                embedding_model=entry["embedding_model"] or config["embedding_model"],
                embedding_api_key=config.get("emb_api_key", ""),
                llm_api_key=config.get("llm_api_key", ""),
                llm_base_url=config.get("llm_base_url", ""),
                llm_model=entry["llm_model"] or config.get("llm_model", ""),
                fallback_models=entry["fallback_models"],
                top_k=entry["top_k"],
                selected_years=entry["years"],
                venues=entry["venues"],
                must_have=entry["must_have"],
                abstract_chars=entry["abstract_chars"],
                result_view=entry["result_view"],
                rerank_limit=entry["rerank_limit"],
                timeout_seconds=entry["timeout_seconds"],
            )
            store(entry, _annotate(response, entry, time.monotonic() - started))
        except Exception as exc:
            store(entry, _failed_response(entry, exc, time.monotonic() - started))

    responses = []
    for entry in entries:
        response = response_by_id[entry["id"]]
        responses.append(response)
    return responses


def main(argv=None):
    args = build_parser().parse_args(argv)
    started_at = datetime.now(timezone.utc)
    started_clock = time.monotonic()
    try:
        config = load_app_config((CONFIG_FILE, LEGACY_CONFIG_FILE, EXAMPLE_CONFIG_FILE))
        entries = _legacy_entries(args, config)
        query_spec_sources = []
        declared_scope = defaultdict(list)
        runtime_defaults = {
            "years": args.years,
            "venues": args.venue,
            "fields": args.fields,
            "embedding_model": args.embedding_model or config["embedding_model"],
            "llm_model": args.llm_model or config.get("llm_model", ""),
            "pro_fallback_models": args.pro_fallback_model or ["deepseek-v4-flash"],
            "lite_top_k": args.lite_top_k,
            "keyword_top_k": args.keyword_top_k,
            "pro_top_k": args.pro_top_k,
            "rerank_limit": args.rerank_limit,
            "timeout_seconds": args.timeout_seconds,
            "abstract_chars": args.abstract_chars,
            "result_view": args.result_view,
        }
        for path in args.query_spec:
            payload = load_query_spec(path)
            normalized = normalize_query_spec(payload, runtime_defaults=runtime_defaults)
            entries.extend(normalized)
            scope = payload.get("scope", {}) or {}
            if not isinstance(scope, dict):
                raise ValueError("Query spec scope must be an object.")
            for dimension, raw_values in scope.items():
                values = raw_values if isinstance(raw_values, list) else [raw_values]
                for value in values:
                    value = str(value or "").strip()
                    if value and value not in declared_scope[str(dimension)]:
                        declared_scope[str(dimension)].append(value)
            query_spec_sources.append(
                {"path": str(Path(path).resolve()), "query_count": len(normalized), "scope": scope}
            )
        if not entries:
            raise ValueError("At least one legacy query or --query-spec entry is required.")
        ids = [entry["id"] for entry in entries]
        if len(ids) != len(set(ids)):
            raise ValueError("Query ids must be unique across legacy arguments and query specs.")

        with contextlib.redirect_stdout(sys.stderr):
            responses = _run_entries(entries, args, config)
        decision_index = {}
        decision_sources = []
        if args.screening_decisions:
            decisions, decision_sources = load_paper_files(args.screening_decisions)
            decision_index = index_screening_decisions(decisions)
        response = merge_search_responses(responses, screening_decisions=decision_index)
        uncovered_scope = {}
        for dimension, values in declared_scope.items():
            covered = set(response.get("query_coverage", {}).get(dimension, {}))
            missing = [value for value in values if value not in covered]
            if missing:
                uncovered_scope[dimension] = missing
        finished_at = datetime.now(timezone.utc)
        response["run"] = {
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": round(time.monotonic() - started_clock, 3),
            "query_spec_sources": query_spec_sources,
            "screening_decision_sources": decision_sources,
            "checkpoint_dir": str(Path(args.checkpoint_dir).resolve()) if args.checkpoint_dir else "",
            "completed_query_count": sum(item.get("status") == "completed" for item in responses),
            "failed_query_count": sum(item.get("status") != "completed" for item in responses),
            "declared_scope": dict(declared_scope),
            "uncovered_scope": uncovered_scope,
        }
    except Exception as exc:
        write_json({"schema": "chipseeker-agent-collect/v3", "error": str(exc)}, args.output)
        return 1

    write_json(response, args.output)
    return 0 if response["run"]["completed_query_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
