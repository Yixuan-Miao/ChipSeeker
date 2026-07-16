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

Optimize the first phase for recall, not immediate proof. Start searching quickly with a fan-out of short queries instead of spending a long time designing one perfect query.

Use `lite` repeatedly for semantic variants:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py --mode lite --query "<query>" --top-k 200 --abstract-chars 0 --result-view titles
```

Use `keyword` to scan the full corpus without embeddings. Commas mean AND; slashes mean OR. Restrict fields when searching an author, exact title, or DOI:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py --mode keyword --query "InP,LNA/low-noise amplifier" --top-k 0 --abstract-chars 0 --result-view titles
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py --mode keyword --query "J. Grahn" --fields authors --top-k 0 --abstract-chars 0 --result-view titles
```

For the normal high-recall first pass, run several Lite and Keyword queries in one command and deduplicate them automatically:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_collect.py `
  --lite-query "cryogenic InP 4-8 GHz LNA" `
  --lite-query "cryogenic InP low-noise amplifier" `
  --lite-query "cryogenic C-band LNA qubit readout radio astronomy" `
  --keyword-query "InP,LNA/low-noise amplifier" `
  --keyword-query "cryogenic,InP,LNA/low-noise amplifier" `
  --lite-top-k 200 --keyword-top-k 0 --abstract-chars 0 --result-view titles `
  --output "$env:TEMP\chipseeker_candidate_union.json" | Out-Null
```

The collector deduplicates by DOI, then normalized title, and records every query that retrieved each paper. Save large unions to a temporary JSON file and inspect structured title fields rather than printing the whole result into model context. Use `pro` only after the candidate pool exists, for a focused ambiguous subset, terminology expansion, or reranking where the LLM adds value:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py --mode pro --query "<focused ambiguity>" --top-k 30 --rerank-limit 30
```

The coding agent owns inclusion decisions. Never accept or reject a paper solely because Lite similarity, Keyword rank, or Pro reranking is high or low.

## Precision And Recall Protocol

Use a recall-first funnel.

### 1. Separate hard constraints from useful relaxations

Identify what must be true and what may be broadened. For an LNA census, the final paper must contain an LNA as the primary circuit or as a separately described, useful block. A receiver, mixer, or readout-system paper may remain when its LNA is characterized or technically informative.

Treat frequency boundaries as relevance labels rather than brittle exclusions unless the user demands an exact band:

- retain full-band matches;
- retain wider bands containing the target;
- retain positive-width partial overlaps such as 4-6 GHz for a 4-8 GHz request;
- optionally retain a close adjacent band only when its mechanism is clearly useful, labeled `adjacent_useful`;
- exclude endpoint-only contact unless there is another concrete reason to retain it.

Technology, cryogenic operation, and the existence of a relevant LNA still require evidence. Do not infer them from similarity alone.

### 2. Build a large candidate union

Fan out across:

- the full direct phrase;
- technology + circuit without frequency;
- cryogenic circuit without technology, then exact-filter technology;
- acronyms and expanded names;
- application language such as qubit readout, radio astronomy, SIS IF, C-band, receiver, front end, and multiplexed readout;
- process names, device names, authors, venues, and years discovered during search.

Use high `top-k` values and tolerate false positives in this temporary pool. Missing a paper is more costly than admitting an extra candidate at this stage.

### 3. Deduplicate before reading

Union every search result, deduplicate by DOI and then normalized title, and preserve all retrieval sources. Link conference and journal variants as one work family without deleting either publication.

### 4. Triage titles first

Use `--abstract-chars 0`. Remove only titles that are obviously outside the requested circuit, technology, temperature regime, or useful frequency neighborhood. Keep uncertain titles. Never reject a candidate merely because the title omits temperature, process, frequency, or the LNA details that may appear in the abstract.

### 5. Read abstracts only for survivors and uncertain cases

Retrieve full abstracts by exact title or DOI. Join several uncertain titles or DOIs with `/` to hydrate them in one full-corpus scan:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py --mode keyword --query "<title 1>/<title 2>/<DOI 3>" --fields title,doi --top-k 0 --abstract-chars 4000 --result-view standard
```

Classify each survivor as `direct`, `superset`, `partial_overlap`, `adjacent_useful`, `receiver_with_lna`, `simulation_only`, or `exclude`. The final list may be broad, but every label must be accurate.

### 6. Reverse-audit work families

For every important cluster:

- hard-search the exact title and DOI;
- hard-search all authors, especially recurring first and last authors;
- search the process/device name and distinctive circuit phrase;
- find conference precursors, journal extensions, and later follow-up papers;
- inspect benchmark/reference tables in the newest strong papers and search every plausible cited work by exact title or DOI.

Use author search as a discovery tool, not merely metadata verification. A known author often reveals differently titled papers that semantic ranking misses.

### 7. Search to evidence saturation

Do not stop because a fixed number of rounds was completed. Continue until materially different semantic queries, exact technology/circuit queries, and author/work-family reverse audits stop adding new in-scope candidates. If a suspected paper is absent from the local corpus, verify it from an authoritative source and label it `corpus_gap`.

Record exclusions only when the user requests an audit; otherwise keep them out of the deliverable.

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

Before finishing, state which ChipSeeker modes and query families were actually run, the raw and deduplicated candidate counts when available, and the retained-paper count per requested category. A zero-paper category is incomplete unless expanded Lite, Keyword, and work-family searches still find nothing and the user is explicitly told that no in-scope corpus hit was found.

## Research Boundary

When the user asks to validate their idea, search and evaluate evidence around that idea. Do not replace it with unsolicited idea generation. Offer alternative ideas only when explicitly requested.
