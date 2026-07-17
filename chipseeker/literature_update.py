import csv
import hashlib
import os
import shutil
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from chipseeker.data_sync import build_source_snapshot, import_csv_files_incremental, list_source_csv_files
from chipseeker.paths import (
    ARXIV_UPDATE_DIR,
    CACHE_DIR,
    CURRENT_LOCAL_DATA_VERSION,
    DB_FILE,
    LITERATURE_UPDATE_RUN_DIR,
    LITERATURE_UPDATE_STAGING_DIR,
    LOCAL_DATA_STATE_FILE,
    NATURE_UPDATE_DIR,
    SCIENCE_UPDATE_DIR,
    SOURCE_CSV_DIR,
    SOURCE_MANIFEST_FILE,
    SOURCE_REGISTRY_FILE,
)
from chipseeker.update_manager import commit_incremental_source_results, default_incremental_start_date, find_source, load_source_registry
from chipseeker.update_history import record_update_event
from chipseeker.utils import load_json, save_json


OUTPUT_FIELDS = [
    "Document Title",
    "Abstract",
    "Authors",
    "Author Keywords",
    "Publication Year",
    "Publication Title",
    "DOI",
    "PDF Link",
    "Source URL",
]
PROVIDER_OUTPUT_DIRS = {
    "nature": NATURE_UPDATE_DIR,
    "arxiv": ARXIV_UPDATE_DIR,
    "science": SCIENCE_UPDATE_DIR,
}
_UPDATE_LOCK = threading.Lock()


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _run_state_path(run_id, run_dir=LITERATURE_UPDATE_RUN_DIR):
    return os.path.join(run_dir, f"{run_id}.json")


def _save_run_state(state, run_dir=LITERATURE_UPDATE_RUN_DIR):
    state["updated_at_utc"] = _utc_now()
    save_json(_run_state_path(state["run_id"], run_dir), state)


def _source_signature(source_ids):
    return hashlib.sha1("\n".join(sorted(source_ids)).encode("utf-8")).hexdigest()


def _find_resumable_state(source_ids, run_dir=LITERATURE_UPDATE_RUN_DIR):
    signature = _source_signature(source_ids)
    candidates = []
    for path in Path(run_dir).glob("*.json"):
        state = load_json(str(path), {})
        if (
            isinstance(state, dict)
            and state.get("source_signature") == signature
            and not state.get("commit_completed")
            and state.get("status") in {"queued", "running", "interrupted"}
        ):
            candidates.append((path.stat().st_mtime, state))
    return max(candidates, default=(None, None), key=lambda item: item[0])[1]


def create_or_resume_run(
    registry_path,
    source_ids,
    run_dir=LITERATURE_UPDATE_RUN_DIR,
    staging_root=LITERATURE_UPDATE_STAGING_DIR,
):
    os.makedirs(run_dir, exist_ok=True)
    os.makedirs(staging_root, exist_ok=True)
    source_ids = list(dict.fromkeys(source_ids))
    existing = _find_resumable_state(source_ids, run_dir=run_dir)
    if existing:
        for source_state in existing.get("sources", {}).values():
            if source_state.get("status") == "fetched" and not os.path.exists(source_state.get("output_file", "")):
                source_state["status"] = "pending"
        existing["status"] = "queued"
        _save_run_state(existing, run_dir=run_dir)
        return existing

    registry = load_source_registry(registry_path)
    run_id = f"literature-{datetime.now().strftime('%Y%m%d_%H%M%S')}-{uuid.uuid4().hex[:6]}"
    staging_dir = os.path.join(staging_root, run_id)
    sources = {}
    for source_id in source_ids:
        source = find_source(registry, source_id)
        if not source or not source.get("enabled") or not source.get("query"):
            continue
        sources[source_id] = {
            "source_id": source_id,
            "provider": source.get("provider"),
            "name": source.get("name", source_id),
            "start_date": default_incremental_start_date(source),
            "status": "pending",
            "rows": 0,
            "output_file": "",
            "report": {},
        }
    state = {
        "schema_version": 1,
        "run_id": run_id,
        "source_ids": list(sources),
        "source_signature": _source_signature(list(sources)),
        "checked_date": date.today().isoformat(),
        "status": "queued",
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "staging_dir": staging_dir,
        "sources": sources,
        "commit_completed": False,
        "committed_files": [],
        "import_result": None,
    }
    _save_run_state(state, run_dir=run_dir)
    return state


def _paper_key(row):
    doi = str(row.get("DOI", "")).strip().lower()
    if doi:
        return f"doi:{doi}"
    source_url = str(row.get("Source URL", "")).strip().lower()
    if source_url:
        return f"url:{source_url}"
    title = " ".join(str(row.get("Document Title", "")).lower().split())
    year = str(row.get("Publication Year", "")).strip()
    return f"title:{title}|{year}"


def _read_csv_rows(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv_rows(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = path + ".part"
    with open(temporary_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in OUTPUT_FIELDS} for row in rows)
    os.replace(temporary_path, path)


def _remove_staging_dir(staging_dir, staging_root):
    root = os.path.realpath(staging_root)
    target = os.path.realpath(staging_dir)
    if target == root or os.path.commonpath([root, target]) != root:
        raise RuntimeError(f"Refusing to remove staging path outside its root: {target}")
    shutil.rmtree(target, ignore_errors=True)


def _fetch_source(source, source_state, article_cache, progress_callback, cancel_callback):
    from Arxiv_Grabber import grab_arxiv
    from Nature_Grabber import grab_nature
    from Science_Grabber import grab_science

    provider = source.get("provider")
    common = {
        "query": source["query"],
        "output_file": source_state["output_file"],
        "start_date": source_state["start_date"],
        "return_report": True,
        "progress_callback": progress_callback,
        "cancel_callback": cancel_callback,
    }
    if provider == "nature":
        return grab_nature(
            **common,
            journal=source.get("journal", ""),
            year_from=2015,
            max_pages=int(source.get("max_pages", 0) or 0),
            sleep_seconds=float(source.get("sleep_seconds", 0.4)),
            article_cache=article_cache,
        )
    if provider == "arxiv":
        return grab_arxiv(
            **common,
            categories=source.get("categories", []),
            max_results=int(source.get("max_results", 0) or 0),
            page_size=int(source.get("page_size", 100) or 100),
            sleep_seconds=float(source.get("sleep_seconds", 3.0)),
            window_days=int(source.get("window_days", 30) or 30),
        )
    if provider == "science":
        return grab_science(
            **common,
            issns=source.get("issns", []),
            max_results=int(source.get("max_results", 200) or 200),
            sleep_seconds=float(source.get("sleep_seconds", 0.5)),
        )
    raise ValueError(f"Unsupported literature provider: {provider}")


def _commit_staged_sources(state, db_file, cache_dir, source_root, manifest_path, registry_path, local_state_path):
    provider_rows = {}
    successful_results = {}
    for source_id, source_state in state["sources"].items():
        if source_state.get("status") != "fetched":
            continue
        successful_results[source_id] = {"rows": source_state.get("rows", 0)}
        output_file = source_state.get("output_file", "")
        if not output_file or not os.path.exists(output_file):
            raise RuntimeError(f"Staged output disappeared before commit: {source_id}")
        provider_rows.setdefault(source_state["provider"], []).extend(_read_csv_rows(output_file))

    committed_files = []
    for provider, rows in provider_rows.items():
        deduped = {}
        for row in rows:
            key = _paper_key(row)
            if key and key not in deduped:
                deduped[key] = row
        if not deduped:
            continue
        output_dir = PROVIDER_OUTPUT_DIRS[provider]
        output_file = os.path.join(
            output_dir,
            "literature_v2_runs",
            f"{provider}_{state['checked_date']}_{state['run_id']}.csv",
        )
        _write_csv_rows(output_file, list(deduped.values()))
        committed_files.append(output_file)

    added = updated = removed = 0
    file_summaries = []
    if committed_files:
        added, updated, removed, file_summaries = import_csv_files_incremental(
            db_file,
            cache_dir,
            committed_files,
            source_root=source_root,
            manifest_path=manifest_path,
        )

    if successful_results:
        commit_incremental_source_results(
            registry_path,
            successful_results,
            state["checked_date"],
            run_id=state["run_id"],
        )

    source_files = list_source_csv_files(source_root=source_root, manifest_path=manifest_path)
    snapshot = build_source_snapshot(source_files, source_root=source_root)
    local_state = load_json(local_state_path, {})
    if not isinstance(local_state, dict):
        local_state = {}
    record_count = len(load_json(db_file, []))
    now = _utc_now()
    local_state["library_sync"] = {
        "db_file": os.path.abspath(db_file),
        "source_token": snapshot["token"],
        "source_files": snapshot["files"],
        "last_synced_at_utc": now,
        "db_record_count": record_count,
    }
    local_state["bibliographic_metadata_enrich"] = {
        "db_file": os.path.abspath(db_file),
        "source_token": snapshot["token"],
        "source_files": snapshot["files"],
        "schema_version": CURRENT_LOCAL_DATA_VERSION,
        "last_enriched_at_utc": now,
        "matched_rows": 0,
        "updated_count": 0,
    }
    save_json(local_state_path, local_state)
    return {
        "added": added,
        "updated": updated,
        "removed": removed,
        "files": committed_files,
        "file_summaries": file_summaries,
        "record_count": record_count,
    }


def run_literature_update(
    task_id,
    payload,
    update_progress,
    append_history,
    cancel_requested,
):
    with _UPDATE_LOCK:
        state = create_or_resume_run(
            payload.get("registry_path") or SOURCE_REGISTRY_FILE,
            payload["source_ids"],
            run_dir=payload.get("run_dir") or LITERATURE_UPDATE_RUN_DIR,
            staging_root=payload.get("staging_root") or LITERATURE_UPDATE_STAGING_DIR,
        )
        run_dir = payload.get("run_dir") or LITERATURE_UPDATE_RUN_DIR
        state["status"] = "running"
        state["task_id"] = task_id
        _save_run_state(state, run_dir=run_dir)
        registry = load_source_registry(payload.get("registry_path") or SOURCE_REGISTRY_FILE)
        source_ids = state["source_ids"]
        article_cache = {}

        try:
            for index, source_id in enumerate(source_ids):
                if cancel_requested():
                    raise RuntimeError("Task was canceled.")
                source_state = state["sources"][source_id]
                if source_state.get("status") == "fetched" and os.path.exists(source_state.get("output_file", "")):
                    append_history(f"Resuming with completed source: {source_state['name']}")
                    continue
                source = find_source(registry, source_id)
                if not source:
                    source_state["status"] = "failed"
                    source_state["error"] = "Source is no longer present in the registry."
                    _save_run_state(state, run_dir=run_dir)
                    continue

                provider = source.get("provider")
                source_dir = os.path.join(state["staging_dir"], provider, source_id)
                os.makedirs(source_dir, exist_ok=True)
                safe_start = source_state["start_date"].replace("-", "")
                source_state["output_file"] = os.path.join(
                    source_dir,
                    f"{source.get('export_prefix', source_id)}_{state['checked_date']}_from{safe_start}.csv",
                )
                source_state["status"] = "running"
                source_state["started_at_utc"] = _utc_now()
                _save_run_state(state, run_dir=run_dir)
                base_progress = index / max(1, len(source_ids))
                update_progress(base_progress * 0.9, f"Fetching {source_state['name']} from {source_state['start_date']}")

                def source_progress(details):
                    source_state["live"] = details
                    fraction = min(0.85, 0.05 + 0.03 * int(details.get("pages", 0) or 0))
                    overall = ((index + fraction) / max(1, len(source_ids))) * 0.9
                    update_progress(overall, f"{source_state['name']}: pages={details.get('pages', 0)}, rows={details.get('rows', 0)}")

                try:
                    report = _fetch_source(
                        source,
                        source_state,
                        article_cache,
                        source_progress,
                        cancel_requested,
                    )
                    source_state["report"] = {key: value for key, value in report.items() if key != "rows"}
                    source_state["rows"] = int(report.get("row_count", len(report.get("rows", []))) or 0)
                    source_state["finished_at_utc"] = _utc_now()
                    source_state.pop("live", None)
                    if report.get("completed"):
                        source_state["status"] = "fetched"
                        append_history(f"Fetched {source_state['name']}: {source_state['rows']} rows")
                    else:
                        source_state["status"] = "failed"
                        source_state["error"] = "Source was incomplete; checkpoint was not advanced."
                        append_history(f"Incomplete source retained for retry: {source_state['name']}", level="warning")
                except Exception as exc:
                    if cancel_requested():
                        raise
                    source_state["status"] = "failed"
                    source_state["error"] = str(exc)
                    source_state["finished_at_utc"] = _utc_now()
                    source_state.pop("live", None)
                    append_history(f"Source failed and will be retried: {source_state['name']} | {exc}", level="error")
                _save_run_state(state, run_dir=run_dir)

            update_progress(0.92, "Deduplicating staged results and committing the library once")
            import_result = _commit_staged_sources(
                state,
                payload.get("db_file") or DB_FILE,
                payload.get("cache_dir") or CACHE_DIR,
                payload.get("source_root") or SOURCE_CSV_DIR,
                payload.get("manifest_path") or SOURCE_MANIFEST_FILE,
                payload.get("registry_path") or SOURCE_REGISTRY_FILE,
                payload.get("local_state_path") or LOCAL_DATA_STATE_FILE,
            )
            state["import_result"] = import_result
            state["committed_files"] = import_result["files"]
            state["commit_completed"] = True
            failed = [source for source in state["sources"].values() if source.get("status") == "failed"]
            state["status"] = "partial" if failed else "completed"
            state["finished_at_utc"] = _utc_now()
            _save_run_state(state, run_dir=run_dir)
            history_path = payload.get("history_path")
            if history_path:
                completed_source_states = [
                    source for source in state["sources"].values() if source.get("status") == "fetched"
                ]
                try:
                    record_update_event(
                        history_path,
                        "automatic_literature_update",
                        "Nature / arXiv / Science incremental update",
                        status=state["status"],
                        details={
                            "run_id": state["run_id"],
                            "sources": [source.get("name", source.get("source_id", "")) for source in completed_source_states],
                            "source_rows": sum(int(source.get("rows", 0) or 0) for source in completed_source_states),
                            "papers_added": int(import_result.get("added", 0) or 0),
                            "papers_updated": int(import_result.get("updated", 0) or 0),
                            "failed_sources": [source.get("name", source.get("source_id", "")) for source in failed],
                        },
                    )
                except OSError:
                    append_history("Literature update committed, but its timeline entry could not be saved.", level="warning")
            _remove_staging_dir(
                state["staging_dir"],
                payload.get("staging_root") or LITERATURE_UPDATE_STAGING_DIR,
            )
            update_progress(1.0, "Literature update committed")
            return {
                "run_id": state["run_id"],
                "status": state["status"],
                "source_count": len(source_ids),
                "completed_sources": sum(1 for source in state["sources"].values() if source.get("status") == "fetched"),
                "failed_sources": [source["source_id"] for source in failed],
                "import_result": import_result,
            }
        except Exception:
            state["status"] = "interrupted"
            state["interrupted_at_utc"] = _utc_now()
            _save_run_state(state, run_dir=run_dir)
            raise
