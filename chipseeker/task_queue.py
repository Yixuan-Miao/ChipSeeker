import os
import random
import re
import threading
import time
import uuid
from datetime import date
from concurrent.futures import ThreadPoolExecutor

from chipseeker.update_manager import default_nature_start_date, find_source, load_source_registry, save_nature_run_result, save_source_registry
from search_runtime import PaperSearcher


_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chipseeker")
_TASKS = {}
_LOCK = threading.Lock()


def _set_task(task_id, **updates):
    with _LOCK:
        task = _TASKS.setdefault(task_id, {})
        task.update(updates)


def _run_task(task_id, fn, payload):
    _set_task(task_id, status="running", started_at=time.time())
    try:
        result = fn(task_id, payload)
    except Exception as exc:
        _set_task(task_id, status="failed", error=str(exc), finished_at=time.time())
    else:
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
    }
    with _LOCK:
        _TASKS[task_id] = task
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


def cleanup_task(task_id):
    with _LOCK:
        _TASKS.pop(task_id, None)


def _build_embeddings(task_id, payload):
    update_progress(task_id, 0.05, "Loading library and building embeddings")
    PaperSearcher(payload["db_file"], model_name=payload["model_name"], api_key=payload.get("api_key", ""))
    update_progress(task_id, 1.0, "Embedding cache is ready")
    return {"model_name": payload["model_name"]}


def submit_embedding_build(db_file, model_name, api_key=""):
    return submit_task(
        "embedding-build",
        {"db_file": db_file, "model_name": model_name, "api_key": api_key},
        _build_embeddings,
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


def _run_nature_incremental(task_id, payload):
    from Nature_Grabber import grab_nature

    registry = load_source_registry(payload["registry_path"])
    source_ids = payload["source_ids"]
    output_dir = payload["output_dir"]
    run_date = date.today().isoformat()
    completed_ids = []
    written_files = []

    for index, source_id in enumerate(source_ids):
        source = find_source(registry, source_id)
        if not source or not source.get("enabled") or not source.get("query"):
            continue
        update_progress(task_id, index / max(1, len(source_ids)), f"Fetching Nature source {source.get('name', source_id)}")
        source_dir = os.path.join(output_dir, source_id)
        os.makedirs(source_dir, exist_ok=True)
        output_file = os.path.join(source_dir, f"{source.get('export_prefix', source_id)}_{run_date}.csv")
        try:
            rows = grab_nature(
                query=source["query"],
                output_file=output_file,
                journal=source.get("journal", ""),
                year_from=2015,
                start_date=default_nature_start_date(source),
                max_pages=int(source.get("max_pages", 5)),
                sleep_seconds=float(source.get("sleep_seconds", 1.0)),
            )
        except Exception as exc:
            written_files.append({"source_id": source_id, "output_file": output_file, "rows": 0, "error": str(exc)})
            continue
        written_files.append({"source_id": source_id, "output_file": output_file, "rows": len(rows)})
        completed_ids.append(source_id)

    if completed_ids:
        save_nature_run_result(registry, completed_ids, run_date)
        save_source_registry(registry, payload["registry_path"])
    update_progress(task_id, 1.0, "Nature incremental update finished")
    return {"source_ids": completed_ids, "written_files": written_files, "checked_date": run_date}


def submit_nature_incremental(registry_path, source_ids, output_dir):
    return submit_task(
        "nature-incremental",
        {"registry_path": registry_path, "source_ids": source_ids, "output_dir": output_dir},
        _run_nature_incremental,
    )
