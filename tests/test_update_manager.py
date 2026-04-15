from chipseeker.update_manager import (
    advance_ieee_sources,
    default_nature_start_date,
    load_source_registry,
    save_source_registry,
    source_target_window,
    start_ieee_batch,
)


def test_source_registry_batch_and_watermark(tmp_path, monkeypatch):
    registry_path = tmp_path / "source_registry.json"
    template_path = tmp_path / "source_registry_template.json"
    template_path.write_text(
        """{
  "schema_version": 1,
  "sources": [
    {
      "id": "ieee_jssc",
      "provider": "ieee",
      "enabled": true,
      "name": "JSSC",
      "search_query": "Journal of Solid-State Circuits",
      "open_url": "https://example.com/jssc",
      "last_completed_month": "2026-03"
    },
    {
      "id": "nature_q",
      "provider": "nature",
      "enabled": true,
      "name": "Nature Quantum",
      "query": "cryogenic CMOS",
      "last_checked_date": "2026-04-10"
    }
  ],
  "pending_ieee_batch": null
}""",
        encoding="utf-8",
    )

    monkeypatch.setattr("chipseeker.update_manager.SOURCE_REGISTRY_FILE", str(registry_path))
    monkeypatch.setattr("chipseeker.update_manager.SOURCE_REGISTRY_TEMPLATE_FILE", str(template_path))

    registry = load_source_registry(str(registry_path))
    batch = start_ieee_batch(registry, ["ieee_jssc"], "2026-04")
    save_source_registry(registry, str(registry_path))

    assert batch["target_month"] == "2026-04"
    assert batch["windows"][0]["start_date"] == "2026-04-01"
    assert batch["windows"][0]["end_date"] == "2026-04-30"

    advance_ieee_sources(registry, ["ieee_jssc"], "2026-04")
    assert source_target_window(registry["sources"][0], "2026-04") == ("2026-04-01", "2026-04-30")
    assert default_nature_start_date(registry["sources"][1]) == "2026-04-11"
