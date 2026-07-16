---
name: chipseeker-ultra-search
description: Use ChipSeeker for precise, high-recall IC literature censuses, idea validation, technology comparisons, work-family expansion, and persistent paper-search workspaces. Execute fresh local searches, preserve evidence and links, and create only deliverables explicitly requested by the user.
---

# ChipSeeker Ultra Search

Use `F:\Papers_Embedding\SearchPaperByEmbedding-main` as the literature engine. Follow the requested scope and output structure exactly. Do not create generic briefs, query diaries, idea canvases, paper blueprints, or empty Markdown placeholders.

Every task must execute fresh ChipSeeker queries. Memory, old result files, and web search do not count as running ChipSeeker.

## Workspace

For a new persistent task, create only the timestamped root:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_ultra_workspace.py create --direction "<direction>"
```

Add only folders and files requested or required for the stated deliverable. Keep scratch JSON in a temporary location unless raw results were requested. Do not write deliverables until papers have been retained.

## Retrieval Strategy

Optimize candidate generation for recall, then recover precision through deduplication, title triage, abstract review, and work-family auditing.

### 1. Fan out semantic queries in one parallel pass

Use the collector for several short, materially different Lite queries. It loads the corpus once, executes remote query embeddings concurrently, and keeps local-model queries in one batch:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_collect.py `
  --lite-query "cryogenic InP 4-8 GHz LNA" `
  --lite-query "cryogenic InP low-noise amplifier" `
  --lite-query "C-band cryogenic receiver LNA qubit readout radio astronomy" `
  --lite-top-k 200 --abstract-chars 0 --result-view titles `
  --output "$env:TEMP\chipseeker_union.json" | Out-Null
```

Cover distinct query families when relevant:

- direct specification;
- broader technology + circuit;
- acronym and expanded terminology;
- device/process variants;
- application language;
- circuit mechanism or architecture;
- author, venue, and work-family clues discovered during search.

Do not generate many cosmetic rewrites. The collector reports `query_family_count`, per-search `new_unique_count`, and a `saturation` signal so repeated variants do not masquerade as independent evidence.

### 2. Use structured literal search

Use structured selectors for exact identity and hard constraints. Never encode a DOI or exact title inside slash-delimited query syntax.

```powershell
# AND constraints
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py `
  --mode keyword --all-term InP --all-term LNA `
  --fields title,abstract,keywords,ieee_terms --top-k 0 `
  --abstract-chars 0 --result-view titles

# OR synonyms
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py `
  --mode keyword --all-term InP `
  --any-term LNA --any-term "low-noise amplifier" `
  --top-k 0 --abstract-chars 0 --result-view titles

# Author, exact title, or DOI
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py --mode keyword --author "J. Grahn" --fields authors --top-k 0
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py --mode keyword --exact-title "<title>" --top-k 0
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py --mode keyword --doi "10.1109/TMTT.2025.1234567" --top-k 0
```

`--all-term` is repeated AND. `--any-term` is one OR group. Repeated `--exact-title` and `--doi` form an identity OR group. Repeated `--author` matches any listed author. Unicode normalization handles common diacritics and unit symbols such as `Rücker/Rucker` and `μW/uW`.

Legacy comma-AND/slash-OR expressions remain available for generic terms only.

### 3. Choose semantic-first or hard-prefiltered semantic search

Use semantic-first Lite by default. It is usually faster and avoids excluding a useful paper whose title or abstract omits one literal term.

Use `filtered-lite` when a literal constraint is truly mandatory and selective, or when a relevant paper may sit outside the global semantic top 2000:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py `
  --mode filtered-lite --query "cryogenic amplifier for qubit readout" `
  --all-term InP --any-term LNA --any-term "low-noise amplifier" `
  --top-k 200 --abstract-chars 0 --result-view titles
```

This scans the full corpus for the structured constraints, then performs semantic ranking only inside that subset. If the literal subset is huge or the constraint may be absent from metadata, keep semantic-first and filter after retrieval.

The collector can batch this mode with repeated `--filtered-lite-query` and one shared set of structured constraints.

### 4. Use Pro selectively

Use Pro after a candidate pool exists, for focused terminology expansion, ambiguity resolution, or reranking:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py `
  --mode pro --query "<focused ambiguity>" --top-k 30 --rerank-limit 30
```

Do not use Pro as the only census pass. The coding agent owns inclusion decisions.

## Recall Funnel

### Build a broad union

Use high Lite `top-k` values and tolerate temporary false positives. For frequency ranges, retain full-band, containing-band, and positive-width partial-overlap papers. Keep adjacent-band work only when the mechanism is useful and label it.

A receiver or system paper may remain when the target circuit is separately described or characterized. Technology, temperature, and circuit existence still require evidence.

### Deduplicate publications safely

The collector merges matching DOI records. It may merge a DOI-missing record with the same normalized title and year. It never merges two nonempty different DOIs merely because titles match.

Conference, journal, and follow-up publications remain separate records and receive `work_family_id` links. Use `retrieval_family_count` rather than raw `retrieval_count` as stronger evidence: five near-duplicate queries are not five independent confirmations.

### Triage titles before abstracts

Start with `--abstract-chars 0 --result-view titles`. Remove only obvious false positives. Keep uncertain titles when technology, temperature, band, or block-level details may appear only in the abstract.

Hydrate survivors with repeated structured identity selectors:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py `
  --mode keyword `
  --exact-title "<title 1>" --exact-title "<title 2>" `
  --doi "<doi 3>" `
  --top-k 0 --abstract-chars 4000 --result-view standard
```

Classify retained papers accurately, for example `direct`, `superset`, `partial_overlap`, `adjacent_useful`, `receiver_with_lna`, `simulation_only`, or `exclude`.

### Expand work families

For each important seed, use the formal family interface:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_expand_family.py `
  --doi "<seed DOI>" --semantic-top-k 200 --abstract-chars 2000
```

The command combines exact-title variants, author reverse search, and semantic neighbors. It labels `publication_variant`, `likely_extension`, and `related_followup` without deleting separate publications.

Also search distinctive process/device phrases and inspect reference or benchmark tables in strong recent papers. Search plausible cited works by structured exact title or DOI.

## Stopping Rule

Do not stop after a fixed number of rounds. Continue while a materially different semantic, literal, author, process, application, venue/year, or work-family audit adds in-scope papers.

Treat collector saturation as evidence, not an automatic decision:

- inspect every search's `new_unique_count`;
- inspect family-level new and deduplicated counts;
- require multiple materially different query families;
- require late author/work-family audits to add no important papers;
- resolve suspicious category, year, venue, or technology gaps.

Stop locally when additional distinct families produce no meaningful candidates and important work families are closed. Do not keep issuing cosmetic query rewrites after saturation.

## Web Gap Audit

The local corpus is the primary source and normally covers the relevant top journals and conferences. After local saturation, perform one light web audit only for likely corpus gaps:

- recent arXiv/preprints;
- Nature-family or other nonstandard venues;
- papers newer than the latest local update;
- a specific suspected title, author, or work family.

Prefer publisher, DOI, arXiv, conference, or author pages. Do not repeat a broad web census of venues already covered locally. Label verified external-only records `corpus_gap`.

## Deliverables

Write user-facing reports in Chinese by default while preserving English titles and technical terms. Never invent metadata or links. A machine-readable record should include title, authors, year, venue, DOI, `pdf_link`, abstract, technology/process, temperature, frequency, key metrics, evidence category, and source queries when requested.

Before completion:

- verify requested folders and files exist and contain retained papers;
- parse JSON outputs;
- resolve publication duplicates without collapsing work-family variants;
- spot-check false positives and links;
- report modes/query families run, raw count, deduplicated count, retained count per category, and any corpus gaps.

A zero-paper category is incomplete until expanded Lite, structured Keyword, and work-family searches still find nothing.

When validating a user's idea, search evidence around that idea. Do not replace it with unsolicited idea generation unless asked.
