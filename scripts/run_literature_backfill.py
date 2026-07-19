import argparse
import json
import os
import sys
import traceback
from datetime import datetime


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from chipseeker.literature_update import run_literature_update
from chipseeker.paths import (
    CACHE_DIR,
    DB_FILE,
    LITERATURE_UPDATE_RUN_DIR,
    LITERATURE_UPDATE_STAGING_DIR,
    LOCAL_DATA_STATE_FILE,
    PAPER_UPDATE_HISTORY_FILE,
    SOURCE_CSV_DIR,
    SOURCE_MANIFEST_FILE,
    SOURCE_REGISTRY_FILE,
)
from chipseeker.update_manager import load_source_registry


def append_log(path, message, level="info"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {level.upper()} {message}\n")


def main():
    parser = argparse.ArgumentParser(description="Run a resumable historical literature backfill.")
    parser.add_argument("--provider", required=True, choices=("nature", "science", "arxiv"))
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--source-id", action="append", default=[], help="Optional source ID to run; repeat as needed")
    args = parser.parse_args()

    registry = load_source_registry(SOURCE_REGISTRY_FILE)
    source_ids = [
        source["id"]
        for source in registry.get("sources", [])
        if source.get("enabled")
        and int(source.get("generation", 1) or 1) >= 3
        and source.get("provider") == args.provider
        and (not args.source_id or source.get("id") in args.source_id)
    ]
    if not source_ids:
        raise SystemExit("No enabled sources matched the requested provider/source IDs.")
    append_log(args.log_file, f"Starting {args.provider} backfill from {args.start_date}: {source_ids}")

    def progress(value, message):
        append_log(args.log_file, f"progress={value:.3f} {message}")

    def history(message, level="info"):
        append_log(args.log_file, message, level=level)

    try:
        result = run_literature_update(
            f"five-year-{args.provider}-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            {
                "source_ids": source_ids,
                "start_date_override": args.start_date,
                "registry_path": SOURCE_REGISTRY_FILE,
                "db_file": DB_FILE,
                "cache_dir": CACHE_DIR,
                "source_root": SOURCE_CSV_DIR,
                "manifest_path": SOURCE_MANIFEST_FILE,
                "local_state_path": LOCAL_DATA_STATE_FILE,
                "run_dir": LITERATURE_UPDATE_RUN_DIR,
                "staging_root": LITERATURE_UPDATE_STAGING_DIR,
                "history_path": PAPER_UPDATE_HISTORY_FILE,
            },
            progress,
            history,
            lambda: False,
        )
        append_log(args.log_file, "RESULT " + json.dumps(result, ensure_ascii=False))
    except Exception:
        append_log(args.log_file, traceback.format_exc(), level="error")
        raise


if __name__ == "__main__":
    main()
