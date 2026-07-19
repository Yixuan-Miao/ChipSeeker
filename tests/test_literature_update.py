import csv
import json
from datetime import date
from pathlib import Path

import chipseeker.literature_update as lu


def _write_source(path, title="New Chip Paper"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=lu.OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerow(
            {
                "Document Title": title,
                "Abstract": "A" * 160,
                "Authors": "Alice; Bob",
                "Author Keywords": "chip",
                "Publication Year": "2026",
                "Publication Title": "Nature Electronics",
                "DOI": "10.1000/new-chip",
                "PDF Link": "",
                "Source URL": "https://example.org/new-chip",
            }
        )


def test_literature_update_stages_then_commits_once(monkeypatch, tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    db_file = tmp_path / "papers.json"
    db_file.write_text("[]", encoding="utf-8")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    manifest_path = tmp_path / "source_manifest.json"
    registry_path = tmp_path / "registry.json"
    local_state_path = tmp_path / "schema_state.json"
    history_path = tmp_path / "paper_update_history.json"
    run_dir = tmp_path / "runs"
    staging_root = tmp_path / "staging"
    official_dir = source_root / "generated_exports" / "nature_updates"
    registry_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "test_nature_v2",
                        "provider": "nature",
                        "generation": 2,
                        "revision": 1,
                        "enabled": True,
                        "name": "Test Nature",
                        "query": "chip",
                        "last_checked_date": "2026-07-01",
                        "export_prefix": "test_nature_v2",
                    }
                ],
                "pending_ieee_batch": None,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setitem(lu.PROVIDER_OUTPUT_DIRS, "nature", str(official_dir))

    def fake_fetch(source, source_state, article_cache, progress_callback, cancel_callback):
        assert list(source_root.rglob("*.csv")) == []
        _write_source(source_state["output_file"])
        progress_callback({"pages": 1, "rows": 1})
        return {
            "rows": [],
            "row_count": 1,
            "pages": 1,
            "completed": True,
            "truncated": False,
            "output_file": source_state["output_file"],
        }

    monkeypatch.setattr(lu, "_fetch_source", fake_fetch)
    result = lu.run_literature_update(
        "task-1",
        {
            "registry_path": str(registry_path),
            "source_ids": ["test_nature_v2"],
            "db_file": str(db_file),
            "cache_dir": str(cache_dir),
            "source_root": str(source_root),
            "manifest_path": str(manifest_path),
            "local_state_path": str(local_state_path),
            "run_dir": str(run_dir),
            "staging_root": str(staging_root),
            "history_path": str(history_path),
        },
        update_progress=lambda *_args: None,
        append_history=lambda *_args, **_kwargs: None,
        cancel_requested=lambda: False,
    )

    assert result["status"] == "completed"
    assert result["import_result"]["added"] == 1
    assert len(list(official_dir.rglob("*.csv"))) == 1
    assert len(json.loads(db_file.read_text(encoding="utf-8"))) == 1
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    source = next(item for item in registry["sources"] if item["id"] == "test_nature_v2")
    assert source["last_checked_date"] == date.today().isoformat()
    schema_state = json.loads(local_state_path.read_text(encoding="utf-8"))
    assert schema_state["library_sync"]["source_token"]
    assert schema_state["library_sync"]["source_token"] == schema_state["bibliographic_metadata_enrich"]["source_token"]
    history = json.loads(history_path.read_text(encoding="utf-8"))
    assert history["events"][0]["event_type"] == "automatic_literature_update"
    assert history["events"][0]["details"]["papers_added"] == 1


def test_create_or_resume_run_preserves_fetched_source(monkeypatch, tmp_path):
    source = {
        "id": "resume_v2",
        "provider": "nature",
        "generation": 2,
        "enabled": True,
        "name": "Resume",
        "query": "chip",
        "last_checked_date": "2026-07-01",
    }
    monkeypatch.setattr(lu, "load_source_registry", lambda *_args, **_kwargs: {"sources": [source]})
    first = lu.create_or_resume_run("unused.json", ["resume_v2"], run_dir=str(tmp_path / "runs"), staging_root=str(tmp_path / "stage"))
    staged = tmp_path / "stage" / first["run_id"] / "nature" / "resume.csv"
    _write_source(staged)
    first["sources"]["resume_v2"]["status"] = "fetched"
    first["sources"]["resume_v2"]["output_file"] = str(staged)
    first["status"] = "interrupted"
    lu._save_run_state(first, run_dir=str(tmp_path / "runs"))

    resumed = lu.create_or_resume_run("unused.json", ["resume_v2"], run_dir=str(tmp_path / "runs"), staging_root=str(tmp_path / "stage"))

    assert resumed["run_id"] == first["run_id"]
    assert resumed["sources"]["resume_v2"]["status"] == "fetched"


def test_create_run_can_override_incremental_start_date(monkeypatch, tmp_path):
    source = {
        "id": "backfill_v2",
        "provider": "nature",
        "generation": 2,
        "enabled": True,
        "name": "Backfill",
        "query": "chip",
        "last_checked_date": "2026-07-17",
    }
    monkeypatch.setattr(lu, "load_source_registry", lambda *_args, **_kwargs: {"sources": [source]})

    state = lu.create_or_resume_run(
        "unused.json",
        ["backfill_v2"],
        start_date_override="2021-07-18",
        run_dir=str(tmp_path / "runs"),
        staging_root=str(tmp_path / "stage"),
    )

    assert state["start_date_override"] == "2021-07-18"
    assert state["sources"]["backfill_v2"]["start_date"] == "2021-07-18"


def test_load_nature_article_cache_reuses_complete_rows(tmp_path):
    source_dir = tmp_path / "nature"
    source_dir.mkdir()
    source_file = source_dir / "existing.csv"
    lu._write_csv_rows(
        str(source_file),
        [
            {
                "Document Title": "Reusable paper",
                "Abstract": "Complete metadata",
                "Source URL": "https://www.nature.com/articles/example?utm_source=test",
            },
            {
                "Document Title": "Missing abstract",
                "Abstract": "",
                "Source URL": "https://www.nature.com/articles/incomplete",
            },
        ],
    )

    cached = lu._load_nature_article_cache(str(source_dir))

    assert list(cached) == ["https://www.nature.com/articles/example"]
    assert cached["https://www.nature.com/articles/example"]["Document Title"] == "Reusable paper"


def test_recover_incomplete_nature_source_retries_only_failed_urls(tmp_path):
    output_file = tmp_path / "partial.csv"
    _write_source(output_file, title="Existing paper")
    source = {"provider": "nature", "relevance_scopes": None}
    source_state = {
        "output_file": str(output_file),
        "report": {
            "failed": [
                {"url": "https://www.nature.com/articles/recovered", "error": "timeout"},
                {"url": "https://www.nature.com/articles/still-failing", "error": "timeout"},
            ],
            "truncated": False,
            "invalid_rows": 0,
        },
    }

    def fetcher(url):
        if url.endswith("still-failing"):
            raise RuntimeError("still unavailable")
        return {
            "Document Title": "Recovered paper",
            "Abstract": "Complete metadata",
            "Publication Year": "2026",
            "Publication Title": "Nature Electronics",
            "DOI": "10.1000/recovered",
            "Source URL": url,
        }

    report = lu._recover_incomplete_nature_source(source, source_state, {}, fetcher=fetcher)

    assert report["row_count"] == 2
    assert report["completed"] is False
    assert [item["url"] for item in report["failed"]] == ["https://www.nature.com/articles/still-failing"]
