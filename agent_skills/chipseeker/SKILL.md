---
name: chipseeker
description: Search the user's local ChipSeeker IC-paper corpus from any workspace and return evidence-grounded results. Use for IC, semiconductor, RF, analog, mixed-signal, AI-hardware, quantum-hardware, circuit-design paper lookup, surveys, comparisons, or reading lists.
---

# ChipSeeker / 芯寻

Use the local agent JSON interface at `F:\Papers_Embedding\SearchPaperByEmbedding-main`. Search in English technical terms and answer in Chinese unless requested otherwise.

## Ordinary Lookup

Use Lite:

```powershell
python "$HOME\.codex\skills\chipseeker\scripts\search.py" "<query>" --top-k 20
```

Use structured Keyword for literal full-corpus constraints:

```powershell
python "$HOME\.codex\skills\chipseeker\scripts\search.py" --mode keyword --all-term InP --all-term LNA --top-k 0 --abstract-chars 0 --result-view titles
python "$HOME\.codex\skills\chipseeker\scripts\search.py" --mode keyword --author "J. Grahn" --fields authors --top-k 0
python "$HOME\.codex\skills\chipseeker\scripts\search.py" --mode keyword --doi "<doi>" --top-k 0
```

Do not encode exact titles or DOIs in slash-delimited strings. Repeated `--all-term` means AND; repeated `--any-term` is one OR group; repeated title, DOI, or author selectors are alternatives.

Use `filtered-lite` only when a mandatory literal constraint should be applied to the full corpus before semantic ranking. Use Pro only for focused ambiguity or reranking. Pro automatically retries `deepseek-v4-flash` after the selected model fails.

## Survey

For a small survey, batch materially different Lite queries with the collector. For a census, use a structured query spec so each query owns its role, coverage, constraints, and limits:

```powershell
python "$HOME\.codex\skills\chipseeker\scripts\collect.py" `
  --query-spec "$env:TEMP\queries.json" `
  --checkpoint-dir "$env:TEMP\chipseeker_checkpoints" `
  --output "$env:TEMP\candidate_union.json" | Out-Null
```

Prefer recall in the title-first union. Search standalone circuit titles and receiver/readout IC/SoC containers separately. Hydrate survivors from the candidate file, then close work families for every retained paper:

```powershell
Set-Location F:\Papers_Embedding\SearchPaperByEmbedding-main
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_hydrate.py --input "$env:TEMP\candidate_union.json" --output "$env:TEMP\hydrated.json"
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_expand_families.py --input "$env:TEMP\retained.json" --output "$env:TEMP\families.json"
```

For a persistent census, evidence matrix, prior-run comparison, or corpus-gap audit, follow `chipseeker-ultra-search`.

## Output

Return rank, title, year, venue, relevance, DOI link, and PDF link when available. Distinguish source abstracts from verified summaries. Never invent metadata. Search results are leads; read selected primary papers before asserting technical conclusions.

Do not create files for an ordinary lookup. When persistence is requested, write only requested deliverables or raw output under the active project result folder.
