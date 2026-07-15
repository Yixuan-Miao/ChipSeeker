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
    "07_CIRCUIT_CANDIDATES.md",
    "08_READING_AND_CITATION_PLAN.md",
    "09_PAPER_LINKS.md",
    "10_PAPER_IMPORTANCE_REPORT.md",
    "11_IDEA_FEASIBILITY_REVIEW.md",
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
        "04_IDEA_LAB.md": """# 想法实验室 / Idea Lab

在证据明确排除某条路线之前，保留相互竞争的想法；说明它们的物理机制、迁移条件和判废标准。

## 候选路线 / Candidate Routes

### Route A

- 机制（Mechanism）：
- 为什么可能有效：
- 主要风险：
- 证据：

### Route B

- 机制（Mechanism）：
- 为什么可能有效：
- 主要风险：
- 证据：

## 决策与已排除路线 / Decisions and Rejected Paths

- 记录每条路线被选中、暂缓或排除的原因。
""",
        "05_PAPER_BLUEPRINT.md": """# 论文蓝图 / Paper Blueprint

在得到论文证据或仿真结果之前，所有贡献表述都只是动态草稿，不得写成既成结论。

## 题目候选 / Title Candidates

- [贡献能够被证据支持后再拟题。]

## 一句话贡献 / One-Sentence Contribution

- [Architecture + 核心 mechanism + 已验证 advantage。]

## 摘要草稿 / Abstract Draft

- [问题、研究空缺、方案、证据支持的预期贡献、验证计划。]

## 行文逻辑与图片 / Storyline and Figures

1. 问题与文献空缺
2. Architecture 与设计理由
3. 电路和 process 实现
4. Measurement/simulation 与 benchmarking
5. 局限和后续工作

## Benchmarking 表

| 工作 | Process | 温度 | 频率 | Channels | Gain | NF / Tnoise | BW | Power | 可迁移结论 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
""",
        "06_REFERENCE_LIBRARY.md": """# Reference Library

Maintain a deduplicated working bibliography with a short note on why each paper matters.

| Citation Key | Title | Year | Venue | DOI / PDF | Role | Notes |
| --- | --- | --- | --- | --- | --- | --- |
""",
        "07_CIRCUIT_CANDIDATES.md": """# 电路候选方案 / Circuit Candidates

把 transistor-level 候选方案与普通文献笔记分开。每个方案必须写清电路骨架、一阶机理、关键 noise/loss/stability 路径，以及最快的 falsifying simulation。

## Candidate A

- 电路骨架：
- 目标机制（Mechanism）：
- 目标 metric 与 comparison baseline：
- 关键假设：
- 最快判废仿真：

## Candidate B

- 电路骨架：
- 目标机制（Mechanism）：
- 目标 metric 与 comparison baseline：
- 关键假设：
- 最快判废仿真：
""",
        "08_READING_AND_CITATION_PLAN.md": """# 精读与引用计划 / Reading And Citation Plan

分开维护两个问题：为了正确设计必须精读什么，以及为了支撑论文 claim 必须引用什么。必须精读的论文不一定是核心 citation，反之亦然。

## 必须精读 / Must Read In Depth

| 优先级 | Citation Key / Title | 为什么精读 | 必须回答的具体问题 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | [添加论文] | [对所选路线至关重要的 circuit/device mechanism。] | [需要确认的 topology、equations、assumptions 和 limits。] | unread |

## 引用候选 / Citation Candidates

| Paper | 支撑的 claim | Citation role | 引用前必须确认 |
| --- | --- | --- | --- |
| [添加论文] | [具体事实或 novelty claim。] | direct / enabling / transferable / contradictory | [核对 abstract/full text/metric。] |

## 需要和研究者澄清的概念

- [记录理解偏差、知识缺口，以及设计决策前需要补足的最短物理解释。]

## 最终 Reference Set

- 将最终 references 从不可缺少到可选排序，保留完整 title、venue、year、DOI/PDF，以及它要支撑的具体 sentence/figure/claim。
""",
        "09_PAPER_LINKS.md": """# Direct Paper Links

For every paper that enters the evidence ledger, reading plan, or final citation set, record its stable DOI and the direct publisher PDF URL returned by ChipSeeker's `pdf_link` field. Do not use a search-result URL as a substitute. If the corpus has no PDF URL, record the canonical publisher/DOI URL and mark the gap.

| Citation Key | Title | DOI | Direct PDF / Publisher URL | Link Status |
| --- | --- | --- | --- | --- |
| [Add key] | [Full title] | [DOI] | [URL] | verified / canonical only / missing |
""",
        "10_PAPER_IMPORTANCE_REPORT.md": """# 论文重要性报告 / Paper Importance Report

每篇保留论文按 1-5 星评分。解释默认使用中文，论文原题、DOI、metric 和关键技术术语保留英文。星级表示它对当前研究决策的重要性，不代表论文的一般学术水平。

## 评分标准 / Rating Scale

- 5 星：不可缺少的 direct precedent、baseline 或 mechanism paper，必须精读且大概率引用。
- 4 星：会实质改变 architecture 或 validation plan 的强 enabling/transfer paper。
- 3 星：有用的 supporting、system 或 comparison paper，选择性精读和引用。
- 2 星：边缘但可能有用的 technique 或 benchmark。
- 1 星：保留的背景、contradictory evidence 或低概率 idea seed。

## 保留论文 / Retained Papers

| 星级 | Citation Key | Title | 为什么重要 | Decision / Citation Role | DOI | Direct PDF URL |
| --- | --- | --- | --- | --- | --- | --- |
| [1-5] | [key] | [full title] | [简短中文解释] | [direct / enabling / transferable / contradiction] | [DOI] | [URL] |

## 评分说明 / Rating Notes

- selected architecture 或约束变化后重新评分。不要直接删除低星论文，必须记录它被排除或替代的原因。
""",
        "11_IDEA_FEASIBILITY_REVIEW.md": """# Idea 可行性评估报告 / Idea Feasibility Review

把每个 architecture 的可行性评分与参考论文的重要性评分分开。评分用于辅助决策，不表示已经得到 simulation 或 measurement 结果。

## 评估规则 / Evaluation Rules

- 写清目标、comparison baseline 和 evidence level：paper evidence、analytical inference、pre-layout simulation、post-layout simulation 或 measurement。
- 分别给出 novelty、physical plausibility 和 deadline execution probability 的 1-5 分。
- 严格区分原始 input-referred `NF/Te` 改善与 integrated noise、gain、selectivity、average power 收益。
- 写清最快能排除该机制的 simulation；漂亮的 nominal schematic 不能单独构成证据。

## 候选方案评分 / Candidate Scorecard

| Candidate | Mechanism | Novelty | Physical plausibility | Deadline execution | 预期收益 | 主要判废条件 | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [A] | [mechanism] | [1-5] | [1-5] | [1-5] | [specific metric] | [simulation] | active / selected / deferred / rejected |

## 验证门槛 / Gate Results

| Gate | 要求 | 实际证据 | Pass / Fail / Pending | 对结论的影响 |
| --- | --- | --- | --- | --- |
| Device/model | [例如有效的 temperature/noise model] | [evidence] | pending | [允许提出的 claim] |
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
