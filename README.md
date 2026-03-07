# 🔬 ChipSeeker (芯寻) - The Ultimate IC Design AI Search Engine

**ChipSeeker** 是一款专为**集成电路设计工程师与研究人员**打造的本地化智能论文库。

解决IEEE Xplore/各大AI找文网站关键词找论文不全不准/低质量论文不方便筛出，ChipSeeker 利用高维向量语义检索，构建快速搜索、本地化、找论文又准又精的私人知识库。

---
<img width="1703" height="936" alt="45ab0a5d948316db7a7896ffe000673b" src="https://github.com/user-attachments/assets/e886569a-a144-48eb-8a27-cc83e67ffba4" />
## Features

* **语义搜索**  
支持对接地表最强学术向量模型 (Voyage-4 / OpenAI) 或本地轻量模型，不漏过强相关但和搜索词没有对应上的优质论文。
* **IC 专属论文打分系统**  
综合排名ISSCC, JSSC, VLSI, CICC 等顶刊顶会打上`S+` / `AA` 等标签；  
实时抓取当前论文的真实被引量 (Semantic Scholar API)，并与论文年份共同参与综合评分。
* **LLM接口**  
DeepSeek / Kimi / GPT 接口。
* **一键导出**  
支持一键导出到Zotero，一键打开pdf，一键导出到NotebookLM，一键导出BiB等。
* **本地记录保存**  
可记录下论文评分，评语，被搜索到的关键词，打开次数等，方便加深记忆。


---

## Quick Start  

### 1. 环境安装
克隆代码并安装必要的依赖（建议 Python 3.9+）：
```bash
git clone [https://github.com/Yixuan-Miao/ChipSeeker.git](https://github.com/Yixuan-Miao/ChipSeeker.git)
cd ChipSeeker
pip install -r requirements.txt
streamlit run app.py
```
## 2. 运行
在终端输入以下命令启动：
```bash
streamlit run app.py
```
启动后，终端会输出一行类似于 Local URL: http://localhost:8501 的地址。打开你的浏览器，输入 localhost:8501 即可进入系统网页。

## 3. 体验预设数据 (Demo)
为了方便测试，系统中已预设了约 300 篇 2026 年的 IEEE TMTT 论文数据。
打开网页后，你可以直接在左侧边栏配置你自己的 DeepSeek 或 OpenAI API Key，尝试搜索一篇论文，体验打分、AI 分析和批量导出功能。

## 如何构建你的私人Database？

一：手动导入
导出为 .csv 格式包含 Abstract的文件丢入文件夹，刷新网页即可。

二：联系获取作者整理好的 Pro 完整版数据库 

27,000+ 篇精选 IC 顶刊顶会：涵盖近 20 年的 ISSCC, JSSC, VLSI, CICC 等。

自带 SOTA 向量矩阵：附带使用现役最强学术模型 voyage-4-large 跑满的 1024 维 .npy 矩阵文件。下载后直接覆盖本地，瞬间解锁顶级精准度的检索体验。

获取方式 (Contact):

Email: guangeofaisa@gmail.com

小红书: guangeofaisa

Developed with ❤️ by Miao Yixuan. For IC Designers, by an IC Designer. 如果满意请帮作者点一个Star吧！
