import os
import random
import re
import threading
import time
import uuid
from datetime import date
from concurrent.futures import ThreadPoolExecutor

from chipseeker.data_sync import import_csv_files_incremental
from chipseeker.embedding_scope import build_scope_key, filter_papers_by_years
from chipseeker.paths import CACHE_DIR, DB_FILE, SOURCE_CSV_DIR, SOURCE_MANIFEST_FILE
from chipseeker.update_manager import default_incremental_start_date, find_source, load_source_registry, save_incremental_run_result, save_source_registry
from chipseeker.utils import load_json
from search_runtime import PaperSearcher


_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chipseeker")
_TASKS = {}
_LOCK = threading.Lock()
_MAX_HISTORY = 200
DEFAULT_LLM_RERANK_LIMIT = 30
SEMANTIC_PREFILTER_MULTIPLIER = 20
SEMANTIC_PREFILTER_MIN = 1000
SEMANTIC_PREFILTER_MAX = 5000


def _log(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [task-queue] {message}", flush=True)


def _summarize_payload(payload):
    summary = {}
    for key, value in payload.items():
        if key in {"api_key", "access_code"} or key.endswith("_api_key") or key.endswith("_token"):
            summary[key] = "***"
        elif key == "papers":
            summary[key] = f"{len(value)} papers"
        elif key == "source_ids":
            summary[key] = list(value)
        else:
            summary[key] = value
    return summary


def _summarize_result(result):
    """Keep task logs small so large paper payloads cannot block completion."""
    if not isinstance(result, dict):
        return str(result)[:500]

    summary = {}
    for key, value in result.items():
        if key == "results" and isinstance(value, list):
            summary[key] = f"{len(value)} results"
        elif isinstance(value, (list, tuple, set)):
            summary[key] = f"{len(value)} items"
        elif isinstance(value, dict):
            summary[key] = f"{len(value)} fields"
        elif isinstance(value, str) and len(value) > 240:
            summary[key] = f"{value[:237]}..."
        else:
            summary[key] = value
    return summary


def _set_task(task_id, **updates):
    with _LOCK:
        task = _TASKS.setdefault(task_id, {})
        updates.setdefault("updated_at", time.time())
        task.update(updates)


def append_history(task_id, message, level="info"):
    timestamp = time.strftime("%H:%M:%S")
    entry = {"timestamp": timestamp, "level": level, "message": str(message)}
    with _LOCK:
        task = _TASKS.setdefault(task_id, {})
        history = task.setdefault("history", [])
        history.append(entry)
        if len(history) > _MAX_HISTORY:
            del history[:-_MAX_HISTORY]


def _run_task(task_id, fn, payload):
    _set_task(task_id, status="running", started_at=time.time())
    _log(f"{task_id} started payload={_summarize_payload(payload)}")
    append_history(task_id, f"Task started: {_summarize_payload(payload)}")
    try:
        result = fn(task_id, payload)
    except Exception as exc:
        current = get_task(task_id) or {}
        if current.get("cancel_requested") or current.get("status") == "canceled":
            _log(f"{task_id} canceled while running")
            append_history(task_id, "Task stopped after cancellation.", level="warning")
            _set_task(task_id, status="canceled", message="Canceled", finished_at=time.time())
            return
        _log(f"{task_id} failed error={exc}")
        append_history(task_id, f"Task failed: {exc}", level="error")
        _set_task(task_id, status="failed", error=str(exc), finished_at=time.time())
    else:
        current = get_task(task_id) or {}
        if current.get("cancel_requested") or current.get("status") == "canceled":
            _log(f"{task_id} canceled result discarded")
            append_history(task_id, "Task result discarded because it was canceled.", level="warning")
            _set_task(task_id, status="canceled", message="Canceled", finished_at=time.time())
            return
        result_summary = _summarize_result(result)
        _log(f"{task_id} completed result={result_summary}")
        append_history(task_id, f"Task completed: {result_summary}", level="success")
        _set_task(task_id, status="completed", result=result, finished_at=time.time())


def submit_task(kind, payload, fn):
    task_id = f"{kind}-{uuid.uuid4().hex[:10]}"
    task = {
        "id": task_id,
        "kind": kind,
        "status": "queued",
        "progress": 0.0,
        "message": "Queued",
        "payload": payload,
        "created_at": time.time(),
        "history": [{"timestamp": time.strftime("%H:%M:%S"), "level": "info", "message": f"Queued task {kind}"}],
    }
    with _LOCK:
        _TASKS[task_id] = task
    _log(f"{task_id} queued kind={kind}")
    _EXECUTOR.submit(_run_task, task_id, fn, payload)
    return task_id


def get_task(task_id):
    with _LOCK:
        task = _TASKS.get(task_id)
        return dict(task) if task else None


def update_progress(task_id, progress=None, message=None):
    updates = {}
    if progress is not None:
        updates["progress"] = max(0.0, min(1.0, float(progress)))
    if message is not None:
        updates["message"] = message
    if updates:
        _set_task(task_id, **updates)
        if message is not None:
            percent = updates.get("progress")
            if percent is None:
                current = get_task(task_id)
                percent = current.get("progress", 0.0) if current else 0.0
            _log(f"{task_id} progress={percent * 100:.1f}% message={message}")
            append_history(task_id, f"{percent * 100:.1f}% | {message}")


def task_cancel_requested(task_id):
    task = get_task(task_id)
    return bool(task and (task.get("cancel_requested") or task.get("status") == "canceled"))


def cancel_task(task_id, message="Canceled by user"):
    if not task_id:
        return
    append_history(task_id, message, level="warning")
    _set_task(
        task_id,
        status="canceled",
        cancel_requested=True,
        message=message,
        finished_at=time.time(),
    )


def cleanup_task(task_id):
    with _LOCK:
        _TASKS.pop(task_id, None)


def _build_embeddings(task_id, payload):
    papers = load_json(payload["db_file"], [])
    years = payload.get("years") or []
    scoped_papers = filter_papers_by_years(papers, years) if years else papers
    scope_key = payload.get("scope_key") or build_scope_key(years)

    def progress(done, total, message):
        update_progress(task_id, done / max(1, total), message)

    def log_callback(message):
        append_history(task_id, message)

    _log(f"{task_id} embedding setup model={payload['model_name']} scope={scope_key} papers={len(scoped_papers)} db={payload['db_file']}")
    update_progress(task_id, 0.01, f"Loading library for scope {scope_key}")
    searcher = PaperSearcher(
        payload["db_file"],
        model_name=payload["model_name"],
        api_key=payload.get("api_key", ""),
        papers_override=scoped_papers,
        scope_key=scope_key,
        progress_callback=progress,
        log_callback=log_callback,
    )
    _raise_if_cancelled(task_id)
    update_progress(task_id, 0.05, "Building/repairing embedding cache (this may take minutes for large libraries)")
    searcher._ensure_embeddings()
    update_progress(task_id, 1.0, "Embedding cache is ready")
    return {"model_name": payload["model_name"], "scope_key": scope_key, "paper_count": len(scoped_papers), "years": years}


def submit_embedding_build(db_file, model_name, api_key="", years=None, scope_key=None):
    return submit_task(
        "embedding-build",
        {"db_file": db_file, "model_name": model_name, "api_key": api_key, "years": years or [], "scope_key": scope_key},
        _build_embeddings,
    )


def _raise_if_cancelled(task_id):
    if task_cancel_requested(task_id):
        raise RuntimeError("Task was canceled.")


def _llm_powered_search(task_id, payload):
    from chipseeker.llm_tools import expand_search_query_with_llm, rerank_results_with_llm
    from chipseeker.search_ui import filter_search_results
    from chipseeker.utils import extract_year
    from chipseeker.venue_data import analyze_venue

    search_query = str(payload.get("search_query", "")).strip()
    must_have = str(payload.get("must_have", "")).strip()
    display_limit = int(payload.get("display_limit", 50) or 50)
    rerank_limit = int(payload.get("rerank_limit", DEFAULT_LLM_RERANK_LIMIT) or DEFAULT_LLM_RERANK_LIMIT)
    selected_years = tuple(payload.get("selected_years") or ())
    selected_ui_venues = list(payload.get("selected_ui_venues") or [])
    active_scope_years = list(payload.get("active_scope_years") or [])
    active_scope_key = payload.get("active_scope_key") or build_scope_key(active_scope_years)

    update_progress(task_id, 0.05, "Preparing ChipSeeker Pro Search")
    all_papers = load_json(payload["db_file"], [])
    scoped_papers = filter_papers_by_years(all_papers, active_scope_years) if active_scope_years else None
    search_papers = scoped_papers if scoped_papers is not None else all_papers
    _raise_if_cancelled(task_id)

    update_progress(task_id, 0.12, "Expanding query with LLM")
    effective_query = expand_search_query_with_llm(
        search_query,
        payload.get("llm_api_key", ""),
        payload.get("llm_base_url", ""),
        payload.get("llm_model", ""),
    )
    _raise_if_cancelled(task_id)

    update_progress(task_id, 0.28, "Loading ChipSeeker Lite cache")
    searcher = PaperSearcher(
        payload["db_file"],
        model_name=payload["embedding_model"],
        api_key=payload.get("embedding_api_key", ""),
        papers_override=search_papers,
        scope_key=active_scope_key,
    )
    _raise_if_cancelled(task_id)

    update_progress(task_id, 0.48, "Running ChipSeeker Lite retrieval")
    candidate_top_k = min(max(display_limit, 120), 400)
    if must_have or selected_ui_venues:
        semantic_top_k = min(
            max(int(display_limit) * SEMANTIC_PREFILTER_MULTIPLIER, SEMANTIC_PREFILTER_MIN),
            SEMANTIC_PREFILTER_MAX,
        )
        semantic_hits = searcher.search(query=effective_query, top_k=semantic_top_k)
        initial_scan_count = len(semantic_hits)
        filtered_results = filter_search_results(
            semantic_hits,
            selected_years,
            selected_ui_venues,
            must_have,
            analyze_venue,
            extract_year,
        )
    else:
        filtered_results = searcher.search(query=effective_query, top_k=candidate_top_k)
        filtered_results = filter_search_results(
            filtered_results,
            selected_years,
            selected_ui_venues,
            "",
            analyze_venue,
            extract_year,
        )
        initial_scan_count = len(filtered_results)
    _raise_if_cancelled(task_id)

    actual_rerank_limit = min(rerank_limit, len(filtered_results))
    update_progress(task_id, 0.68, f"LLM reranking top {actual_rerank_limit} papers")
    filtered_results = rerank_results_with_llm(
        search_query,
        effective_query,
        filtered_results,
        payload.get("llm_api_key", ""),
        payload.get("llm_base_url", ""),
        payload.get("llm_model", ""),
        limit=actual_rerank_limit,
    )
    _raise_if_cancelled(task_id)

    if len(filtered_results) > display_limit:
        filtered_results = filtered_results[:display_limit]
    update_progress(task_id, 1.0, "ChipSeeker Pro Search finished")
    return {
        "results": filtered_results,
        "initial_count": initial_scan_count,
        "effective_query": effective_query,
        "search_query": search_query,
        "must_have": must_have,
        "display_limit": display_limit,
        "selected_ui_venues": selected_ui_venues,
        "selected_years": selected_years,
        "embedding_model": payload.get("embedding_model", ""),
        "search_mode": "llm_powered",
        "rerank_limit": actual_rerank_limit,
        "query_state_key": payload.get("query_state_key", ""),
    }


def submit_llm_powered_search(
    db_file,
    search_query,
    must_have,
    display_limit,
    selected_ui_venues,
    selected_years,
    embedding_model,
    embedding_api_key="",
    active_scope_key="all",
    active_scope_years=None,
    llm_api_key="",
    llm_base_url="",
    llm_model="",
    rerank_limit=DEFAULT_LLM_RERANK_LIMIT,
    query_state_key="",
):
    return submit_task(
        "llm-search",
        {
            "db_file": db_file,
            "search_query": search_query,
            "must_have": must_have,
            "display_limit": display_limit,
            "selected_ui_venues": selected_ui_venues,
            "selected_years": selected_years,
            "embedding_model": embedding_model,
            "embedding_api_key": embedding_api_key,
            "active_scope_key": active_scope_key,
            "active_scope_years": active_scope_years or [],
            "llm_api_key": llm_api_key,
            "llm_base_url": llm_base_url,
            "llm_model": llm_model,
            "rerank_limit": rerank_limit,
            "query_state_key": query_state_key,
        },
        _llm_powered_search,
    )


def _download_pdfs(task_id, payload):
    from playwright.sync_api import sync_playwright

    papers = payload["papers"]
    save_dir = payload["save_dir"]
    os.makedirs(save_dir, exist_ok=True)
    success_n = 0
    fail_n = 0
    failures = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            accept_downloads=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        for index, paper in enumerate(papers):
            url = paper.get("pdf_link") or (f"https://doi.org/{paper['doi']}" if paper.get("doi") else "")
            title_safe = re.sub(r'[\\/*?:"<>|]', "", paper.get("title", f"paper_{index}"))[:100]
            update_progress(task_id, index / max(1, len(papers)), f"Fetching {index + 1}/{len(papers)}: {title_safe}")
            if not url:
                fail_n += 1
                failures.append({"title": paper.get("title", ""), "reason": "missing_url"})
                continue

            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                time.sleep(2)
                actual_pdf_url = url
                if "ieeexplore.ieee.org" in page.url or "stamp.jsp" in page.url:
                    for frame in page.frames:
                        if ".pdf" in frame.url:
                            actual_pdf_url = frame.url
                            break
                with page.expect_download(timeout=30000) as download_info:
                    page.evaluate(f"window.location.href = '{actual_pdf_url}'")
                download = download_info.value
                download.save_as(os.path.join(save_dir, f"{title_safe}.pdf"))
                success_n += 1
            except Exception as exc:
                fail_n += 1
                failures.append({"title": paper.get("title", ""), "reason": str(exc)})
            finally:
                page.close()

            update_progress(task_id, (index + 1) / max(1, len(papers)), f"Processed {index + 1}/{len(papers)}")
            time.sleep(random.uniform(8.0, 18.0))
            if (index + 1) % 10 == 0:
                time.sleep(45)
        browser.close()

    update_progress(task_id, 1.0, "PDF download finished")
    return {"success": success_n, "failed": fail_n, "save_dir": save_dir, "failures": failures}


def submit_pdf_download(papers, save_dir):
    return submit_task(
        "pdf-download",
        {"papers": papers, "save_dir": save_dir},
        _download_pdfs,
    )


def _run_provider_incremental(task_id, payload):
    from Nature_Grabber import grab_nature
    from Arxiv_Grabber import grab_arxiv
    from Science_Grabber import grab_science

    registry = load_source_registry(payload["registry_path"])
    source_ids = payload["source_ids"]
    output_dir = payload["output_dir"]
    provider = payload["provider"]
    run_date = date.today().isoformat()
    completed_ids = []
    written_files = []
    source_count = max(1, len(source_ids))

    for index, source_id in enumerate(source_ids):
        source = find_source(registry, source_id)
        if not source or not source.get("enabled") or not source.get("query"):
            continue
        source_start_date = default_incremental_start_date(source)
        update_progress(task_id, index / source_count * 0.88, f"Fetching {provider} source {source.get('name', source_id)} from {source_start_date}")
        source_dir = os.path.join(output_dir, source_id)
        os.makedirs(source_dir, exist_ok=True)
        safe_start_date = source_start_date.replace("-", "")
        output_file = os.path.join(source_dir, f"{source.get('export_prefix', source_id)}_{run_date}_from{safe_start_date}.csv")
        try:
            if provider == "nature":
                rows = grab_nature(
                    query=source["query"],
                    output_file=output_file,
                    journal=source.get("journal", ""),
                    year_from=2015,
                    start_date=source_start_date,
                    max_pages=int(source.get("max_pages", 5)),
                    sleep_seconds=float(source.get("sleep_seconds", 1.0)),
                )
            elif provider == "arxiv":
                rows = grab_arxiv(
                    query=source["query"],
                    output_file=output_file,
                    categories=source.get("categories", []),
                    start_date=source_start_date,
                    max_results=int(source.get("max_results", 100)),
                    sleep_seconds=float(source.get("sleep_seconds", 0.5)),
                )
            elif provider == "science":
                rows = grab_science(
                    query=source["query"],
                    output_file=output_file,
                    issns=source.get("issns", []),
                    start_date=source_start_date,
                    max_results=int(source.get("max_results", 100)),
                    sleep_seconds=float(source.get("sleep_seconds", 0.5)),
                )
            else:
                raise ValueError(f"Unsupported provider: {provider}")
        except Exception as exc:
            written_files.append({"source_id": source_id, "output_file": output_file, "rows": 0, "start_date": source_start_date, "error": str(exc)})
            append_history(task_id, f"{provider} source failed: {source.get('name', source_id)} | {exc}", level="error")
            continue
        written_files.append({"source_id": source_id, "output_file": output_file, "rows": len(rows), "start_date": source_start_date})
        update_progress(
            task_id,
            ((index + 1) / source_count) * 0.88,
            f"Fetched {provider} source {source.get('name', source_id)}: {len(rows)} rows",
        )
        append_history(task_id, f"Wrote {len(rows)} rows to {output_file}")
        completed_ids.append(source_id)

    if completed_ids:
        save_incremental_run_result(registry, completed_ids, run_date)
        save_source_registry(registry, payload["registry_path"])

    import_result = None
    if payload.get("import_after") and completed_ids:
        update_progress(task_id, 0.92, "Importing fetched CSV files into the paper library")
        successful_files = [item["output_file"] for item in written_files if item.get("output_file") and not item.get("error")]
        added, updated, removed, file_summaries = import_csv_files_incremental(
            payload.get("db_file") or DB_FILE,
            payload.get("cache_dir") or CACHE_DIR,
            successful_files,
            source_root=payload.get("source_root") or SOURCE_CSV_DIR,
            manifest_path=payload.get("manifest_path") or SOURCE_MANIFEST_FILE,
        )
        import_result = {
            "added": added,
            "updated": updated,
            "removed": removed,
            "files_scanned": len(file_summaries),
        }
        append_history(task_id, f"Imported CSV files: added={added}, updated={updated}, removed={removed}, files_scanned={len(file_summaries)}")

    update_progress(task_id, 1.0, f"{provider} incremental update finished")
    return {
        "provider": provider,
        "source_ids": completed_ids,
        "written_files": written_files,
        "checked_date": run_date,
        "import_result": import_result,
    }


def submit_nature_incremental(
    registry_path,
    source_ids,
    output_dir,
    import_after=False,
    db_file=None,
    cache_dir=None,
    source_root=None,
    manifest_path=None,
):
    return submit_task(
        "nature-incremental",
        {
            "registry_path": registry_path,
            "source_ids": source_ids,
            "output_dir": output_dir,
            "provider": "nature",
            "import_after": import_after,
            "db_file": db_file,
            "cache_dir": cache_dir,
            "source_root": source_root,
            "manifest_path": manifest_path,
        },
        _run_provider_incremental,
    )


def submit_arxiv_incremental(registry_path, source_ids, output_dir):
    return submit_task(
        "arxiv-incremental",
        {"registry_path": registry_path, "source_ids": source_ids, "output_dir": output_dir, "provider": "arxiv"},
        _run_provider_incremental,
    )


def submit_science_incremental(
    registry_path,
    source_ids,
    output_dir,
    import_after=False,
    db_file=None,
    cache_dir=None,
    source_root=None,
    manifest_path=None,
):
    return submit_task(
        "science-incremental",
        {
            "registry_path": registry_path,
            "source_ids": source_ids,
            "output_dir": output_dir,
            "provider": "science",
            "import_after": import_after,
            "db_file": db_file,
            "cache_dir": cache_dir,
            "source_root": source_root,
            "manifest_path": manifest_path,
        },
        _run_provider_incremental,
    )
