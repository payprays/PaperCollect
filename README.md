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
  - id: sp
    display_name: IEEE S&P
    full_name: IEEE Symposium on Security and Privacy
    dblp_stream: conf/sp
    aliases: [SP, S&P]
    category: SC
  - id: ndss
    display_name: NDSS
    full_name: Network and Distributed System Security Symposium
    dblp_stream: conf/ndss
    category: SC
include_ccfddl_catalog: true  # 合并 CCFDDL 的 300+ 会议 catalog
years:
  - 2024
  - 2025
concurrency:
  threads: 5
limit_per_conference: 0   # 0 表示不限制
openai_api_key: ""        # 建议用环境变量
output_dir: "data"
url_base: ""             # 可选，例如反代到 /papercollect 时设为 "/papercollect"
```

采集与补全论文
```bash
uv run python main.py --config config.yaml
```
按会议/年份增量获取并补全论文，写入 `data/` 目录（每个会议-年份一个 JSON）。重复运行只补全缺失的元数据。

Web 前端 / RSS
```bash
uv run python web.py --config config.yaml --host 127.0.0.1 --port 5000
```
打开 `http://127.0.0.1:5000` 后，可以按 CCFDDL 分类筛选会议，并输入要采集的年份。`config.yaml` 中的 `years` 只作为 UI 建议值，不限制实际输入；后端允许合理年份，便于采集最新 proceedings。会议配置使用统一 catalog：`id` 作为文件/RSS slug，`display_name` 用于界面展示，`dblp_stream` 用于权威 DBLP stream 查询。默认会合并 `src/data/ccf_conferences.yaml` 中来自 CCFDDL 的 300+ 会议；如只想使用本地 `config.yaml`，可设置 `include_ccfddl_catalog: false`。采集完成后会生成对应 RSS 链接，例如：
```text
http://127.0.0.1:5000/feed/icse/2025.xml
```
RSS 内容来自已保存的 JSON 结果；如果某个会议/年份还没有采集结果，对应 feed 会返回 404。

如果服务挂在子路径下，可在 `config.yaml` 设置 `url_base`：
```yaml
url_base: "/papercollect"
```
此时前端 API 请求、静态资源、任务状态 URL 和 RSS 链接都会带上 `/papercollect` 前缀。

前端的搜索框会在已保存的 JSON 论文库中做本地搜索，默认使用概念语义搜索，也可切换为关键词搜索；可按 CCFDDL 分类、会议和年份过滤，不需要 OpenAI API key。概念语义搜索使用本地 expanded BM25 + 概念词表重排，并会过滤 proceedings、poster、chair message 等非正式论文条目。

会议分类资源来自 `ccfddl/ccf-deadlines` 的公开 conference YAML，已生成到 `src/data/ccf_conferences.yaml` 作为本地只读 catalog，运行时不依赖外网。

在 CCFDDL 分类之外，前端还提供面向本项目研究方向的 Focus 过滤：Cloud Security、Cloud Native、Distributed Systems、Software Engineering、Security。Focus 标签由会议元数据和本地规则推断，也可在 `config.yaml` 的会议条目中用 `focus_tags` 覆盖或补充。

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
