# Structured Query And Evidence Reference

Use this reference when building a high-recall census query plan or screening file.

## Query spec

```json
{
  "schema": "chipseeker-agent-query-spec/v1",
  "scope": {
    "technology": ["InP"],
    "circuit": ["LNA"],
    "temperature": ["cryogenic"],
    "frequency": ["4-8 GHz"],
    "container": ["receiver", "readout IC", "SoC"]
  },
  "defaults": {
    "years": "2000:2026",
    "abstract_chars": 0,
    "result_view": "titles"
  },
  "queries": [
    {
      "id": "direct-spec",
      "mode": "lite",
      "query": "cryogenic InP 4-8 GHz low-noise amplifier",
      "query_family": "direct-specification",
      "query_role": "standalone_lna",
      "coverage": {
        "technology": ["InP"],
        "circuit": ["LNA"],
        "temperature": ["cryogenic"],
        "frequency": ["4-8 GHz"]
      },
      "top_k": 300
    },
    {
      "id": "receiver-container",
      "mode": "lite",
      "query": "cryogenic InP receiver readout IC low-noise front-end C-band",
      "query_family": "receiver-container",
      "query_role": "receiver_soc",
      "coverage": {
        "container": ["receiver", "readout IC", "SoC"]
      },
      "top_k": 300
    },
    {
      "id": "literal-inp-lna",
      "mode": "keyword",
      "all_terms": ["InP"],
      "any_terms": ["LNA", "low-noise amplifier"],
      "fields": ["title", "abstract", "keywords", "ieee_terms"],
      "query_family": "literal-circuit",
      "query_role": "standalone_lna",
      "top_k": 0
    }
  ]
}
```

Supported modes are `lite`, `keyword`, `filtered-lite`, and `pro`. Each query owns its own `all_terms`, `any_terms`, `exact_titles`, `dois`, `authors`, `fields`, `years`, `venues`, `top_k`, models, and fallback models. Do not put exact identity in a legacy comma/slash expression.

Use orthogonal query families rather than cosmetic rewrites. Cover the applicable dimensions:

- technology and process synonyms;
- target circuit and expanded name;
- receiver, readout IC, SoC, front-end, and IF-amplifier containers;
- application language;
- frequency aliases and containing/partial bands;
- cryogenic temperature terminology;
- architecture or mechanism;
- author, venue/year, and work-family identities discovered later.

The Cartesian product is unnecessary. Every declared scope value must appear in at least one query's `coverage`; inspect `run.uncovered_scope`.

## Screening decisions

Store scratch decisions in JSON, not in user deliverable folders:

```json
{
  "decisions": [
    {
      "title": "<exact title>",
      "year": 2025,
      "doi": "<doi>",
      "screening_decision": "include",
      "screening_reason": "Explicit measured cryogenic LNA with positive-width target-band overlap.",
      "record_type": "receiver_with_explicit_lna",
      "evidence_category": "measured",
      "evidence_matrix": {
        "technology": {"status": "pass", "evidence": "<source wording or field>"},
        "cryogenic": {"status": "pass", "evidence": "4 K"},
        "circuit": {"status": "pass", "evidence": "three-stage LNA"},
        "frequency": {"status": "pass", "evidence": "4-8 GHz LNA band"}
      },
      "lna_band_ghz": {"low": 4.0, "high": 8.0},
      "system_band_ghz": {"low": 5.0, "high": 7.0},
      "physical_temperature_k": 4.0
    }
  ]
}
```

Allowed working decisions are `include`, `exclude`, and `uncertain`. Require explicit evidence for technology, cryogenic operation, target circuit existence, and positive-width frequency overlap before final inclusion. A receiver title alone does not prove an LNA. Keep conference and journal publications separate.

For provenance, distinguish:

- `source_in_current_corpus`;
- `abstract_kind=source_abstract`;
- `abstract_kind=verified_primary_source_summary`;
- `doi_link`, `pdf_link`, and other source URLs.

Do not present a primary-source summary as a verbatim abstract.
