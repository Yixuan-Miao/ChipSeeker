import json
import zipfile
from pathlib import Path

from chipseeker.content_pack import build_content_pack, detect_content_pack_status, install_bundled_demo_csv, install_content_pack


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
