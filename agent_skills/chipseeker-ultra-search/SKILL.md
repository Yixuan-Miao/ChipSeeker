---
name: chipseeker-ultra-search
description: Use ChipSeeker to perform precise, high-recall literature searches and create only the folders and deliverables explicitly requested by the user. Use for literature censuses, idea validation, paper lists, technology comparisons, and persistent search workspaces.
---

# ChipSeeker Ultra Search

Use ChipSeeker as the literature engine. Follow the user's requested scope and output structure exactly. Do not generate generic research templates, idea reports, paper blueprints, status files, or extra Markdown unless the user explicitly asks for them.

Every literature task must execute fresh ChipSeeker searches for the current request. Do not claim that ChipSeeker was used when relying only on old output files, memory, general web search, or hand-written candidate lists. External publisher and author pages may verify metadata or a suspected corpus gap, but they do not replace the required ChipSeeker retrieval pass.

## Create A Workspace

For a new task, create only an empty timestamped folder:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_ultra_workspace.py create --direction "<direction>"
```

After creation, add only the folders and files named or clearly required by the user. Search scratch files should be temporary and must not remain in the final workspace unless the user requests raw results.

Do not create deliverable files before there are retained papers to write. If the first searches return no usable papers, broaden and reformulate the ChipSeeker queries instead of filling the workspace with empty placeholders or workflow documents.

## Search With ChipSeeker

Use `lite` for broad recall, synonym variants, technology variants, frequency variants, and long-tail discovery:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py --mode lite --query "<query>" --top-k 100 --abstract-chars 4000
```

Use several independent `lite` queries rather than trusting one ranking. Use `pro` only for a focused ambiguous set, difficult terminology expansion, or reranking where the LLM adds value:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py --mode pro --query "<focused query>" --top-k 30 --rerank-limit 30
```

The coding agent owns inclusion decisions. Never accept or reject a paper solely because Lite similarity or Pro reranking is high or low.

## Precision And Recall Protocol

Before searching, convert the request into explicit inclusion and exclusion rules. For every retained paper, verify all required dimensions from its title and abstract:

1. Correct technology or device family.
2. Explicit cryogenic or low-temperature operation/characterization.
3. The requested circuit type is the primary circuit or a clearly characterized block.
4. The reported frequency band satisfies the user's definition.

Deduplicate by DOI, then normalized title. Treat a conference paper and an extended journal paper as separate publications but link them as the same work family when appropriate.

Run a reverse audit after the first candidate set:

- Search exact titles, acronyms, process names, neighboring frequency descriptions, and application terms.
- Inspect lower-ranked exact matches, not only top results.
- Search for known work families and later journal extensions.
- Inspect benchmark tables and reference lists in the newest retained papers, then search every in-scope cited work by exact title or DOI.
- For every known exact title, query its exact title, DOI, first author, and work-family terms before declaring it absent.
- If an authoritative publication is verified but is absent from the local ChipSeeker corpus, retain it only when it is inside the user's scope and label it `corpus_gap`. Never hide a corpus gap or silently call the search complete.
- Record exclusions only when the user requests an audit; otherwise keep them out of the deliverable.

For a frequency census, label each retained paper precisely:

- `exact_or_full_cover`: covers the requested band or essentially the full band.
- `partial_overlap`: overlaps only part of the requested band.
- `superset`: a wider band contains the requested band.

Do not silently reinterpret "4-8 GHz" as only exact 4-8 GHz when the user asks for all relevant work; preserve these labels so scope remains explicit.

## Deliverables

Write user-facing reports in Chinese by default while preserving original English paper titles and technical terms. A machine-readable paper record should normally include:

- title
- authors
- year
- venue
- DOI
- direct PDF/publisher URL from `pdf_link`
- abstract
- technology/process
- physical temperature
- frequency range
- gain
- `NF/Te`
- power
- evidence category
- source queries or verification note when requested

Do not report completion until every requested folder exists, every requested output file is populated, links are present, JSON parses successfully, duplicates are resolved, and a final spot-check confirms that no obvious false positives remain.

Completion means the requested paper list has been produced, not that a fixed workflow has been executed. Keep searching with new ChipSeeker queries while unresolved technology, frequency, author-family, venue, or year gaps remain. Do not create `00_PROJECT_BRIEF.md`, query logs, progress diaries, idea canvases, or any other generic files unless the user explicitly requested them.

Before finishing, state which ChipSeeker modes were actually run and summarize the retained-paper count per requested category. A zero-paper category is incomplete unless exhaustive ChipSeeker reformulation still finds nothing and the user is explicitly told that no in-scope corpus hit was found.

## Research Boundary

When the user asks to validate their idea, search and evaluate evidence around that idea. Do not replace it with unsolicited idea generation. Offer alternative ideas only when explicitly requested.
