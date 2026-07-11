"""Persistent local workspaces for long-running Ultra Search research."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


WORKSPACE_FILES = (
    "00_PROJECT_BRIEF.md",
    "01_LIVE_STATUS.md",
    "02_SEARCH_TRACE.md",
    "03_EVIDENCE_LEDGER.md",
    "04_IDEA_LAB.md",
    "05_PAPER_BLUEPRINT.md",
    "06_REFERENCE_LIBRARY.md",
)


def safe_direction_name(direction):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(direction or "").strip())
    text = re.sub(r"\s+", "_", text).strip(" ._")
    text = re.sub(r"_+", "_", text)
    return (text or "untitled_direction")[:72]


def workspace_templates(direction, created_at):
    timestamp = created_at.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "00_PROJECT_BRIEF.md": f"""# Research Brief

> Created: {timestamp}
> Workspace: persistent Ultra Search research record

## Original Direction

{direction}

## Fixed Constraints

- [Record confirmed process, frequency, temperature, power, area, architecture, or application constraints.]

## Unknowns and Novelty Hypotheses

- [Record each unverified claim as a hypothesis, not a conclusion.]

## Research Objective

- Build an evidence-backed literature map, decide which design routes are defensible, and prepare a paper-ready research blueprint.
""",
        "01_LIVE_STATUS.md": f"""# Live Status

> Updated: {timestamp}
> State: ACTIVE

## Current Working Hypothesis

- [Write the best current technical hypothesis and its supporting evidence.]

## Evidence Gaps That Must Be Closed

- [ ] Direct precedent or nearest analogue identified.
- [ ] Enabling circuit/process evidence identified.
- [ ] Key metrics mapped into a comparable benchmark.
- [ ] Contradictory evidence evaluated.
- [ ] At least two plausible design routes compared.

## Next Concrete Action

- [Run the next named query or read the next evidence set.]

## Questions for the Researcher

- [Ask only questions whose answer changes the search or design decision.]

## Resume Protocol

Read this file, `02_SEARCH_TRACE.md`, and `03_EVIDENCE_LEDGER.md` before continuing. If a session or token budget ends, set State to `PAUSED`, record the exact next action here, and resume from that action rather than restarting.
""",
        "02_SEARCH_TRACE.md": """# Search Trace

Record every search before and after it runs.

| Round | Query | Mode | Why This Query | New Mechanism/Evidence | Result File | Next Gap |
| --- | --- | --- | --- | --- | --- | --- |
""",
        "03_EVIDENCE_LEDGER.md": """# Evidence Ledger

Every factual claim must link to one or more papers. Classify a paper by its role, not only its similarity score.

| Paper | DOI / PDF | Role | Evidence Extracted | Metrics | Supports / Challenges | Confidence |
| --- | --- | --- | --- | --- | --- | --- |
""",
        "04_IDEA_LAB.md": """# Idea Lab

Keep competing ideas alive until evidence rules them out.

## Candidate Routes

### Route A

- Mechanism:
- Why it may work:
- Main risk:
- Evidence:

### Route B

- Mechanism:
- Why it may work:
- Main risk:
- Evidence:

## Decisions and Rejected Paths

- Record why a route was selected, deferred, or rejected.
""",
        "05_PAPER_BLUEPRINT.md": """# Paper Blueprint

Treat all text as a living draft until supported by evidence.

## Title Candidates

- [Draft after the contribution is defensible.]

## One-Sentence Contribution

- [Architecture + key mechanism + validated advantage.]

## Abstract Draft

- [Problem, gap, proposed approach, evidence-backed expected contribution, and validation plan.]

## Storyline and Figures

1. Problem and literature gap
2. Architecture and design rationale
3. Circuit/process implementation
4. Measurement/simulation plan and benchmarking
5. Limits and future work

## Benchmarking Table

| Work | Process | Temperature | Frequency | Channels | Gain | NF / Tnoise | BW | Power | Transferable Lesson |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
""",
        "06_REFERENCE_LIBRARY.md": """# Reference Library

Maintain a deduplicated working bibliography with a short note on why each paper matters.

| Citation Key | Title | Year | Venue | DOI / PDF | Role | Notes |
| --- | --- | --- | --- | --- | --- | --- |
""",
    }


def create_workspace(direction, root, created_at=None):
    created_at = created_at or datetime.now()
    root = Path(root)
    folder_name = f"{created_at.strftime('%Y%m%d_%H%M%S')}_{safe_direction_name(direction)}"
    workspace = root / folder_name
    suffix = 2
    while workspace.exists():
        workspace = root / f"{folder_name}_{suffix}"
        suffix += 1
    workspace.mkdir(parents=True)
    (workspace / "queries").mkdir()
    for filename, content in workspace_templates(direction, created_at).items():
        (workspace / filename).write_text(content, encoding="utf-8")
    return workspace


def workspace_status(workspace):
    workspace = Path(workspace)
    return {
        "workspace": str(workspace.resolve()),
        "exists": workspace.is_dir(),
        "required_files": {filename: (workspace / filename).is_file() for filename in WORKSPACE_FILES},
        "queries_dir": str((workspace / "queries").resolve()),
    }
