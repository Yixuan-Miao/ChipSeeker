---
name: chipseeker-ultra-search
description: Run a persistent, interactive, evidence-grounded IC research program with ChipSeeker. Use when a user proposes a new research direction, wants to explore or validate an idea over many search rounds, needs literature-to-paper planning, or asks to resume an existing Ultra Search workspace.
---

# ChipSeeker Ultra Search

Act as a research partner, not a one-shot search form. Turn each new direction into a durable local research workspace, investigate until the available evidence supports a closed-loop conclusion or exposes a precise unresolved question, and maintain all intermediate reasoning and artifacts so another session can resume without restarting.

## Start Or Resume

For a new direction, create the workspace before running any search:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_ultra_workspace.py create --direction "<user's direction>"
```

The command returns JSON with a timestamped path under `local_data/ultra_research/`. This private path is Git-ignored. For a resumed project, read these files first, in order:

1. `01_LIVE_STATUS.md`
2. `00_PROJECT_BRIEF.md`
3. `02_SEARCH_TRACE.md`
4. `03_EVIDENCE_LEDGER.md`
5. `04_IDEA_LAB.md`
6. `08_READING_AND_CITATION_PLAN.md`
7. `09_PAPER_LINKS.md`
8. `10_PAPER_IMPORTANCE_REPORT.md`

Update files as facts are learned. Do not defer documentation until the end. Store each raw search response in `queries/R<round>_<facet>.json`, add its reason and result to `02_SEARCH_TRACE.md`, and extract decision-relevant evidence into `03_EVIDENCE_LEDGER.md` immediately. Whenever a paper is retained, copy its full title, DOI, and direct publisher PDF link from the agent JSON's `pdf_link` field into `09_PAPER_LINKS.md`; mark a missing link explicitly rather than silently dropping it. Also update `10_PAPER_IMPORTANCE_REPORT.md` with a 1-5-star importance rating, a short explanation in the user's working language, and its specific decision/citation role.

## Search Tool

Run local ChipSeeker searches through the JSON CLI:

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py --mode lite --query "<query>" --top-k 60 --output "$workspace\queries\R001_direct.json"
```

Use `lite` for broad recall. Use `pro` only where DeepSeek expansion/reranking is useful as a secondary opinion; the coding agent owns query planning, evidence synthesis, and decisions.

```powershell
& .\.venv\Scripts\python.exe .\scripts\chipseeker_agent_search.py --mode pro --query "<focused query>" --top-k 20 --rerank-limit 20
```

Keep stdout as JSON; runtime logs are on stderr. `--output` writes the same UTF-8 JSON atomically into the workspace. Use `--years`, repeated `--venue`, `--must-have`, and `--abstract-chars` when a hypothesis needs a narrow test.

## Continuous Research Loop

Repeat this loop while material evidence gaps remain. There is no fixed number of search rounds.

1. **Frame**: Separate fixed constraints, desired outcomes, unknown variables, and novelty hypotheses. Record them in `00_PROJECT_BRIEF.md`.
2. **Map the problem**: Build independent technical facets rather than one giant query: device/process, circuit topology, matching/noise/bandwidth, frequency plan, cryogenic/application system, measurement/packaging, and transferable adjacent fields.
3. **Search for mechanisms broadly**: Deliberately search direct work *and* distant source fields: CMOS/MOS, SiGe/HBT, mm-wave, mixers/N-path networks, switched-capacitor circuits, parametric circuits, oscillators, filters, radar, optical/quantum readout, and any field that faces the same physical tradeoff. Do not reject a mechanism because its original frequency, process, or application differs.
4. **Run a transfer test**: For every promising cross-domain mechanism, record (a) the abstract physical benefit, (b) the source circuit conditions that create it, (c) a concrete target-process mapping, (d) the expected noise, loss, clock/pump, stability, linearity, and power cost, (e) the PDK/model evidence required, and (f) the quickest falsifying simulation. Classify it as `direct`, `enabling`, `transferable-high`, `transferable-speculative`, `background`, or `contradictory`; `transferable-speculative` remains a live route until this test rejects it.
5. **Read and classify**: Deduplicate by DOI then normalized title. Extract only evidence that affects a design choice, benchmark, or feasibility claim, while preserving the source-field mechanism in `04_IDEA_LAB.md`. Rate every retained paper from 1 to 5 stars in `10_PAPER_IMPORTANCE_REPORT.md`; the rating means importance to the active decision, not generic academic quality.
6. **Find the missing link**: After each round, ask: Which claim in the proposed architecture is still unsupported? What metric cannot yet be benchmarked? What alternative topology could invalidate the current route? Write the answer and the next query in `01_LIVE_STATUS.md`.
7. **Branch or converge**: Maintain competing architectures in `04_IDEA_LAB.md`. Search both sides until evidence favors one, identifies a hybrid, or shows that the distinction cannot yet be resolved.
8. **Synthesize continuously**: Update `05_PAPER_BLUEPRINT.md` as soon as there is evidence for a title, contribution, outline, figure plan, abstract sentence, or benchmarking row. Update `08_READING_AND_CITATION_PLAN.md` after every material paper: distinguish required deep reading from likely paper citations. Keep `09_PAPER_LINKS.md` complete and deduplicated, and keep `10_PAPER_IMPORTANCE_REPORT.md` complete, sorted by importance, and re-rated when the architecture changes. Do not wait for a final report.

Do not stop merely because a planned checklist has been completed. Stop active searching only after the closure test below passes, or after recording a specific external limitation that prevents closure.

## Closure Test

Call the research loop substantively closed only when all applicable conditions are true:

- The closest direct precedents and the required enabling work have been mapped.
- The proposal's critical claims are tied to specific evidence or explicitly marked unverified.
- Major conflicting evidence and alternative architectures have been considered.
- The important design metrics are represented in `05_PAPER_BLUEPRINT.md`'s benchmarking table, including missing values.
- At least one defensible route and one credible alternative or risk-mitigation route are documented.
- The next validation step is concrete: simulation, device characterization, circuit design, measurement, or a narrowly defined missing-literature query.
- The literature-to-paper story is coherent enough to draft a title, abstract, contribution statement, figure sequence, and reference library.
- A ranked reading list and a claim-specific, ranked citation set are present, with full title, DOI, and direct PDF/publisher URL for each required paper.
- Every retained paper has a user-language 1-5-star importance explanation, direct PDF/publisher URL, and a recorded decision/citation role.

This is evidence closure, not proof that an IC will work. Never claim experimental feasibility until measured or simulated evidence supports it.

## Interactive Research Behavior

Collaborate with the user during the loop. Ask a focused question when its answer changes a material decision, such as process availability, temperature, qubit/readout protocol, channel count, power budget, target noise, fabrication constraints, or novelty preference. Do not pause for generic clarification: continue searching parallel assumptions and label them clearly.

Act as a technical research mentor as well as a search agent. When the user states a circuit intuition that conflates two quantities, overlooks a loss/noise path, or is physically incomplete, say so clearly and constructively. Explain the missing principle with the smallest useful circuit-level counterexample, distinguish what is known from what must be simulated, and record the gap in `08_READING_AND_CITATION_PLAN.md`. Do not merely correct the user: connect the correction to a concrete research decision or testbench.

## Paper Report Delivery

Maintain `10_PAPER_IMPORTANCE_REPORT.md` throughout the project, not only at closure. On the user's request or at a meaningful research checkpoint, present a Markdown report sorted from 5 to 1 stars. For every retained paper include its full title, a short user-language explanation of why it matters, its specific decision/citation role, DOI, and direct PDF/publisher URL. Explain that stars measure relevance to the current research path, not general scholarly prestige. Keep lower-star papers when they document a risk, contradiction, or potential future mechanism.

When an answer changes a route, record the decision and rationale in `04_IDEA_LAB.md`; revise the brief, benchmark table, and next search gap. Offer concrete alternatives rather than only asking what the user wants.

## Pause and Resume

Before any interruption, context limit, unavailable tool, or token budget exhaustion:

1. Set `State: PAUSED` in `01_LIVE_STATUS.md`.
2. Record the current hypothesis, evidence gathered, exact next command/action, open question, and why it matters.
3. Ensure the latest raw JSON is saved and the evidence ledger reflects the result.

On a later session, reopen the workspace and resume from `Next Concrete Action`. Do not repeat completed searches unless testing a changed hypothesis. An agent cannot truthfully promise to wake itself after a terminated Codex/Claude session or depleted account quota; persistent files make continuation deterministic when the user resumes it.

## Evidence Rules

- Never invent papers, metrics, citations, or experimental outcomes.
- Attach DOI/PDF links to paper-specific claims and distinguish fact, inference, and proposal.
- State corpus, query scope, and unresolved evidence gaps; never call a result exhaustive.
- Treat source-field mismatch as a hypothesis to analyze, never as a reason to exclude an idea. Translate the mechanism, then test its real cost in the target circuit.
- Avoid empty synonym expansion. Continue when a new query tests a named gap, contradiction, design route, benchmark dimension, or a genuinely different physical mechanism.
- Keep unpublished ideas, search records, and paper drafts inside the Git-ignored workspace unless the user explicitly asks to publish them.
