# 招标文件智能合规审批

系统保持“目录提取 → 内容匹配 → 规则校验”三步结构。规则始终由 `--policy-rules` 指定的
JSON/XLSX 提供；第三步读取同一行的“检查方式”，不再让大模型运行时生成 Python checker。

## 1. 当前架构

```text
招标文档（PDF/DOC/DOCX/ODT/RTF/WPS/TXT/MD）
  │
  ▼
步骤一 src/dir_extr
  文本、目录、章节、物理页/文件内页码
  │
  ▼
步骤二 src/cont_match  ◀── --policy-rules 规则 JSON/XLSX
  字符召回 + 可选并发 Qwen 重排
  │
  ▼
rules_matched.json（包含 check_method、structured_fields）
  │
  ▼
步骤三 src/rule_check
  ├─ 检查方式包含“结构化数据检查” → 全局确定性执行器
  └─ 其他检查方式                → 并发 Qwen 语义判定
  │
  ▼
decision_cache + summary.json + summary.md
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
│   ├── semantic.py          # 短 JSON 语义判定
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

规则表仍通过现有参数传入：

```bash
--policy-rules /path/to/规则.xlsx
```

读取列包括：

- `序号` → `rule_id`
- `重点排查情形` → `rule_raw`
- `触发逻辑公式` → `rule_text`
- `检查方式` → `check_method`
- `结构化数据展示字段` → `structured_fields`

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
`【法规依据】`，用于补充具体法律概念、数值和期限。`【公式】`、开发说明和其他生成的量化块不参与
召回或判定，`structured_fields` 只作字段别名提示。结构化操作直接从 `rule_raw + 法规依据` 派生。

确定性执行器是全局代码，不按案件、规则生成 Python。金额、百分比和日期值始终由正则提取。
当预设字段名没有出现在证据中时，本地 Qwen 只负责将该字段映射到正则已经发现的候选位置，模型
看不到候选的实际数值，也不负责读取或计算数值。映射后仍不完整时返回 `warning` 供人工复核，
不会把生成字段的缺失写成 `insufficient_input`。

步骤二以 `rule_raw` 为主查询、法规依据为辅助查询做字符 TF-IDF 召回，再由 Qwen 在候选章节中
重排。公式和结构化字段不参与召回；长章节发送给 Qwen 前会从全文截取与两项查询重叠最高的窗口，不再
固定只看章节开头。如果 Qwen 全部拒绝候选，达到字符分数阈值的候选会作为兜底 evidence 保留，
避免步骤三把一次空选误解成输入资料缺失。

## 3. 启动 vLLM

单张物理 GPU 3：

```bash
export LLM_CUDA_VISIBLE_DEVICES=3
export LLM_MODEL_PATH="/home/zyl/LLM Library/Qwen3-8B"
export LLM_MODEL=Qwen3-8B
export LLM_HOST=127.0.0.1
export LLM_PORT=8001
export LLM_MAX_MODEL_LEN=16384
export LLM_GPU_MEM_UTIL=0.9
export LLM_MAX_NUM_SEQS=16

bash scripts/serve_vllm_qwen3_8b.sh --tensor-parallel-size 1
```

业务终端：

```bash
export LOCAL_LLM_BASE_URL=http://127.0.0.1:8001/v1
export LOCAL_LLM_MODEL=Qwen3-8B
export LOCAL_LLM_API_KEY=EMPTY

python -c "from src.llm import healthcheck; print(healthcheck())"
```

`src/llm.py` 使用复用连接池并设置 `trust_env=False`，连接本机 vLLM 时不会误用服务器上的
SOCKS/HTTP 代理。

## 4. 完整运行

```bash
python main.py \
  --one_report_path files/docs/招标文件2.pdf \
  --policy-rules files/规则.xlsx \
  --use-llm \
  --strict-llm
```

`--use-llm` 仍只控制步骤二的候选重排。步骤三中，非结构化规则默认使用本地 Qwen 判定；如只想
测试确定性结构化规则，可增加 `--no-llm-check`。

批量运行：

```bash
python scripts/run_batch.py \
  --reports_path files/docs \
  --policy-rules files/规则.xlsx \
  --use-llm \
  --strict-llm \
  --continue-on-error
```

## 5. 性能配置

步骤二和步骤三都并发向 vLLM 发请求，使 vLLM 能进行连续批处理。默认并发数均为4：

```bash
export MATCHING_WORKERS=4
export SEMANTIC_WORKERS=4
```

也可按本次任务覆盖：

```bash
python main.py \
  --one_report_path files/docs/招标文件2.pdf \
  --policy-rules files/规则.xlsx \
  --use-llm \
  --match-workers 6 \
  --check-workers 6
```

建议从4开始。若 vLLM 日志长期显示 `Waiting` 很多或单请求延迟明显上升，再降低；如果仍始终只有
`Running: 1` 且显存充足，可逐步提高到6或8。

服务脚本默认设置 `--max-num-seqs 16` 并启用 prefix caching，足以容纳业务端4～8路并发；
`LLM_MAX_NUM_SEQS` 只是服务端并发上限，实际并发仍由 `MATCHING_WORKERS`/`SEMANTIC_WORKERS` 控制。

步骤三语义输出使用 `/no_think`，默认最多768 token，并只允许一次格式修正重试：

| 环境变量 | 默认值 | 作用 |
|---|---:|---|
| `MATCHING_WORKERS` | `4` | 步骤二并发重排数 |
| `SEMANTIC_WORKERS` | `4` | 步骤三并发语义判定数 |
| `SEMANTIC_MAX_TOKENS` | `768` | 单条判定最大输出 |
| `SEMANTIC_MAX_RETRIES` | `1` | JSON/引用校验失败后的重试次数 |
| `SEMANTIC_MAX_EVIDENCE_CHARS` | `16000` | 单规则发送的证据字符总量 |
| `LOCAL_LLM_MAX_CONNECTIONS` | `16` | HTTP 连接池上限 |
| `LOCAL_LLM_TIMEOUT` | `180` | 单次请求超时秒数 |

`--review` 会对每条结果再调用一次模型，默认不要开启；它用于抽查或高风险任务，而不是常规加速路径。

## 6. 中断续跑、重检和回滚

每个案件默认生成：

```text
reports/report_5/
├── 招标文件2.pdf
├── matched/rules_matched.json
├── preprocessing/
├── decision_cache/
│   ├── rule_<id>_<digest>.json
│   └── history/
└── results/
    ├── summary.json
    └── summary.md
```

从已有步骤二结果继续：

```bash
python main.py \
  --input reports/report_5/matched/rules_matched.json \
  --policy-rules files/规则.xlsx
```

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
  --policy-rules files/规则.xlsx \
  --use-llm \
  --strict-llm \
  --match-workers 4
```

或：

```bash
python main.py \
  --one_report_path files/docs/招标文件2.pdf \
  --policy-rules files/规则.xlsx \
  --use-llm \
  --preprocess-only
```

只运行步骤三：

```bash
python main.py --input reports/report_5/matched/rules_matched.json --policy-rules files/规则.xlsx
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
