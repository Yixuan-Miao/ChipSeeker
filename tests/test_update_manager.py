from chipseeker.update_manager import (
    advance_ieee_sources,
    default_nature_start_date,
    load_source_registry,
    merge_literature_v2_sources,
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
      "id": "ieee_rfic",
      "provider": "ieee",
      "enabled": true,
      "source_kind": "conference",
      "name": "RFIC",
      "search_query": "RFIC",
      "open_url": "https://example.com/rfic",
      "last_completed_month": "2025-12"
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
    assert start_ieee_batch(registry, ["ieee_rfic"], "2026-04")["windows"][0]["start_date"] == "2026-01-01"

    advance_ieee_sources(registry, ["ieee_jssc"], "2026-04")
    assert source_target_window(registry["sources"][0], "2026-04") == ("2026-04-01", "2026-04-30")
    assert default_nature_start_date(registry["sources"][2]) == "2026-04-11"


def test_v2_sources_retire_legacy_and_inherit_earliest_nature_checkpoint(tmp_path, monkeypatch):
    template_path = tmp_path / "literature_v2.json"
    template_path.write_text(
        """{
  "sources": [
    {"id":"nature_v2","provider":"nature","generation":2,"revision":1,"enabled":true,"query":"chip","last_checked_date":""},
    {"id":"arxiv_v2","provider":"arxiv","generation":2,"revision":1,"enabled":true,"query":"chip","last_checked_date":""}
  ]
}""",
        encoding="utf-8",
    )
    monkeypatch.setattr("chipseeker.update_manager.LITERATURE_SOURCE_TEMPLATE_FILE", str(template_path))
    payload = {
        "sources": [
            {"id": "old_nature_a", "provider": "nature", "enabled": True, "last_checked_date": "2026-06-06"},
            {"id": "old_nature_b", "provider": "nature", "enabled": True, "last_checked_date": "2026-05-16"},
            {"id": "old_arxiv", "provider": "arxiv", "enabled": True, "last_checked_date": ""},
        ]
    }

    assert merge_literature_v2_sources(payload) is True
    by_id = {source["id"]: source for source in payload["sources"]}
    assert by_id["old_nature_a"]["enabled"] is False
    assert by_id["old_arxiv"]["enabled"] is False
    assert by_id["nature_v2"]["last_checked_date"] == "2026-05-16"
    assert by_id["arxiv_v2"]["last_checked_date"] == ""
