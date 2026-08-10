# 招标文件智能合规审批

本项目把完整流程拆成三个边界清晰的步骤，同时提供一个统一入口：

1. 从 PDF、DOC、DOCX 等招标文档提取逐页文本、目录和章节；
2. 将政策规则与招标章节匹配，生成约定的 `rules_matched.json`；
3. 为规则生成并复用 Python checker，执行审批并输出报告。

所有模型调用统一连接服务器本地的 Qwen3-8B vLLM，不调用外部模型 API。模型服务由用户
手动启动，程序不会在运行时自动加载模型。

## 1. 代码结构

```text
src/
├── dir_extr/                   # 步骤一：多格式文档、目录、章节
│   ├── documents.py            # 格式分派、Office 转 PDF、DOCX 降级
│   ├── pdf.py
│   └── sections.py
├── cont_match/                 # 步骤二：规则读取、召回、LLM 重排
│   ├── rules.py
│   ├── retrieval.py
│   ├── llm_matcher.py
│   └── pipeline.py             # 串联步骤一、二并输出正式 JSON
├── code_gen/                   # 步骤三：checker 生成到报告
│   ├── checker_store.py        # checker 哈希、保存与复用
│   ├── graph.py                # 生成、验证、失败重试状态图
│   ├── prompts.py
│   ├── sandbox.py              # 静态检查与限时子进程执行
│   ├── reviewer.py             # 可选 LLM 复核
│   └── report.py               # JSON/Markdown 报告
├── page_schema.py              # 步骤一、二共享的内部数据结构
├── engine.py                   # 案件审批总编排
├── llm.py                      # 步骤二、三共用的本地模型客户端
└── rule_schema.py              # 步骤二输出、步骤三输入的正式契约

main.py                         # 三步统一入口，也支持从中间结果开始
prepare_case.py                 # 步骤一、二独立运行/排错入口
gen_checker.py                  # 单条规则 checker 生成/修复入口
scripts/run_batch.py            # 多案件批量完整运行
```

`checker_store.py`、`reviewer.py` 和 `report.py` 都只被第三步使用，因此归入 `code_gen/`。
`llm.py` 同时服务内容匹配和 checker 生成；`rule_schema.py` 横跨步骤二、三；
`page_schema.py` 横跨步骤一、二，所以保留在 `src/` 顶层。步骤一、二的生产串联逻辑属于
内容匹配的输出阶段，因此放在 `cont_match/pipeline.py`，不再额外保留 `preprocessing.py`。

更详细的依赖和数据流见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。逐函数说明见
[docs/PREPROCESSING_ANNOTATIONS.md](docs/PREPROCESSING_ANNOTATIONS.md)。同伴原始代码及标注保留在
`references/stage1+2/`，不进入生产调用链。`reports/` 仅由程序自动生成案件产物。

## 2. 完整数据流

```text
招标文档（PDF/DOC/DOCX/ODT/RTF/WPS/TXT/MD）
  │
  ▼
步骤一 dir_extr
  逐页文本 + 页码口径 + 正文印刷页 + 章节
  │
  ▼
步骤二 cont_match  ◀── 政策规则 JSON/XLSX
  字符级 TF-IDF 召回 + 可选 Qwen3-8B 重排
  │
  ▼
rules_matched.json
  │
  ▼
步骤三 code_gen
  checker 缓存/生成 → 子进程执行 → 可选复核 → 审批报告
```

步骤一、二负责定位原文，不直接判定违规。步骤三的 checker 才根据规则和已匹配 evidence
给出 `violation`、`warning`、`pass`、`insufficient_input` 或 `error`。

正式 JSON 契约见 [docs/MATCHED_JSON.md](docs/MATCHED_JSON.md)。关键约束是：

- `rule_id` 是规则整数序号；
- `rule_raw` 对应政策表“重点排查情形”；
- `source` 只包含 `file`；
- `evidence.location` 同时保存来源页、页码口径和正文印刷页；
- checker 生成时不向模型提供某个案件的 evidence，确保相同规则可跨案件复用。

### 2.1 支持的招标文件格式

| 格式 | 提取方式 | 页码口径 |
|---|---|---|
| PDF | PyMuPDF，失败时降级 pypdf/pdftotext | `original_pdf`，原始 PDF 物理页 |
| DOCX/DOCM | 优先 LibreOffice 转 PDF；不可用时解析 Word XML | `converted_pdf` 或 `logical_page` |
| DOC/ODT/RTF/WPS | LibreOffice 临时转 PDF | `converted_pdf` |
| TXT/Markdown | UTF-8/GB18030 直接读取，换页符切页 | `logical_page` |

服务器处理 Office 文档前建议安装 LibreOffice，并确认以下命令至少一个可用：

```bash
libreoffice --version
# 或
soffice --version
```

转换只发生在临时目录，`reports/report_x/` 内保留原始输入文件。DOCX 无 LibreOffice 时仍能降级
提取段落和表格，但只有文档中的显式分页符可以形成可靠逻辑页；旧 `.doc` 等格式没有该降级能力。

## 3. 启动 Qwen3-8B vLLM

先在模型服务终端进入项目环境，然后设置服务端变量：

```bash
export LLM_CUDA_VISIBLE_DEVICES=0,1,2,3
export LLM_MODEL_PATH="/home/zyl/public/LLM Library/Qwen3-8B"
export LLM_MODEL=Qwen3-8B
export LLM_HOST=127.0.0.1
export LLM_PORT=8001
export LLM_MAX_MODEL_LEN=16384
export LLM_GPU_MEM_UTIL=0.9

bash scripts/serve_vllm_qwen3_8b.sh --tensor-parallel-size 4
```

如果只用一张指定 GPU，例如物理 GPU 2：

```bash
export LLM_CUDA_VISIBLE_DEVICES=2
bash scripts/serve_vllm_qwen3_8b.sh --tensor-parallel-size 1
```

`LLM_MAX_MODEL_LEN` 是单次请求允许的最大上下文长度，越大 KV cache 显存开销越高；
`LLM_GPU_MEM_UTIL` 是 vLLM 可使用的每张可见 GPU 显存比例。当前默认值 `16384` 和 `0.9`
适合先在已跑通的服务器配置上使用；如果启动时显存不足，优先降低最大长度或显存比例。

另开业务程序终端设置客户端变量：

```bash
export LOCAL_LLM_BASE_URL=http://127.0.0.1:8001/v1
export LOCAL_LLM_MODEL=Qwen3-8B
export LOCAL_LLM_API_KEY=EMPTY

python -c "from src.llm import healthcheck; print(healthcheck())"
```

服务端 `LLM_MODEL` 与客户端 `LOCAL_LLM_MODEL` 必须一致；服务端 `LLM_PORT` 与
`LOCAL_LLM_BASE_URL` 中的端口也必须一致。

| 位置 | 变量 | 默认值/作用 |
|---|---|---|
| 服务脚本 | `LLM_MODEL_PATH` | 必填，Qwen3-8B 权重目录 |
| 服务脚本 | `LLM_MODEL` | `Qwen3-8B`，vLLM served model name |
| 服务脚本 | `LLM_CUDA_VISIBLE_DEVICES` | `0,1,2,3`，指定服务可见 GPU |
| 服务脚本 | `LLM_HOST` / `LLM_PORT` | `127.0.0.1` / `8001` |
| 服务脚本 | `LLM_MAX_MODEL_LEN` | `16384` |
| 服务脚本 | `LLM_GPU_MEM_UTIL` | `0.9` |
| Python 客户端 | `LOCAL_LLM_BASE_URL` | `http://localhost:8001/v1` |
| Python 客户端 | `LOCAL_LLM_MODEL` | `Qwen3-8B` |
| Python 客户端 | `LOCAL_LLM_CANDIDATE_CHARS` | `1200`，每个匹配候选最多发送的字符数 |

## 4. 一条命令运行完整流程

vLLM 启动并通过健康检查后，运行：

```bash
python main.py \
  --one_report_path /incoming/招标文件2.docx \
  --policy-rules /path/to/policy_rules.xlsx \
  --document-page-1-pdf-page 9 \
  --use-llm \
  --strict-llm
```

这个入口依次完成目录提取、内容匹配、checker 生成/复用、执行和报告输出。`--use-llm`
控制步骤二是否用 Qwen 重排；步骤三在缺少 checker 时默认会使用同一个 Qwen3-8B 服务生成代码。
需要额外复核 checker 结果时增加 `--review`。

程序不接收 `case_id`。它扫描 `reports/` 中已有的 `report_x`（同时兼容旧式 `reportx`），
自动创建最大编号加一的目录，并把输入文档复制进去。默认产物结构：

```text
reports/report_2/
├── 招标文件2.docx
├── matched/
│   └── rules_matched.json
├── preprocessing/
│   ├── converted_source.pdf    # Office 文档转换后保留，PDF/TXT 时没有
│   ├── outline.json
│   ├── sections.json
│   ├── matches.json
│   └── manifest.json
└── results/
    ├── summary.json
    └── summary.md

generated_checkers/
├── rule_<rule_id>_<hash>.py
└── rule_<rule_id>_<hash>.json
```

`--document-page-1-pdf-page 9` 表示原始 PDF 或 Office 转换后 PDF 的第 9 页对应正文印刷第 1 页，
因此正文页码为来源页码减 8。`evidence.location.page_basis` 会标记页码是原始 PDF、转换 PDF
还是逻辑页，避免不同口径混用。

## 5. 分阶段运行与排错

### 5.1 单独运行步骤一、二

```bash
python prepare_case.py \
  --one_report_path /incoming/招标文件2.docx \
  --policy-rules /path/to/policy_rules.xlsx \
  --document-page-1-pdf-page 9 \
  --use-llm \
  --strict-llm
```

也可以用统一入口运行到步骤二后停止：

```bash
python main.py \
  --one_report_path /incoming/招标文件2.docx \
  --policy-rules /path/to/policy_rules.xlsx \
  --document-page-1-pdf-page 9 \
  --use-llm \
  --strict-llm \
  --preprocess-only
```

不传 `--use-llm` 时只使用字符级召回，不访问模型。这适合验证页码、章节和 JSON 链路；
正式匹配建议使用 Qwen 重排，使模型可以拒绝所有无关候选。默认情况下模型失败会记录后降级，
`--strict-llm` 则要求任何匹配模型失败都终止。

### 5.2 从已有 JSON 单独运行步骤三

```bash
python main.py --input reports/report_2/matched/rules_matched.json
```

只执行指定规则：

```bash
python main.py \
  --input reports/report_2/matched/rules_matched.json \
  --rules 2 3 4
```

严格无模型诊断模式：

```bash
python main.py \
  --input reports/report_2/matched/rules_matched.json \
  --no-generate
```

无模型模式仍会执行已有 checker；没有缓存的规则会明确记录为 `error`，空 evidence 会记录为
`insufficient_input`。如果同时传 `--review`，复核仍会访问模型。

### 5.3 生成或修复单条 checker

```bash
python gen_checker.py \
  --input reports/report_2/matched/rules_matched.json \
  --rule-id 2

python main.py \
  --input reports/report_2/matched/rules_matched.json \
  --rules 2 \
  --no-generate
```

`prepare_case.py` 和 `gen_checker.py` 都是可直接运行的分阶段运维/排错入口，不是单元测试。
正式整案运行仍以 `main.py` 为准。

### 5.4 批量运行多个案件

`--reports_path` 会递归查找输入目录中所有受支持文档，其他文件自动跳过。启动 vLLM 后运行：

```bash
python scripts/run_batch.py \
  --reports_path /incoming/tenders \
  --policy-rules /path/to/policy_rules.xlsx \
  --document-page-1-pdf-page 9 \
  --use-llm \
  --strict-llm
```

默认任一案件失败就停止。希望继续处理后续案件并在最后汇总失败项时增加：

```bash
python scripts/run_batch.py \
  --reports_path /incoming/tenders \
  --policy-rules /path/to/policy_rules.xlsx \
  --document-page-1-pdf-page 9 \
  --use-llm \
  --strict-llm \
  --continue-on-error
```

也可以直接使用统一入口：

```bash
python main.py \
  --reports_path /incoming/tenders \
  --policy-rules /path/to/policy_rules.xlsx \
  --document-page-1-pdf-page 9 \
  --use-llm \
  --strict-llm
```

每个文档会单独生成新的 `reports/report_x/`。批量脚本调用同一个 `main.py`，因此单文件和批量
行为保持一致。不要把待解析文档放进自动输出的 `reports/` 目录。

## 6. Checker 缓存、定位和重新生成

系统对规范化后的 `rule_text` 计算 SHA-256，并生成：

```text
rule_<rule_id>_<规则哈希前12位>
```

报告中的 `checker_key` 可直接定位 `generated_checkers/` 下的 `.py` 代码和 `.json` 元数据。
规则内容变化时哈希也变化，不会误用旧规则的 checker。

人工重新生成第 2 条规则：

```bash
python gen_checker.py \
  --input reports/report_2/matched/rules_matched.json \
  --rule-id 2 \
  --feedback "这里填写人工发现的问题" \
  --force
```

或者直接在案件入口中忽略缓存：

```bash
python main.py \
  --input reports/report_2/matched/rules_matched.json \
  --rules 2 \
  --force-regenerate
```

checker 在真实 evidence 上执行异常时，`engine.py` 会把错误反馈给模型，只重生成当前规则；
传入 `--review` 后，复核不通过也只迭代当前规则。其他规则不受影响。

当前同一 `checker_key` 的重新生成会覆盖原 `.py/.json`，尚未实现内置历史版本与一键回滚。
需要恢复上一版时，应依赖 Git、服务器快照或人工备份；“重新生成”不等同于“恢复旧版本”。

## 7. 常用配置

| 环境变量 | 默认值 | 含义 |
|---|---|---|
| `CODEGEN_MAX_RETRIES` | `3` | 单次 checker 生成最大尝试次数 |
| `REVIEW_MAX_RETRIES` | `1` | 复核失败后的重新生成次数 |
| `REVIEW_MAX_EVIDENCE_CHARS` | `20000` | 复核最多携带的 evidence 字符数 |
| `CHECKER_TIMEOUT` | `30` | 单个 checker 最长执行秒数 |
| `GENERATED_DIR` | `generated_checkers` | checker 缓存目录 |

## 8. 测试

```bash
python -m unittest discover -s tests -v
```

真实 `report_2` JSON/XLSX 测试只在对应文件存在时运行；本地没有这些私有样例时会标记为
`skipped`，而不是伪造业务输入。PDF 存在时仍会验证真实页数和双页码。

## 9. 当前边界

- 支持 PDF、常见 Office 文档和纯文本；扫描件 OCR 尚未接入，程序不会伪造提取原文；
- DOC/ODT/RTF/WPS 依赖系统 LibreOffice；DOCX 无 LibreOffice 时只提供逻辑页降级；
- 内容匹配是候选定位，不是最终违规判断；
- 生成代码经过 AST 限制并在临时目录的限时子进程中执行，但这不等同于完整安全沙箱；
- 生产部署仍建议使用禁网、只读文件系统、资源限额和非特权容器。
