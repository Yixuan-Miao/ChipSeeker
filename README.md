# 🔬 ChipSeeker (芯寻) - The Ultimate IC Design AI Search Engine

**ChipSeeker** 是一款专为**集成电路 (IC) 设计工程师与研究人员**打造的本地化、智能学术文献检索与管理智库。

传统的 IEEE Xplore 搜索死板、充斥着大量无用的会议目录和卷首语，且无法沉淀个人的阅读思考。ChipSeeker 结合了业界最强的高维向量语义检索 (Embedding) 与本地大模型总结 (LLM)，帮你建立只属于你自己的芯片设计私人智库。

## ✨ Core Features (核心特性)

- 🧠 **语义级降维搜索**：原生支持地表最强学术向量模型 `Voyage-4-large` 以及 `OpenAI`。搜 "Cryo-CMOS Qubit LNA"，系统凭借深层语义理解直接捞出精准匹配的顶级架构论文，彻底告别关键词堆砌。
- 🏛️ **IC 专属学术滤网**：底层硬编码 2025/2026 最新 JCR 影响因子与顶级会议（ISSCC, JSSC, VLSI, CICC 等），自动打上 `S+ / AA` 独家分级标签。
- 🧹 **暴力清洗学术垃圾**：内置针对 IEEE 数据库的强力正则拦截器。一键物理删除所有 Guest Editorial、Author Index 和 Technical Session 介绍，还你 100% 纯净学术空间。
- 🤖 **大模型 Global Review**：选中 20 篇高价值论文，一键调用 DeepSeek / Kimi / GPT-4，直接生成中文视角的《技术趋势演进与架构对比报告》。
- 📊 **极致的学术管理**：本地记录阅读次数、个人神作打分；支持一键导出 CSV 数据库、Markdown (无缝对接 NotebookLM) 以及自动生成 LaTeX 友好的 BibTeX 引文。

---

## 🚀 Quick Start (快速开始)

### 1. 环境配置
确保你已安装 Python 3.9+。在终端中运行以下命令克隆仓库并安装依赖：
```bash
git clone [https://github.com/Yixuan-Miao/ChipSeeker.git](https://github.com/Yixuan-Miao/ChipSeeker.git)
cd ChipSeeker
pip install -r requirements.txt