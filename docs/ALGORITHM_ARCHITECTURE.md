# 招标文件智能合规审批

系统保持“目录提取 → 内容匹配 → 规则校验”三步结构。规则始终由 `--policy-rules` 指定的
JSON 提供（由本项目之外的程序统一转换，不再解析 Excel/PDF）；第三步读取同一行的“检查方式”，不再让大模型运行时生成 Python checker。

## 1. 当前架构

```text
招标文档（PDF/DOC/DOCX/ODT/RTF/WPS/TXT/MD）
  │
  ▼
步骤一 src/dir_extr
  文本、目录、章节、物理页/文件内页码
  │
  ▼
步骤二 src/cont_match  ◀── --policy-rules 规则 JSON
  字符 TF-IDF + BGE-M3 混合召回 + 可选并发 Qwen 重排
  │
  ▼
rules_matched.json（包含 check_method、structured_fields）
  │
  ▼
步骤三 src/rule_check
  ├─ 检查方式包含“结构化数据检查” → 全局确定性执行器 → Qwen 解释
  └─ 其他检查方式                → 并发 Qwen 语义判定与解释
  │
  ▼
reports/summary_brief.md + 各案件 decision_cache/summary.json/summary.md
```

代码布局：

```text
src/
├── dir_extr/                # 步骤一：多格式提取、页码、章节
├── cont_match/              # 步骤二：规则读取、召回、LLM 重排
├── rule_check/              # 步骤三：全局执行器、语义判定、缓存、报告
│   ├── methods.py           # 规范化“检查方式”并路由
│   ├── structured.py        # 金额/比例/日期正则提取与确定性计算
│   ├── field_resolver.py    # 预设字段与正则候选位置的语义别名映射
│   ├── semantic.py          # 一次调用完成短 JSON 语义判定与解释
│   ├── explainer.py         # 为确定性结果补充 LLM 分析，不修改结果
│   ├── cache.py             # 中断续跑、历史版本、回滚
│   ├── reviewer.py          # 可选第二次 LLM 复核
│   └── report.py
├── engine.py                # 并发执行步骤三
├── llm.py                   # vLLM 连接池，直连本机且不读取代理
├── page_schema.py
└── rule_schema.py

main.py                      # 完整/分阶段统一入口
prepare_case.py              # 只运行步骤一、二
scripts/run_batch.py         # 批量入口
```

旧的案件专用代码生成模块和 `gen_checker.py` 已从生产框架移除。历史判定回滚由
`decision_cache/history/` 提供。

## 2. “检查方式”路由

规则由本项目之外的程序统一转成 JSON 后传入（不再解析 Excel/PDF）：

```bash
--policy-rules /path/to/policy_rules.json
```

JSON 顶层为 `{version, rules:[...]}` 或直接规则数组，每条规则字段：

- `rule_id`（整数，缺省用行号）
- `rule_raw` → 重点排查情形（必填）
- `rule_text` → 触发逻辑公式，**对象**，含 `description`/`legal_basis`/`formula`/`dev_note` 四个可选子字段；载入时按 `【描述】/【法规依据】/【公式】/【开发说明】` 顺序重组为块字符串（也兼容纯字符串）
- `check_method` → 检查方式（缺省“大模型分析”）
- `structured_fields` → 结构化数据展示字段
- `match_hints` → 仅用于步骤二召回的提示，不进最终输出

当前路由规则非常明确：只要“检查方式”的组合中包含 `结构化数据检查`，就走全局确定性执行器；
其他方法，包括关键词匹配、大模型分析、政策库匹配及其组合，走本地 Qwen 语义判定。

例如：

| 检查方式 | 执行器 |
|---|---|
| `结构化数据检查` | `structured` |
| `结构化数据检查+大模型分析` | `structured` |
| `关键词匹配+大模型分析` | `semantic_llm` |
| `大模型分析` | `semantic_llm` |
| `政策库匹配+大模型分析` | `semantic_llm` |

`rule_raw`（重点排查情形）决定审查主题；程序会从 `rule_text` 中单独拆出明确标记的
`【法规依据】`，用于补充具体法律概念、数值和期限。`【描述】`只作为 LLM 理解适用场景的说明，
不能单独新增阈值、条件或缺失输入。`【公式】`、开发说明和其他生成的量化块不参与召回或判定，
`structured_fields` 只作字段别名提示。结构化操作直接从 `rule_raw + 法规依据` 派生。

确定性执行器是全局代码，不按案件、规则生成 Python。金额、百分比和日期值始终由正则提取。
当预设字段名没有出现在证据中时，本地 Qwen 只负责将该字段映射到正则已经发现的候选位置，模型
看不到候选的实际数值，也不负责读取或计算数值。映射后仍不完整时返回 `warning` 供人工复核，
不会把生成字段的缺失写成 `insufficient_input`。

当前步骤三不是 embedding 相似度阈值判定：非结构化规则直接由 Qwen 读取 `evidence`、`rule_raw`、
`【描述】`和`【法规依据】`，一次返回状态、简要结论和可解释分析；结构化规则先由正则和全局代码给出状态，
再调用一次 Qwen 解释该结果是否有证据支持。解释模型不能覆盖确定性状态，只会在指标中写入
`llm_analysis_consistent` 和分析置信度。embedding 只参与步骤二召回，不决定步骤三状态。

结构化执行器会把派生操作、正则提取值、证据索引、比较符、阈值和计算结果保存在
`structured_result.metrics`。确定性计算完成时，Qwen 只解释和审计该结果，不覆盖状态；当结构化初判带
`requires_review=true` 时，系统再执行一次完整语义判定，并同时保留 `structured_result` 和最终 `result`，
方便比较“正则为什么无法完成”和“语义兜底如何判断”。

步骤二以 `rule_raw` 为主查询、法规依据为辅助查询，同时计算字符 TF-IDF 和 BGE-M3 embedding
相似度，默认按55%字符分数、45%向量分数融合。长章节先按1400字符、重叠200字符切片，章节向量分数
取最相关切片，避免只编码章节开头。融合召回 top-k 后由 Qwen 重排，最终每条规则最多保留3个 evidence。
公式和结构化字段不参与召回；如果 Qwen 全部拒绝候选，达到融合分数阈值的候选会作为兜底 evidence
保留，避免步骤三把一次空选误解成输入资料缺失。

## 3. 启动 vLLM

全项目只读取 `config/runtime.env`。首次部署运行 `bash scripts/setup_runtime_config.sh`，然后在该文件中配置：

```dotenv
LLM_CUDA_VISIBLE_DEVICES=3
LLM_MODEL_PATH="/home/zyl/LLM Library/Qwen3-8B"
LLM_MODEL=Qwen3-8B
LLM_HOST=127.0.0.1
LLM_PORT=8001
LLM_MAX_MODEL_LEN=16384
LLM_GPU_MEM_UTIL=0.9
LLM_MAX_NUM_SEQS=16
LOCAL_LLM_BASE_URL="http://${LLM_HOST}:${LLM_PORT}/v1"
LOCAL_LLM_MODEL="${LLM_MODEL}"
LOCAL_EMBED_MODEL="/home/zyl/LLM Library/bge-m3"
LOCAL_EMBED_DEVICE=cpu
```

启动和检查不需要执行任何 `export`：

```bash
bash scripts/algorithm/serve_vllm_qwen3_8b.sh --tensor-parallel-size 1
bash scripts/algorithm/check_vllm.sh
```

步骤二默认加载本地 BGE-M3，服务器环境需安装 `sentence-transformers`，并把 `LOCAL_EMBED_MODEL`
指向本地权重目录。`LOCAL_EMBED_DEVICE` 可设为 `cpu` 或 `cuda:0`。当前后端 worker 默认不设置
`CUDA_VISIBLE_DEVICES`，因此 `cuda:0` 表示 worker 可见的第一张 GPU；生产环境若要把 embedding 固定到
另一张卡，应在进程管理器中限制 worker 的 GPU，而 vLLM 的物理 GPU 始终由 `LLM_CUDA_VISIBLE_DEVICES`
配置并由 vLLM 启动脚本设置。embedding 初始化失败时默认打印原因并降级为纯字符召回；
设置 `LOCAL_EMBED_STRICT=1` 可改为立即终止，`--no-embedding` 可显式关闭。

`src/llm.py` 使用复用连接池并设置 `trust_env=False`，连接本机 vLLM 时不会误用服务器上的
SOCKS/HTTP 代理。

## 4. 完整运行

每次新的单文件或批量完整运行都会先删除并重建根目录 `reports/`。该目录始终只表示最近一次运行，
案件编号也从 `report_1` 重新开始；如需保留上一轮结果，请在启动新任务前自行复制整个目录。

```bash
bash scripts/algorithm/run_one_report.sh
```

`--use-llm` 仍只控制步骤二的候选重排。步骤三默认使用本地 Qwen：非结构化规则由一次调用完成
判定和解释，结构化规则在确定性计算后调用一次模型解释。如只想测试纯确定性计算，可增加
`--no-llm-check`；此时非结构化规则无法自动判定，结构化规则仍执行但不生成 LLM 分析。

批量运行：

```bash
bash scripts/algorithm/run_reports.sh
```

## 5. 性能配置

步骤二和步骤三都并发向 vLLM 发请求，使 vLLM 能进行连续批处理。统一在 `config/runtime.env` 调整：

```dotenv
MATCHING_WORKERS=4
SEMANTIC_WORKERS=4
```

建议从4开始。若 vLLM 日志长期显示 `Waiting` 很多或单请求延迟明显上升，再降低；如果仍始终只有
`Running: 1` 且显存充足，可逐步提高到6或8。

服务脚本默认设置 `--max-num-seqs 16` 并启用 prefix caching，足以容纳业务端4～8路并发；
`LLM_MAX_NUM_SEQS` 只是服务端并发上限，实际并发仍由 `MATCHING_WORKERS`/`SEMANTIC_WORKERS` 控制。

步骤三判定和解释均使用 `/no_think`，默认最多768 token；语义判定只允许一次格式修正重试。Qwen
仍可能输出空的 `<think></think>` 包装，因此所有步骤三模型调用统一从混合文本中提取第一个 JSON，
兼容 think 标签、Markdown 代码块和前后说明文字：

| 环境变量 | 默认值 | 作用 |
|---|---:|---|
| `MATCHING_WORKERS` | `4` | 步骤二并发重排数 |
| `SEMANTIC_WORKERS` | `4` | 步骤三并发语义判定数 |
| `SEMANTIC_MAX_TOKENS` | `768` | 单条判定最大输出 |
| `SEMANTIC_MAX_RETRIES` | `1` | JSON/引用校验失败后的重试次数 |
| `SEMANTIC_MAX_EVIDENCE_CHARS` | `16000` | 单规则发送的证据字符总量 |
| `LOCAL_LLM_MAX_CONNECTIONS` | `16` | HTTP 连接池上限 |
| `LOCAL_LLM_TIMEOUT` | `180` | 单次请求超时秒数 |
| `LOCAL_EMBED_MODEL` | `BAAI/bge-m3` | embedding 模型名或本地权重目录 |
| `LOCAL_EMBED_DEVICE` | 自动 | embedding 运行设备，如 `cpu`、`cuda:0` |
| `LOCAL_EMBED_BATCH_SIZE` | `16` | embedding 批量编码大小 |
| `LOCAL_EMBED_WEIGHT` | `0.45` | 融合分数中的 embedding 权重 |
| `LOCAL_EMBED_CHUNK_CHARS` | `1400` | 长章节向量切片字符数 |
| `LOCAL_EMBED_CHUNK_OVERLAP` | `200` | 相邻向量切片重叠字符数 |

一般语义规则调用一次模型；结构化规则调用一次结果解释，若字段名需要近义映射，可能再增加一次
仅选择正则候选位置的调用。`--review` 会在这些常规分析之外再调用一次独立模型复核，默认不要开启；
它用于抽查或高风险任务。

LLM 分析无法生成时会记录为独立的 `analysis_error`，不会再计入 `pipeline_error` 或覆盖已经得到的
规则状态；最后一次未通过校验的模型原文会截断保存到 `analysis_raw` 便于排查。

## 6. 输出报告、中断续跑和回滚

一次批量或单文件运行统一生成：

```text
reports/
├── summary_brief.md              # 本次运行唯一执法简报，汇总全部招标文件
├── report_1/
│   ├── 招标文件1.pdf
│   ├── matched/rules_matched.json
│   ├── preprocessing/
│   ├── decision_cache/
│   │   ├── rule_<id>_<digest>.json
│   │   └── history/
│   └── results/
│       ├── summary.json
│       └── summary.md             # 当前文件详细报告；含 LLM 分析与证据位置
└── report_2/
    └── ...
```

`summary_brief.md` 列出每份文件的通过、预警、违规和未完成数量，并按文件列出各状态对应的规则，
用于执法人员快速浏览。每个案件的 `results/summary.md` 保留执行器、法规依据、指标、错误和证据等
详细信息。各状态都会记录 LLM 分析以及步骤二证据的章节、PDF页码/文件内页码；通过规则不再复制
完整 evidence 原文，避免报告过长。违规和预警若有可回引 finding，仍保留短的命中原文。

从已有步骤二结果继续：

```bash
python main.py \
  --input reports/report_5/matched/rules_matched.json \
  --policy-rules files/policy_rules.json
```

`--input` 属于当前 `reports/` 内的续跑/重检，不会在启动时清空目录，否则会删除它正要读取的 JSON
和历史缓存；它会更新案件详细报告以及根目录 `reports/summary_brief.md`。新的
`--one_report_path`/`--reports_path` 任务才会覆盖整个 `reports/`。

已经成功完成的规则会按“规则内容 + 检查方式 + evidence”哈希复用，只有缺失或变化的规则重新执行。
为旧版 JSON 同时传入 `--policy-rules` 时，程序按 `rule_id` 补齐最新“检查方式”和“结构化数据展示字段”，
不会重跑目录提取和内容匹配；新版 JSON 已自带这两个字段，仍建议传入以应用规则表中的最新路由。

只重检部分规则：

```bash
python main.py \
  --input reports/report_5/matched/rules_matched.json \
  --rules 2 3 9 \
  --force-recheck
```

强制重检前的结果会自动写入 `decision_cache/history/`。恢复指定规则上一版本：

```bash
python main.py \
  --input reports/report_5/matched/rules_matched.json \
  --rules 2 3 \
  --rollback-rules 2 3
```

旧参数仍兼容：`--no-generate` 等价于 `--no-llm-check`，`--force-regenerate` 等价于
`--force-recheck`，`--checker-dir` 等价于 `--check-cache-dir`。

## 7. 分阶段运行

只运行步骤一、二：

```bash
python prepare_case.py \
  --one_report_path files/docs/招标文件2.pdf \
  --policy-rules files/policy_rules.json \
  --use-llm \
  --strict-llm \
  --match-workers 4
```

或：

```bash
python main.py \
  --one_report_path files/docs/招标文件2.pdf \
  --policy-rules files/policy_rules.json \
  --use-llm \
  --preprocess-only
```

只运行步骤三：

```bash
python main.py --input reports/report_5/matched/rules_matched.json --policy-rules files/policy_rules.json
```

## 8. 支持的招标文档

| 格式 | 提取方式 | 页码口径 |
|---|---|---|
| PDF | PyMuPDF，失败时 pypdf/pdftotext | 原始 PDF 物理页 |
| DOCX/DOCM | LibreOffice 转 PDF；不可用时解析 Word XML | 转换 PDF 页或逻辑页 |
| DOC/ODT/RTF/WPS | LibreOffice 转 PDF | 转换 PDF 页 |
| TXT/Markdown | UTF-8/GB18030，换页符切页 | 逻辑页 |

Office 文档建议在服务器安装 LibreOffice。转换后的 PDF 会保留在
`reports/report_x/preprocessing/converted_source.pdf`。

## 9. 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖检查方式路由、旧 JSON 兼容、确定性金额/日期规则、LLM JSON 与原文引用校验、步骤二
并发、判定缓存、强制重检和回滚。
