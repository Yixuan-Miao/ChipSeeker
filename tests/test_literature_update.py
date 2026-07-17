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
