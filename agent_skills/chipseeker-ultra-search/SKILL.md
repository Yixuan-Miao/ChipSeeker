---
name: chipseeker-ultra-search
description: Plan and execute evidence-grounded, multi-pass literature discovery for an IC research idea using ChipSeeker's local agent CLI. Use when a user gives a broad technical research goal, asks for comprehensive related papers, feasibility assessment, design inspiration, or an Ultra Search workflow.
---

# ChipSeeker Ultra Search

Use this skill to turn a research idea into a bounded, auditable literature search. Run the local CLI from the ChipSeeker open-source repository. It prints machine-readable JSON to stdout and progress logs to stderr.

## Tool

Run:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py --mode lite --query "<query>" --top-k 60
```

Use `--mode pro` only for a small number of focused checks. It invokes the configured DeepSeek expansion/rerank workflow and can take about a minute. The coding agent remains responsible for research decisions.

Useful filters:

```powershell
--years 2020:2026
--venue JSSC --venue ISSCC
--must-have "SiGe/SiGe HBT, cryogenic"
--abstract-chars 2400
```

Do not parse console logs as results. Read the JSON object from stdout. Each result contains rank, similarity, title, abstract, authors, venue, year, DOI, PDF link, keywords, and any Pro-mode LLM relevance evidence.

## Workflow

1. Extract the user's fixed constraints, preferred targets, unknowns, and possible novelty claims. Treat every novelty claim as unverified.
2. Run one direct `pro` query for the complete goal, then run 4-8 `lite` queries over independent branches: process/device, circuit topology, frequency/noise/bandwidth, cryogenic or application system, and transferable neighboring domains.
3. Deduplicate by DOI, then normalized title. Keep a paper if it is directly relevant or has a specific transferable mechanism. Label it `direct`, `enabling`, `transferable`, `background`, or `contradictory`.
4. Read returned abstracts and identify missing evidence. Run at most two additional targeted rounds; do not keep expanding generic synonyms after the evidence stops changing.
5. Produce an evidence-backed report: literature map, paper list grouped by role, measured metrics, feasibility evidence, risks, and 2-4 design directions. Attach DOI/PDF links to every factual claim about a paper.

## Guardrails

- Never claim exhaustive coverage or experimental feasibility. State the corpus and search-round limits.
- Never invent a paper, metric, architecture, or citation. Mark an inference clearly and link it to the supporting papers.
- Keep the number of calls bounded. Start with 6-10 total calls and stop when successive rounds yield no new design mechanisms.
- Prefer Lite for breadth. Use Pro for precision, query wording review, or final reranking; do not let DeepSeek determine the overall research strategy.
- Preserve the search trace: query, filters, round, and reason each query was run.
