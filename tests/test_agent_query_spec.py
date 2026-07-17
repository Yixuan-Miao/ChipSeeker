import json

import pytest

from chipseeker.agent_query_spec import load_query_spec, normalize_query_spec


def test_query_spec_supports_per_query_constraints_and_roles(tmp_path):
    path = tmp_path / "queries.json"
    path.write_text(
        json.dumps(
            {
                "schema": "chipseeker-agent-query-spec/v1",
                "defaults": {"years": "2020:2026", "abstract_chars": 0},
                "queries": [
                    {
                        "id": "inp-receiver",
                        "mode": "filtered-lite",
                        "query": "cryogenic qubit readout receiver",
                        "all_terms": ["InP"],
                        "any_terms": ["receiver", "front-end"],
                        "query_family": "receiver-container",
                        "query_role": "receiver_soc",
                        "coverage": {"technology": ["InP"], "container": ["receiver", "SoC"]},
                        "top_k": 120,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    entries = normalize_query_spec(load_query_spec(path))

    assert entries[0]["mode"] == "filtered_lite"
    assert entries[0]["years"] == (2020, 2026)
    assert entries[0]["all_terms"] == ["InP"]
    assert entries[0]["query_role"] == "receiver_soc"
    assert entries[0]["coverage"]["container"] == ["receiver", "SoC"]
    assert entries[0]["top_k"] == 120


def test_query_spec_rejects_filtered_lite_without_hard_selectors():
    with pytest.raises(ValueError, match="requires structured selectors"):
        normalize_query_spec(
            {
                "queries": [
                    {"id": "bad", "mode": "filtered-lite", "query": "cryogenic LNA"}
                ]
            }
        )
