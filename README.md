# ChipSeeker / SearchPaperByEmbedding

ChipSeeker is a local paper search tool for chip, circuit, RF, mixed-signal, quantum hardware, and related topics.

## What It Does

- Streamlit UI for paper search and review
- Local or API-based embedding search
- Auto-sync from compatible CSV files into a local JSON database
- Versioned `local_data` schema with automatic migrations
- Hybrid filtering by year, venue, and exact-match keywords
- Conflict review page for dedupe edge cases before import collapses them
- LLM keyword generation, single-paper analysis, and global review generation
- Export selected papers to NotebookLM markdown, CSV, and BibTeX
- Background embedding build and background PDF download queue
- Built-in `Nature_Grabber.py` for Nature / Nature Electronics metadata collection
- Venue rules stored in `chipseeker/data/venue_rules.json`

## Repo Layout

- `app.py`: main Streamlit app
- `chipseeker/app_main.py`: Streamlit UI entry implementation
- `chipseeker/data_sync.py`: CSV sync, deduplication, source manifest, source organization
- `chipseeker/conflict_review.py`: source-record conflict detection and review helpers
- `chipseeker/search_ui.py`: hybrid filtering, highlight, ranking helpers
- `chipseeker/exports.py`: NotebookLM / CSV / BibTeX export helpers
- `chipseeker/maintenance.py`: purge and cache maintenance helpers
- `chipseeker/migrations.py`: local data schema versioning and migrations
- `chipseeker/task_queue.py`: background task queue for embedding and PDF downloads
- `chipseeker/data/venue_rules.json`: editable venue rules and color metadata
- `search_runtime.py`: active embedding search runtime
- `search.py`: compatibility shim
- `Nature_Grabber.py`: Nature metadata collector
- `scripts/setup.ps1`: Windows setup
- `scripts/setup.sh`: macOS / Linux setup
- `config.example.json`: public config template
- `config.local.json`: local private config, do not commit
- `local_data/`: runtime data directory, ignored by git

## local_data Layout

- `local_data/sources/`: source CSV files scanned by the app
- `local_data/sources/manual/`: hand-collected and Nature-collected CSVs
- `local_data/sources/generated_exports/`: exported CSV batches
- `local_data/cache/`: embedding cache files
- `local_data/exports/`: NotebookLM markdown and future exports
- `local_data/downloads/`: downloaded PDFs
- `local_data/backups/`: purge backups
- `local_data/schema_state.json`: local schema version state
- `local_data/conflict_resolutions.json`: dismissed conflict review items
- `local_data/*.json`: local database and user state

## Quick Install

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

macOS / Linux:

```bash
bash ./scripts/setup.sh
```

## One-Line Agent Install

`codex`:

```bash
codex "Open this repo, run scripts/setup.ps1 on Windows or scripts/setup.sh on macOS/Linux, then tell me how to launch ChipSeeker."
```

`cc`:

```bash
cc "Open this repo, run scripts/setup.ps1 on Windows or scripts/setup.sh on macOS/Linux, then tell me how to launch ChipSeeker."
```

## Manual Install

```bash
pip install -r requirements.txt
playwright install chromium
```

Optional extras:

```bash
pip install -r requirements-dev.txt
pip install -r requirements-optional.txt
```

Or with project extras:

```bash
pip install .[dev]
```

## Config

1. Copy `config.example.json` to `config.local.json`
2. Fill the fields you need:
   - `embedding_model`
   - `emb_api_key`
   - `llm_api_key`
   - `llm_base_url`
   - `llm_model`

If you only want local embedding, set `embedding_model` to `all-MiniLM-L6-v2`.

## Run

```bash
streamlit run app.py
```

## Nature Grabber

CLI example:

```bash
python Nature_Grabber.py --query "cryogenic CMOS qubit readout" --journal nature-electronics --output nature_quantum.csv
```

If `--output` is a relative path, the CSV is written to `local_data/sources/manual/`.

The Streamlit sidebar also exposes Nature Grabber directly. The output CSV is app-compatible and will be picked up by the library sync.

## CSV Schema

The app scans compatible source CSV files recursively under `local_data/sources/`.
Root-level CSVs are automatically organized into `manual/` or `generated_exports/`, and a manifest is written to `local_data/source_manifest.json`.
The manifest is versioned, and startup migrations keep `local_data` compatible when the on-disk layout changes.

Required fields:

- `Document Title`
- `Abstract`
- `Authors`
- `Author Keywords`
- `Publication Year`
- `Publication Title`
- `DOI`
- `PDF Link`

When source CSV files change, the app automatically syncs the local paper database and rebuilds cache when needed.

## Review And Background Jobs

- `Conflict Review` in the sidebar exposes dedupe anomalies such as same title with different years, or same DOI with different abstracts.
- Missing embedding cache is built in a background task instead of blocking app startup.
- PDF batch download now runs as a background queue, so the UI stays usable while downloads continue.
- Venue matching is editable through `chipseeker/data/venue_rules.json`; updating the rules no longer requires touching Python code.

## Tests

```bash
pytest
```

## Open Source Notes

- Do not commit `config.local.json`
- Do not commit local CSV / JSON / NPY / PDF data
- Do not commit any real API key
- `.gitignore` is already set up to ignore `local_data/`
