# ChipSeeker / SearchPaperByEmbedding

## Quick Install

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

Or just double-click:

```bat
Install_ChipSeeker.bat
```

macOS / Linux:

```bash
bash ./scripts/setup.sh
```

What Quick Install now does:

- creates `.venv`
- upgrades `pip / setuptools / wheel`
- installs `requirements.txt`
- installs `requirements-optional.txt`
- installs `playwright` Chromium
- creates `config.local.json` if missing
- initializes the runtime folders under `local_data`

Quick launch on Windows after install:

- Double-click `Start_ChipSeeker.bat`
- Or create a desktop shortcut pointing to `Start_ChipSeeker.bat`

Bundled demo data:

- The repo now ships with `demo_data/export2026.03.04-08.56.26.csv`
- This is a `2026` `TMTT` demo CSV so new users can validate the app quickly
- In the app's `Quick Start`, click `Load Bundled TMTT 2026 Demo CSV` to import it into `local_data`

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
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install -r requirements-optional.txt
.\.venv\Scripts\python -m playwright install chromium
```

Windows one-click install / start:

```bat
Install_ChipSeeker.bat
Start_ChipSeeker.bat
```

Optional dev extras:

```bash
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
```

## Config

1. Copy `config.example.json` to `config.local.json`.
2. Fill the fields you need:
   - `embedding_model`
   - `emb_api_key`
   - `llm_api_key`
   - `llm_base_url`
   - `llm_model`
3. If you only want local embedding, set `embedding_model` to `all-MiniLM-L6-v2`.

## Run

```bash
streamlit run app.py
```

Windows double-click launch:

```bat
Start_ChipSeeker.bat
```

## Paid Database Delivery

Recommended delivery format:

- Do not zip the whole repo for buyers
- In the app sidebar, use `Content Pack -> Build Content Pack ZIP`
- Send the generated ZIP from `local_data/exports/content_packs/`

Why this is the best option:

- it includes the database JSON, source CSVs, cache files, registry, and state files
- it avoids shipping your whole code workspace
- the buyer can import it directly from `Quick Start` or the sidebar `Content Pack` panel

What to send if you build it manually:

- zip the `local_data/` folder only
- do not include `config.local.json`
- do not include any private API keys

Recommended update flow for buyers:

1. You rebuild a new content pack ZIP after updating your library
2. Name it with a clear version or date, for example `ChipSeeker_ContentPack_2026-04-18.zip`
3. Send the new ZIP to the buyer
4. The buyer opens ChipSeeker and imports the new ZIP from `Quick Start` or `Content Pack`

Short-term best practice:

- always send a full replacement content pack ZIP
- do not try to send patch files or partial folder replacements yet
- this is the safest and simplest workflow for non-technical users

## Nature Grabber

CLI example:

```bash
python Nature_Grabber.py --query "cryogenic CMOS qubit readout" --journal nature-electronics --output nature_quantum.csv
```

Incremental example:

```bash
python Nature_Grabber.py --query "cryogenic CMOS qubit readout" --start-date 2026-04-01 --output nature_quantum_incremental.csv
```

If `--output` is a relative path, the CSV is written to `local_data/sources/manual/`.

## Update Manager

- `IEEE Incremental`: ChipSeeker tracks each venue watermark, opens the venue page for your manual CSV export, and advances the watermark after you upload the exported batch.
- `Nature Incremental`: ChipSeeker tracks each query's last checked date and runs incremental pulls in the background.
- `arXiv Incremental`: ChipSeeker tracks AI hardware / quantum hardware preprint queries and incrementally collects compatible CSVs in the background.
- `Conflict Review`: surfaces dedupe anomalies such as same title with different years, or same DOI with different abstracts before they silently collapse into one record.
- `Embedding Coverage Builder`: lets you start with `2026` or a custom year slice, then queue additional year ranges in the background instead of blocking on all 30k+ papers at once.
- `Quick Start`: first-run onboarding that defaults to bundled local MiniLM search, treats cloud APIs as optional, and lets users import a bundled demo CSV or a paid content pack ZIP.

## Repo Layout

- `app.py`: main Streamlit entry
- `Install_ChipSeeker.bat`: Windows double-click installer
- `Start_ChipSeeker.bat`: Windows double-click launcher
- `chipseeker/app_main.py`: Streamlit UI entry implementation
- `chipseeker/content_pack.py`: content pack build/install helpers plus bundled demo CSV install
- `chipseeker/data_sync.py`: CSV sync, deduplication, source manifest, source organization
- `chipseeker/conflict_review.py`: source-record conflict detection and review helpers
- `chipseeker/migrations.py`: local data schema versioning and migrations
- `chipseeker/task_queue.py`: background task queue for embedding, PDF, and Nature incremental jobs
- `chipseeker/update_manager.py`: source registry, update watermarks, IEEE batches, and Nature incremental helpers
- `chipseeker/data/venue_rules.json`: editable venue rules and color metadata
- `chipseeker/data/source_registry_template.json`: default IEEE / Nature update source template
- `search_runtime.py`: active embedding search runtime
- `search.py`: compatibility shim
- `Nature_Grabber.py`: Nature metadata collector
- `Arxiv_Grabber.py`: arXiv metadata collector

## local_data Layout

- `local_data/sources/manual/`: hand-collected CSVs and IEEE incremental upload batches
- `local_data/sources/generated_exports/`: generated CSV batches, including Nature incremental outputs
- `local_data/cache/`: embedding cache files
- `local_data/exports/`: NotebookLM markdown and future exports
- `local_data/downloads/`: downloaded PDFs
- `local_data/backups/`: purge backups
- `local_data/schema_state.json`: local schema version state
- `local_data/conflict_resolutions.json`: dismissed conflict review items
- `local_data/source_registry.json`: IEEE / Nature update registry and watermarks
- `demo_data/export2026.03.04-08.56.26.csv`: bundled 2026 TMTT demo CSV for quick trial

## Tests

```bash
pytest
```

## Open Source Notes

- Do not commit `config.local.json`
- Do not commit local CSV / JSON / NPY / PDF data
- Do not commit any real API key
- `.gitignore` is already set up to ignore `local_data/`

## Original README

The original project README content is preserved below.

[English](#english-version) | [简体中文](#中文版本)

---

<a id="english-version"></a>
# 🔬 ChipSeeker - The Ultimate AI Search Engine for IC Design

**ChipSeeker** is a localized, intelligent paper repository tailored specifically for **IC design engineers and researchers**. 

Tired of incomplete or inaccurate keyword searches and the hassle of filtering out low-quality papers on IEEE Xplore or other academic search engines? ChipSeeker leverages high-dimensional vector semantic retrieval to build a fast, localized, and highly accurate personal knowledge base.

---
<img width="1703" height="936" alt="45ab0a5d948316db7a7896ffe000673b" src="https://github.com/user-attachments/assets/e886569a-a144-48eb-8a27-cc83e67ffba4" />
<img width="1712" height="1089" alt="959728b4c0db5f5d2ea8eb08bc877126" src="https://github.com/user-attachments/assets/ba21993f-a6c8-4904-8cd3-37dfad642b52" />

## Key Features

* **Semantic High-Dimensional Retrieval** Powered by top-tier academic LLMs like Voyage-4 and OpenAI. Break free from rigid keyword matching; perform deep semantic searches based on circuit architectures and specifications. This ensures you never miss highly relevant, high-quality papers, even if they lack exact keyword matches.
* **IC-Specific Scoring System** Features a comprehensive ranking of top IC conferences and journals, assigning exclusive tags like S+ or AA to premier venues (e.g., ISSCC, JSSC). It scientifically quantifies a paper's value by combining real-time citation counts from Semantic Scholar with publication years.
* **LLM Integration** Seamlessly connects with DeepSeek, Kimi, and other leading LLM APIs.
* **One-Click Export** Instantly open PDFs or seamlessly generate CSV databases, standard IEEE BibTeX citations, and Markdown knowledge packs optimized for NotebookLM.
* **Permanent Local Storage** Keep a permanent log of your reading history. Rate papers (from "Masterpiece" to "Trash"), add custom notes, and save search queries—a reliable companion for your entire academic career.
* **Automated Data Cleaning** Uses underlying regex rules to clean up messy CSV exports from IEEE. It physically filters out non-academic clutter, such as special issue introductions and conference table of contents, ensuring a 100% pure repository.

---

## Quick Start  

### 1. Installation
Clone the repository and install the required dependencies (Python 3.9+ recommended):
```bash
git clone [https://github.com/Yixuan-Miao/ChipSeeker.git](https://github.com/Yixuan-Miao/ChipSeeker.git)
cd ChipSeeker
pip install -r requirements.txt

```

### 2. Run the App

Start the application from your terminal:

```bash
streamlit run app.py

```

Once started, the terminal will output a `Local URL` (e.g., `http://localhost:8501`). Open this address in your browser to access the web interface.

### 3. Try the Demo

For easy testing, the system comes pre-loaded with approximately 300 IEEE TMTT papers from 2026.
Open the web page, configure your DeepSeek or OpenAI API Key in the left sidebar, and try searching for a paper to experience the scoring, AI analysis, and batch export features.

## How to Build Your Private Database?

**Method 1: Manual Import** Drop your exported `.csv` files (must include the `Abstract` column) into the designated folder and refresh the web page.

**Method 2: Get the Pro Database Curated by the Author** * **27,000+ Selected Top IC Papers:** Covers nearly 20 years of premier venues including ISSCC, JSSC, VLSI, and CICC.

* **Pre-computed SOTA Vector Matrices:** Includes 1024-dimensional `.npy` matrix files generated by the state-of-the-art academic model `voyage-4-large`. Simply overwrite your local files to instantly unlock top-tier retrieval accuracy.

**Contact:**

* **Email:** guangeofaisa@gmail.com
* **Xiaohongshu (RED):** guangeofaisa

Developed with ❤️ by Miao Yixuan. For IC Designers, by an IC Designer. If you find this helpful, please leave a Star! ⭐

---

<a id="中文版本"></a>

# 🔬 ChipSeeker (芯寻) - The Ultimate IC Design AI Search Engine

**ChipSeeker** 是一款专为**集成电路设计工程师与研究人员**打造的本地化智能论文库。

解决IEEE Xplore/各大AI找文网站关键词找论文不全不准/低质量论文不方便筛出，ChipSeeker 利用高维向量语义检索，构建快速搜索、本地化、找论文又准又精的私人知识库。

---

<img width="1703" height="936" alt="45ab0a5d948316db7a7896ffe000673b" src="https://github.com/user-attachments/assets/e886569a-a144-48eb-8a27-cc83e67ffba4" />
<img width="1712" height="1089" alt="959728b4c0db5f5d2ea8eb08bc877126" src="https://github.com/user-attachments/assets/ba21993f-a6c8-4904-8cd3-37dfad642b52" />

## ChipSeeker 核心特性

* **语义级高维检索** 对接 Voyage-4 / OpenAI 等顶尖学术大模型。摆脱死板的关键词匹配，基于电路架构和指标进行深层语义检索，不漏过字面不包含但强相关的优质论文。
* **IC 专属打分系统** IC 圈顶会顶刊综排，为 ISSCC、JSSC 等打上 S+ / AA 专属标签；
结合 Semantic Scholar 实时被引量与发表年份，科学量化论文价值。
* **LLM接口** 无缝接入 DeepSeek / Kimi 等 API。
* **一键导出** 支持一键打开 PDF，无缝生成 CSV 数据库、标准 IEEE BibTeX 引文代码，以及专供 NotebookLM 的 Markdown 喂料包。
* **本地记录永久保存** 永久记录你的阅读历史。支持为论文打分（神作至垃圾）、添加专属笔记、记录搜索匹配词，伴随你的整个科研生涯。
* **全自动数据清洗** 针对 IEEE 导出的混乱 CSV 进行底层正则拦截。物理级过滤特刊介绍、会议目录等非学术废料，保证文库 100% 纯净。

---

## Quick Start

### 1. 环境安装

克隆代码并安装必要的依赖（建议 Python 3.9+）：

```bash
git clone [https://github.com/Yixuan-Miao/ChipSeeker.git](https://github.com/Yixuan-Miao/ChipSeeker.git)
cd ChipSeeker
pip install -r requirements.txt

```

### 2. 运行

在终端输入以下命令启动：

```bash
streamlit run app.py

```

启动后，终端会输出一行类似于 `Local URL: http://localhost:8501` 的地址。打开你的浏览器，输入 `localhost:8501` 即可进入系统网页。

### 3. 体验预设数据 (Demo)

为了方便测试，系统中已预设了约 300 篇 2026 年的 IEEE TMTT 论文数据。
打开网页后，你可以直接在左侧边栏配置你自己的 DeepSeek 或 OpenAI API Key，尝试搜索一篇论文，体验打分、AI 分析和批量导出功能。

## 如何构建你的私人Database？

**一：手动导入** 导出为 `.csv` 格式（需包含 Abstract）的文件丢入文件夹，刷新网页即可。

**二：联系获取作者整理好的 Pro 完整版数据库** * **27,000+ 篇精选 IC 顶刊顶会：** 涵盖近 20 年的 ISSCC, JSSC, VLSI, CICC 等。

* **自带 SOTA 向量矩阵：** 附带使用现役最强学术模型 `voyage-4-large` 跑满的 1024 维 `.npy` 矩阵文件。下载后直接覆盖本地，瞬间解锁顶级精准度的检索体验。

**获取方式 (Contact):**

* **Email:** guangeofaisa@gmail.com
* **小红书:** guangeofaisa

Developed by Miao Yixuan. 如果满意请帮作者点一个Star吧！⭐
