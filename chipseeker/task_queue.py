import os
import random
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from chipseeker.embedding_scope import build_scope_key, filter_papers_by_years
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


def _run_resumable_literature_update(task_id, payload):
    from chipseeker.literature_update import run_literature_update

    return run_literature_update(
        task_id,
        payload,
        update_progress=lambda progress, message: update_progress(task_id, progress, message),
        append_history=lambda message, level="info": append_history(task_id, message, level=level),
        cancel_requested=lambda: task_cancel_requested(task_id),
    )


def submit_literature_incremental(
    registry_path,
    source_ids,
    db_file=None,
    cache_dir=None,
    source_root=None,
    manifest_path=None,
    local_state_path=None,
    run_dir=None,
    staging_root=None,
    history_path=None,
):
    return submit_task(
        "literature-v2",
        {
            "registry_path": registry_path,
            "source_ids": list(source_ids),
            "db_file": db_file,
            "cache_dir": cache_dir,
            "source_root": source_root,
            "manifest_path": manifest_path,
            "local_state_path": local_state_path,
            "run_dir": run_dir,
            "staging_root": staging_root,
            "history_path": history_path,
        },
        _run_resumable_literature_update,
    )
