---
name: chipseeker-ultra-search
description: Use ChipSeeker for precise, high-recall IC literature censuses, idea validation, technology comparisons, automatic work-family closure, prior-run regression, and persistent paper-search workspaces. Execute fresh local searches, preserve evidence and links, and create only deliverables explicitly requested by the user.
---

# ChipSeeker Ultra Search

Use `F:\Papers_Embedding\SearchPaperByEmbedding-main` as the literature engine. Follow the requested scope and output structure exactly. Do not create generic briefs, query diaries, idea canvases, paper blueprints, or empty Markdown placeholders.

Every task must execute fresh ChipSeeker queries. Memory, old result files, and web search do not count as running ChipSeeker. Write user-facing reports in Chinese by default while preserving English titles and technical terms.

## Workspace

For a new persistent task, create only the timestamped root:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_ultra_workspace.py create --direction "<direction>"
```

Add only folders and files required by the requested deliverable. Keep query plans, checkpoints, raw unions, decisions, and audits in a temporary or ignored scratch location unless the user requests them. Do not write deliverables before papers are retained.

## Required Loop

Run this loop until the evidence closes; it is not a fixed-round checklist:

1. declare scope dimensions and orthogonal query families in a structured query spec;
2. retrieve a broad title-first union, including a separate receiver/SoC container branch;
3. deduplicate publications and remove only obvious title-level false positives;
4. hydrate every survivor from the candidate JSON;
5. record `include`, `exclude`, or `uncertain` against an evidence matrix;
6. expand work families for every retained paper until no likely new member appears;
7. rerun newly revealed author, process, application, venue/year, or terminology queries;
8. calculate saturation from new retained work families, not raw candidates;
9. inspect corpus freshness, perform a targeted web gap audit, and compare any prior run;
10. write only the requested deliverables after regressions and unresolved evidence are reviewed.

Read [references/query-spec.md](references/query-spec.md) when creating query specs or screening decisions.

## Retrieval

### Structured parallel plan

Prefer a per-query JSON plan for census work:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_collect.py `
  --query-spec "$env:TEMP\chipseeker_queries.json" `
  --checkpoint-dir "$env:TEMP\chipseeker_checkpoints" `
  --output "$env:TEMP\chipseeker_union.json" | Out-Null
```

The collector loads the corpus once, batches compatible Lite searches, checkpoints every query, preserves partial success, and reports timings, roles, coverage, and failures.

Cover materially different families when applicable:

- direct specification and standalone target circuit;
- receiver, readout IC, SoC, low-noise front-end, mixer, and IF-amplifier containers;
- technology, process, and device variants;
- acronym and expanded terminology;
- application language;
- frequency aliases, containing bands, and positive-width partial bands;
- architecture or mechanism;
- author, venue/year, identity, and work-family clues discovered later.

Do not generate cosmetic rewrites or a full Cartesian product. Declare technology, circuit, temperature, frequency, container, and application scope values; map query `coverage`; require `run.uncovered_scope` to be empty.

### Structured literal search

Use structured selectors for exact identity and hard constraints. Never encode a DOI or exact title in slash-delimited syntax.

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py `
  --mode keyword --all-term InP `
  --any-term LNA --any-term "low-noise amplifier" `
  --fields title,abstract,keywords,ieee_terms --top-k 0 `
  --abstract-chars 0 --result-view titles

& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py --mode keyword --author "J. Grahn" --fields authors --top-k 0
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py --mode keyword --exact-title "<title>" --top-k 0
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py --mode keyword --doi "<doi>" --top-k 0
```

Repeated `--all-term` is AND. Repeated `--any-term` is one OR group. Repeated title, DOI, or author selectors are identity alternatives. Unicode normalization handles common diacritics and unit symbols.

### Semantic-first and filtered Lite

Use semantic-first Lite by default. It avoids excluding papers whose metadata omit a literal term.

Use `filtered-lite` when a mandatory literal constraint is selective, or a relevant paper may sit outside the global semantic top 2000:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py `
  --mode filtered-lite --query "cryogenic amplifier for qubit readout" `
  --all-term InP --any-term LNA --any-term "low-noise amplifier" `
  --top-k 200 --abstract-chars 0 --result-view titles
```

### Pro

Use Pro only after a candidate pool exists, for terminology expansion, ambiguity resolution, or focused reranking. Never use Pro as the only census pass; the coding agent owns inclusion decisions.

The CLI tries the selected model and then `deepseek-v4-flash` by default. Fallback reranking is capped at 25 candidates. Inspect `pro_attempts`. A Pro failure must not discard successful Lite or Keyword results.

## Recall Funnel

### Build a broad union

Use high Lite `top-k` and tolerate temporary false positives. For frequency ranges, retain full-band, containing-band, and positive-width partial-overlap papers. Keep adjacent-band work only when the mechanism is useful and label it.

Always run a container-paper branch. Classify candidates as:

- `standalone_lna`;
- `receiver_with_explicit_lna`;
- `device_or_process_lna_vehicle`;
- `receiver_without_separable_lna`.

A receiver or system paper remains only when the target circuit is explicitly described or characterized. Label useful low-noise front ends that are not standalone LNAs. A receiver title alone does not prove an LNA.

### Deduplicate publications

Merge matching DOI records. A DOI-missing record may merge with the same normalized title and year. Never merge two different nonempty DOIs merely because titles match.

Conference, journal, and follow-up publications remain separate records linked by `work_family_id`. Use `retrieval_family_count`, not raw retrieval count, as stronger independent evidence.

### Title triage and hydration

Start with `--abstract-chars 0 --result-view titles`. Remove only obvious false positives. Keep uncertain titles when technology, temperature, band, or block details may exist only in the abstract.

Hydrate survivors in one local-corpus pass:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_hydrate.py `
  --input "$env:TEMP\chipseeker_union.json" `
  --abstract-chars 10000 `
  --output "$env:TEMP\chipseeker_hydrated.json" | Out-Null
```

The hydrator preserves retrieval evidence, refuses ambiguous identities, and reports unresolved records.

### Evidence screening

Require separate evidence for:

- technology/process;
- cryogenic operation or physical temperature;
- existence of the target circuit;
- positive-width target-band overlap.

Record LNA and system bands separately. Endpoint contact is not overlap. Distinguish measured, simulation-only, device-only, and unverified-model evidence. When no tighter temperature ceiling was requested, bucket results as `<=4.2K`, `4.2-20K`, `20-77K`, and `77-120K` instead of silently mixing them.

Keep decisions in scratch JSON and rerun the collector with `--screening-decisions`. Only `saturation.basis=retained_work_families` is suitable for stopping; raw-candidate saturation is provisional.

### Work-family closure

Run family expansion for every retained paper:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_expand_families.py `
  --input "$env:TEMP\retained.json" `
  --semantic-top-k 100 --abstract-chars 4000 `
  --output "$env:TEMP\work_family_closure.json" | Out-Null
```

The command batches semantic title neighbors, reverses every full author, follows newly confirmed members, and stops at convergence. It confirms `publication_variant` and `likely_extension`; inspect every `related_suggestion` manually. Search distinctive process/device phrases and plausible cited titles or DOIs from strong benchmark papers.

## Stopping Rule

Do not stop after a fixed number of rounds. Continue while a materially different semantic, literal, author, process, application, container, venue/year, or work-family audit adds retained papers.

Before stopping:

- attach screening decisions and inspect `new_retained_count` and `new_retained_family_count`;
- require late distinct query families to add no retained work families;
- require all declared scope values to be covered;
- require family closure and related-suggestion review;
- resolve suspicious category, year, venue, technology, temperature, and band gaps;
- stop issuing cosmetic rewrites after retained-family saturation.

A zero-paper category is incomplete until expanded Lite, structured Keyword, container, and work-family searches still find nothing.

## Audit And Web Gaps

Audit evidence, frequency overlap, source provenance, corpus year/venue coverage, and any prior run:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_audit.py `
  --input "$env:TEMP\retained.json" `
  --prior "<prior PAPERS.json>" `
  --target-band 4:8 `
  --output "$env:TEMP\evidence_audit.json" | Out-Null
```

Review every removed prior publication. Report retained, added, removed, prior retention rate, local-corpus recall where measurable, family additions, and external corpus-gap additions.

After local saturation, browse only likely gaps:

- recent arXiv or preprints;
- Nature-family or nonstandard venues;
- papers newer than the local venue/year coverage;
- a suspected title, author, DOI, or work family.

Prefer publisher, DOI, arXiv, conference, institutional, or author pages. Do not repeat a broad web census of venues already covered locally. Label verified external-only records `corpus_gap`. For preprints, check technical plausibility, publication status, measured versus simulated evidence, cryogenic model credibility, and internal consistency; label uncertainty instead of trusting title similarity.

## Deliverables

Never invent metadata or links. Keep separate `doi_link`, `pdf_link`, and other source URLs. Distinguish `abstract_kind=source_abstract` from `verified_primary_source_summary`; never present a summary as a verbatim abstract.

A machine-readable record should include title, authors, year, venue, DOI, source links, abstract provenance, technology/process, physical temperature, structured LNA/system bands, key metrics, record type, evidence matrix, work-family links, and source queries when requested.

Before completion:

- verify requested folders/files exist and contain retained papers;
- parse JSON outputs;
- require every included paper to pass all mandatory evidence axes or carry an explicit documented exception;
- resolve publication duplicates without collapsing work-family variants;
- spot-check false positives, technical credibility, and links;
- report modes, query families and roles, failures/fallbacks, raw/deduplicated/retained counts, family closure, prior regression, and corpus gaps.

When validating a user's idea, search evidence around that idea. Do not replace it with unsolicited idea generation unless asked.
