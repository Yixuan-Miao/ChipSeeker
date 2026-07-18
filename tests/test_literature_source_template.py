import json
from pathlib import Path


TEMPLATE = Path(__file__).parents[1] / "chipseeker" / "data" / "literature_sources_v2.json"


def test_literature_template_uses_short_domain_sources():
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    sources = payload["sources"]
    nature = [source for source in sources if source["provider"] == "nature"]
    arxiv = [source for source in sources if source["provider"] == "arxiv"]
    science = [source for source in sources if source["provider"] == "science"]

    assert payload["schema_version"] == 3
    assert len(nature) >= 8
    assert all(len(source["query"]) < 350 for source in nature)
    assert any("CMOS" in source["query"] and "integrated circuit" in source["query"] for source in nature)
    assert any("foundation model" in source["query"] and source.get("relevance_scopes") == ["ai_core"] for source in nature)
    assert any("quantum error correction" in source["query"] and "quantum simulation" in source["query"] for source in nature)
    assert all(source["categories"] for source in arxiv)
    assert all(source["initial_lookback_days"] <= 180 for source in arxiv)
    assert len(science) == 1
    assert "machine learning" not in science[0]["query"].lower()
    assert "integrated circuit" in science[0]["query"].lower()
