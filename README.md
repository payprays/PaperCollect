PaperCollect
============

PaperCollect 是一个小型流程，负责：
- 从 DBLP 拉取指定会议论文；
- 用 OpenAlex、Arxiv、Crossref、EuropePMC、Semantic Scholar 等多源补全摘要和引用信息；
- 将结果存成 JSON 便于复用；
- 用 OpenAI 做轻量 RAG 检索 / 问答（ask）。

依赖
- Python 3.12+
- OpenAI API Key：设置为环境变量 `OPENAI_API_KEY`（RAG 搜索/问答必需，采集阶段可选）

环境准备
```bash
uv sync                                         # 基于 pyproject.toml / uv.lock 安装依赖
source .venv/bin/activate
```

配置
- 修改 `config.yaml` 选择会议、年份、并发数、输出目录等。
- 不要把密钥写入仓库：推荐 `export OPENAI_API_KEY=<your-key>`；`config.yaml` 中的 `openai_api_key` 为空占位。

`config.yaml` 示例片段：
```yaml
conferences:
  - SP
  - NDSS
years:
  - 2024
  - 2025
concurrency:
  threads: 5
limit_per_conference: 0   # 0 表示不限制
openai_api_key: ""        # 建议用环境变量
output_dir: "data"
```

采集与补全论文
```bash
uv run python main.py --config config.yaml
```
按会议/年份增量获取并补全论文，写入 `data/` 目录（每个会议-年份一个 JSON）。重复运行只补全缺失的元数据。

RAG 检索 / 问答
- 先确保已有 `data/` 下的 JSON 数据，并设置密钥：`export OPENAI_API_KEY=<your-key>`。
- 检索模式（返回排序结果，自动中译标题/摘要）：
```bash
uv run python search_papers.py "LLM-based fuzzing for systems software" --top_k 5 --mode search --year 2024 --exclude Workshop Poster
```
- 问答模式（基于 top K 论文生成答案）：
```bash
uv run python search_papers.py "What defenses work against prompt injection?" --top_k 10 --mode ask --venue NDSS
```

提示
- 输出按会议-年份缓存，中断后可重跑。
- 测试时可把 `limit_per_conference` 设小以减少 API 消耗。
- `.env` 已加入 `.gitignore`，如需本地文件存放密钥可放这里。
