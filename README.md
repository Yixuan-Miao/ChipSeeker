# ChipSeeker V2

[English](#english) | [简体中文](#chinese)

---

<a id="english"></a>
## English

ChipSeeker is a local paper search workbench for IC design, AI hardware, and quantum hardware research. It combines:

- semantic retrieval over your own CSV library
- venue-aware ranking for top journals and conferences
- local reading notes, ratings, and exports
- IEEE semi-automatic incremental update workflow
- Nature / Nature Electronics / arXiv incremental collectors

In-app basics:

- sidebar language switch: English / 简体中文
- top-right `Help` button for the core workflow
- local content-pack ZIP upload supports large files

### Quick Install

Windows, one command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

Windows, double-click:

```bat
Install_ChipSeeker.bat
```

macOS / Linux:

```bash
bash ./scripts/setup.sh
```

The installer will:

- create `.venv`
- install required and optional dependencies
- install Playwright Chromium
- create `config.local.json` if missing
- initialize `local_data`

### Quick Start

Run:

```bat
Start_ChipSeeker.bat
```

or:

```bash
streamlit run app.py
```

Bundled demo:

- `demo_data/export2026.03.04-08.56.26.csv` is included
- in `Quick Start`, click `Load Bundled TMTT 2026 Demo CSV`
- default local embedding model is `all-MiniLM-L6-v2`, so semantic search can work without any API key

### Optional Config

Copy `config.example.json` to `config.local.json` only if you want cloud APIs.

Optional fields:

- `embedding_model`
- `emb_api_key`
- `llm_api_key`
- `llm_base_url`
- `llm_model`

If you want zero-config local use, keep `embedding_model` as `all-MiniLM-L6-v2`.

### Nature Grabber

Example:

```bash
python Nature_Grabber.py --query "cryogenic CMOS qubit readout" --journal nature-electronics --output nature_quantum.csv
```

Incremental example:

```bash
python Nature_Grabber.py --query "cryogenic CMOS qubit readout" --start-date 2026-04-01 --output nature_quantum_incremental.csv
```

Relative output paths are written into `local_data/sources/manual/`.

### Content Pack Delivery

If you sell your curated database, do not send the whole repo.

Recommended flow:

1. In the app, use `Content Pack -> Build Content Pack ZIP`
2. Send the ZIP from `local_data/exports/content_packs/`
3. The buyer imports it from `Quick Start` or the sidebar `Content Pack` panel

This is better than shipping the whole workspace because it includes only the managed library data, cache, registry, and state files.

### Project Layout

- `app.py`: Streamlit entry
- `Install_ChipSeeker.bat`: one-click Windows install
- `Start_ChipSeeker.bat`: one-click Windows launch
- `chipseeker/`: UI, sync, update manager, task queue, content pack, migrations
- `Nature_Grabber.py`: Nature metadata collector
- `Arxiv_Grabber.py`: arXiv metadata collector
- `local_data/`: runtime data, cache, exports, downloads, backups

### Tests

```bash
pytest
```

---

<a id="chinese"></a>
## 简体中文

ChipSeeker 是一个面向集成电路设计、AI 芯片和量子硬件研究的本地论文搜索工作台。它主要提供：

- 基于你自己 CSV 论文库的语义检索
- 面向顶刊顶会的 venue 评分与排序
- 本地阅读记录、评分、笔记和导出
- IEEE 半自动增量更新流程
- Nature / Nature Electronics / arXiv 增量抓取

应用内基础入口：

- 侧边栏可切换 `English / 简体中文`
- 右上角 `Help` 提供核心使用流程
- 本地内容包 ZIP 支持较大文件上传

### 一键安装

Windows 命令行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

Windows 双击：

```bat
Install_ChipSeeker.bat
```

macOS / Linux：

```bash
bash ./scripts/setup.sh
```

安装脚本会自动完成：

- 创建 `.venv`
- 安装必需和可选依赖
- 安装 Playwright Chromium
- 缺失时自动生成 `config.local.json`
- 初始化 `local_data`

### 快速启动

直接双击：

```bat
Start_ChipSeeker.bat
```

或运行：

```bash
streamlit run app.py
```

仓库自带一份演示数据：

- `demo_data/export2026.03.04-08.56.26.csv`
- 在应用的 `Quick Start` 里点击 `Load Bundled TMTT 2026 Demo CSV`
- 默认本地 embedding 模型是 `all-MiniLM-L6-v2`，不填任何 API key 也能直接体验语义搜索

### 可选配置

只有你要使用云端模型时，才需要把 `config.example.json` 复制为 `config.local.json`。

可选字段：

- `embedding_model`
- `emb_api_key`
- `llm_api_key`
- `llm_base_url`
- `llm_model`

如果你只想本地直接用，保持 `embedding_model = all-MiniLM-L6-v2` 即可。

### Nature Grabber

示例：

```bash
python Nature_Grabber.py --query "cryogenic CMOS qubit readout" --journal nature-electronics --output nature_quantum.csv
```

增量抓取示例：

```bash
python Nature_Grabber.py --query "cryogenic CMOS qubit readout" --start-date 2026-04-01 --output nature_quantum_incremental.csv
```

如果 `--output` 使用相对路径，CSV 会默认写入 `local_data/sources/manual/`。

### 数据库交付方案

如果你对外出售自己整理的数据库，不要直接发整个仓库。

推荐流程：

1. 在应用里使用 `Content Pack -> Build Content Pack ZIP`
2. 把生成在 `local_data/exports/content_packs/` 里的 ZIP 发给买家
3. 买家在 `Quick Start` 或侧边栏 `Content Pack` 面板里直接导入

这样最稳，因为它只包含受管理的数据、缓存、注册表和状态文件，不会把整个开发环境一起打包出去。

### 目录说明

- `app.py`：Streamlit 入口
- `Install_ChipSeeker.bat`：Windows 双击安装
- `Start_ChipSeeker.bat`：Windows 双击启动
- `chipseeker/`：UI、同步、更新管理、任务队列、内容包、迁移逻辑
- `Nature_Grabber.py`：Nature 元数据抓取器
- `Arxiv_Grabber.py`：arXiv 元数据抓取器
- `local_data/`：运行数据、缓存、导出、下载、备份

### 测试

```bash
pytest
```
