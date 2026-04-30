import json
import zipfile
from pathlib import Path

import numpy as np

from chipseeker.content_pack import build_content_pack, build_content_update_pack, detect_content_pack_status, install_bundled_demo_csv, install_content_pack, install_content_update_pack


class UploadedPack:
    def __init__(self, path):
        self._payload = Path(path).read_bytes()

    def getvalue(self):
        return self._payload


def test_build_and_install_content_pack(tmp_path):
    data_dir = tmp_path / "source_local_data"
    cache_dir = data_dir / "cache"
    sources_dir = data_dir / "sources" / "manual"
    cache_dir.mkdir(parents=True)
    sources_dir.mkdir(parents=True)

    db_file = data_dir / "isscc_papers.json"
    db_file.write_text(
        json.dumps(
            [
                {
                    "title": "Paper A",
                    "abstract": "A" * 120,
                    "year": "2026",
                    "venue": "ISSCC",
                    "doi": "10.1000/a",
                }
            ]
        ),
        encoding="utf-8",
    )
    (data_dir / "source_manifest.json").write_text(
        json.dumps({"entries": [{"relative_path": "manual/a.csv", "valid_source": True}]}),
        encoding="utf-8",
    )
    (data_dir / "schema_state.json").write_text(
        json.dumps({"schema_version": 5, "library_sync": {"db_record_count": 1}}),
        encoding="utf-8",
    )
    (data_dir / "source_registry.json").write_text(json.dumps({"sources": [], "pending_ieee_batch": None}), encoding="utf-8")
    (sources_dir / "a.csv").write_text("Document Title,Abstract\nPaper A," + ("A" * 120), encoding="utf-8")
    (cache_dir / "cache_isscc_papers_demo_all-MiniLM-L6-v2_all.npy").write_text("cache", encoding="utf-8")

    build_result = build_content_pack(
        str(data_dir),
        str(db_file),
        str(cache_dir),
        str(data_dir / "source_manifest.json"),
        schema_state={"library_sync": {"db_record_count": 1}},
        output_dir=str(tmp_path / "exports"),
        pack_name="demo_pack.zip",
    )
    zip_path = Path(build_result["zip_path"])
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path, "r") as archive:
        names = archive.namelist()
        assert "local_data/isscc_papers.json" in names
        assert "content_pack_manifest.json" in names

    target_dir = tmp_path / "target_local_data"
    install_result = install_content_pack(UploadedPack(zip_path), str(target_dir))
    assert install_result["copied_entries"] > 0
    assert (target_dir / "isscc_papers.json").exists()
    assert (target_dir / "sources" / "manual" / "a.csv").exists()

    status = detect_content_pack_status(
        str(target_dir),
        str(target_dir / "isscc_papers.json"),
        str(target_dir / "cache"),
        str(target_dir / "source_manifest.json"),
        schema_state={"library_sync": {"db_record_count": 1}},
    )
    assert status["pack_ready"] is True
    assert status["paper_count"] == 1


def test_install_bundled_demo_csv(tmp_path):
    demo_csv = tmp_path / "export2026.03.04-08.56.26.csv"
    demo_csv.write_text("Document Title,Abstract\nDemo," + ("A" * 120), encoding="utf-8")
    source_root = tmp_path / "local_data" / "sources"

    target_path = install_bundled_demo_csv(str(demo_csv), str(source_root))

    assert Path(target_path).exists()
    assert "generated_exports" in str(target_path)


def test_incremental_update_pack_merges_papers_and_cache_delta(tmp_path):
    data_dir = tmp_path / "source_local_data"
    cache_dir = data_dir / "cache"
    sources_dir = data_dir / "sources" / "generated_exports"
    cache_dir.mkdir(parents=True)
    sources_dir.mkdir(parents=True)
    db_file = data_dir / "isscc_papers.json"
    manifest_path = data_dir / "source_manifest.json"
    state_path = data_dir / "content_pack_state.json"

    paper_a = {"title": "Paper A", "abstract": "A" * 120, "year": "2026", "venue": "JSSC", "doi": "10.1000/a"}
    db_file.write_text(json.dumps([paper_a]), encoding="utf-8")
    manifest_path.write_text(json.dumps({"entries": []}), encoding="utf-8")
    (sources_dir / "export_a.csv").write_text("Document Title,Abstract\nPaper A," + ("A" * 120), encoding="utf-8")
    cache_file = cache_dir / "cache_isscc_papers_all-MiniLM-L6-v2_all.npy"
    meta_file = cache_dir / "cache_isscc_papers_all-MiniLM-L6-v2_all.meta.json"
    np.save(cache_file, np.array([[1.0, 0.0]], dtype=np.float32))
    meta_file.write_text(json.dumps({"fingerprints": ["fp-a"], "model_name": "all-MiniLM-L6-v2"}), encoding="utf-8")

    build_content_pack(
        str(data_dir),
        str(db_file),
        str(cache_dir),
        str(manifest_path),
        schema_state={"library_sync": {"db_record_count": 1}},
        output_dir=str(tmp_path / "exports"),
        pack_name="full.zip",
        state_path=str(state_path),
    )

    paper_b = {"title": "Paper B", "abstract": "B" * 120, "year": "2026", "venue": "JSSC", "doi": "10.1000/b"}
    db_file.write_text(json.dumps([paper_a, paper_b]), encoding="utf-8")
    (sources_dir / "export_b.csv").write_text("Document Title,Abstract\nPaper B," + ("B" * 120), encoding="utf-8")
    np.save(cache_file, np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))
    meta_file.write_text(json.dumps({"fingerprints": ["fp-a", "fp-b"], "model_name": "all-MiniLM-L6-v2"}), encoding="utf-8")

    update_result = build_content_update_pack(
        str(data_dir),
        str(db_file),
        str(cache_dir),
        str(manifest_path),
        schema_state={"library_sync": {"db_record_count": 2}},
        output_dir=str(tmp_path / "exports"),
        pack_name="update.zip",
        state_path=str(state_path),
    )
    assert update_result["paper_delta_count"] == 1
    assert update_result["cache_delta_count"] == 1

    target_dir = tmp_path / "target_local_data"
    (target_dir / "cache").mkdir(parents=True)
    (target_dir / "isscc_papers.json").write_text(json.dumps([paper_a]), encoding="utf-8")
    np.save(target_dir / "cache" / cache_file.name, np.array([[1.0, 0.0]], dtype=np.float32))
    (target_dir / "cache" / meta_file.name).write_text(json.dumps({"fingerprints": ["fp-a"], "model_name": "all-MiniLM-L6-v2"}), encoding="utf-8")

    install_result = install_content_update_pack(UploadedPack(Path(update_result["zip_path"])), str(target_dir))
    merged_papers = json.loads((target_dir / "isscc_papers.json").read_text(encoding="utf-8"))
    merged_cache = np.load(target_dir / "cache" / cache_file.name)
    assert install_result["paper_added"] == 1
    assert install_result["cache_appended"] == 1
    assert len(merged_papers) == 2
    assert merged_cache.shape == (2, 2)
