from chipseeker import migrations
from chipseeker.utils import load_json


def test_migrate_local_data_wraps_manifest_and_moves_root_csv(tmp_path, monkeypatch):
    data_dir = tmp_path / "local_data"
    source_dir = data_dir / "sources"
    manual_dir = source_dir / "manual"
    source_dir.mkdir(parents=True)

    legacy_csv = source_dir / "legacy.csv"
    legacy_csv.write_text("Document Title,Abstract\nA,B\n", encoding="utf-8")

    manifest_path = data_dir / "source_manifest.json"
    manifest_path.write_text('[{"relative_path":"legacy.csv","valid_source":true}]', encoding="utf-8")

    state_path = data_dir / "schema_state.json"
    conflict_path = data_dir / "conflict_resolutions.json"
    registry_path = data_dir / "source_registry.json"
    template_path = tmp_path / "source_registry_template.json"
    template_path.write_text('{"schema_version":1,"sources":[{"id":"ieee_jssc","provider":"ieee"},{"id":"arxiv_ai_hardware","provider":"arxiv"}],"pending_ieee_batch":null}', encoding="utf-8")

    monkeypatch.setattr(migrations, "SOURCE_CSV_DIR", str(source_dir))
    monkeypatch.setattr(migrations, "MANUAL_SOURCE_DIR", str(manual_dir))
    monkeypatch.setattr(migrations, "SOURCE_MANIFEST_FILE", str(manifest_path))
    monkeypatch.setattr(migrations, "LOCAL_DATA_STATE_FILE", str(state_path))
    monkeypatch.setattr(migrations, "CONFLICT_RESOLUTIONS_FILE", str(conflict_path))
    monkeypatch.setattr(migrations, "SOURCE_REGISTRY_FILE", str(registry_path))
    monkeypatch.setattr(migrations, "SOURCE_REGISTRY_TEMPLATE_FILE", str(template_path))

    state = migrations.migrate_local_data()

    assert state["schema_version"] == 4
    assert (manual_dir / "legacy.csv").exists()
    manifest = load_json(str(manifest_path), {})
    assert manifest["schema_version"] >= 1
    assert manifest["entries"][0]["relative_path"] == "legacy.csv"
    assert load_json(str(conflict_path), {})["dismissed"] == []
    registry = load_json(str(registry_path), {})
    assert registry["sources"][0]["id"] == "ieee_jssc"
    assert any(source["id"] == "arxiv_ai_hardware" for source in registry["sources"])
