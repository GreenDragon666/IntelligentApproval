# 架构说明

## 1. 三个步骤

| 步骤 | 目录 | 输入 | 输出 |
|---|---|---|---|
| 一：目录提取 | `src/dir_extr/` | 招标 PDF、正文页码偏移 | `PageText`、目录书签、`DocumentSection` |
| 二：内容匹配 | `src/cont_match/` | 章节、政策规则 JSON/XLSX | 带双页码 evidence 的 `MatchedCase` |
| 三：代码生成与审批 | `src/code_gen/` | `MatchedCase` | checker、规则执行结果、审批报告 |

目录结构直接表达业务步骤：

```text
src/
├── dir_extr/                   # 步骤一
│   ├── pdf.py
│   └── sections.py
├── cont_match/                 # 步骤二
│   ├── rules.py
│   ├── retrieval.py
│   ├── llm_matcher.py
│   └── pipeline.py             # 串联步骤一、二，输出正式 JSON
├── code_gen/                   # 步骤三
│   ├── checker_store.py
│   ├── graph.py
│   ├── prompts.py
│   ├── sandbox.py
│   ├── reviewer.py
│   └── report.py
├── page_schema.py              # 步骤一、二共享
├── rule_schema.py              # 步骤二、三共享
├── llm.py                      # 步骤二、三共享
└── engine.py                   # 案件审批编排
```

归类原则是“主要由哪个步骤调用，就放入哪个步骤；跨步骤使用才保留顶层”。因此：

- `checker_store` 只负责第三步生成代码的持久化和复用；
- `reviewer` 只复核第三步的 checker 结果；
- `report` 只渲染第三步的审批结果；
- `page_schema` 被目录提取和内容匹配共同使用；
- `rule_schema` 是内容匹配输出与代码生成输入之间的稳定接口；
- `llm` 被步骤二候选重排和步骤三 checker 生成/复核共同使用。

## 2. 入口与编排层

`main.py` 是用户统一入口。它不包含提取、匹配或审批算法，只负责选择运行范围和串联编排：

```text
main.py --one_report_path <PDF>
  → 自动创建 reports/report_x 并复制输入 PDF
  → cont_match.pipeline.prepare_case
      → dir_extr
      → cont_match
      → 写 rules_matched.json
  → engine.run_case
      → code_gen checker 缓存/生成/执行/复核
  → code_gen.report

main.py --input rules_matched.json
  → 跳过步骤一、二
  → engine.run_case
  → code_gen.report

main.py --reports_path <目录>
  → 递归发现所有 PDF
  → 每个 PDF 分配独立的 reports/report_x
  → 对每个 PDF 执行与单文件模式相同的三步流程
```

`prepare_case.py` 是步骤一、二的独立运行/排错入口；`gen_checker.py` 是单条规则的第三步生成/
修复入口。它们不是单元测试，也不会替代正式统一入口 `main.py`。

`case_id` 仍是正式 JSON 内部契约字段，但不再由命令行传入。程序扫描既有 `report_x` 和旧式
`reportx`，取最大编号加一，并把新目录名作为 `case_id`。失败案件保留已经分配的目录，避免
后续任务覆盖其追溯信息。

## 3. 步骤一：目录提取

`dir_extr/pdf.py`：

- 使用 PyMuPDF 逐真实 PDF 页抽取文本；
- 依赖不可用时依次尝试 pypdf 和系统 `pdftotext`；
- 保存 PDF 物理页；
- 根据 `document_page_1_pdf_page` 计算正文印刷页；
- 提取 PDF 书签目录。

`dir_extr/sections.py`：

- 优先按 PDF 书签切分；
- 无书签时使用通用中文标题模式；
- 长章节按最大页数切块；
- 每个章节保留标题、完整原文和两套页码范围。

本步骤不包含政策规则、行业关键词或模型调用。

## 4. 步骤二：内容匹配

`cont_match/rules.py` 从正式 JSON 或政策 XLSX 加载：

- 整数 `rule_id`；
- `rule_raw`（重点排查情形）；
- `rule_text`（触发逻辑公式）；
- 只用于召回的辅助字段。

`cont_match/retrieval.py` 使用领域无关的字符级 TF-IDF 召回 top-k 章节；
`cont_match/llm_matcher.py` 可把候选交给本地 Qwen3-8B 重排，也允许模型拒绝全部候选。

`cont_match/pipeline.py::prepare_case` 是步骤二的生产入口，负责：

1. 调用目录提取；
2. 加载规则并执行召回/重排；
3. 转换为正式 `MatchedCase`；
4. 写 `rules_matched.json` 和可追溯中间产物。

无模型时使用字符召回结果，适合链路测试；正式运行建议启用 Qwen 重排。模型失败默认降级并
记录到 `matches.json`，`--strict-llm` 可改为立即终止。

## 5. 步骤三：代码生成与审批

```text
MatchedCase.rules[]
  → evidence 为空：insufficient_input
  → checker_store 按规则哈希查找 checker
      ├── 已存在：复用
      └── 不存在：graph 调用本地 Qwen3-8B 生成
  → sandbox 静态检查、限时子进程执行、结果契约校验
  → 可选 reviewer 复核
      ├── 通过：进入报告
      └── 不通过：只反馈并重生成当前规则
  → report 输出 summary.json / summary.md
```

`engine.py` 是案件级编排器：它管理规则选择、错误隔离、重生成和复核迭代；具体的第三步实现
仍在 `code_gen/` 内。单条规则失败不会终止其他规则。

## 6. 共享正式契约

```text
MatchedCase
├── case_id
├── source
│   └── file
└── rules[]
    ├── rule_id: int
    ├── rule_raw
    ├── rule_text
    └── evidence[]
        ├── location
        │   ├── file
        │   ├── section
        │   ├── pdf_pages
        │   └── document_pages
        └── text
```

该契约定义在 `src/rule_schema.py`。步骤二只能通过它输出，步骤三只依赖它消费，因此第三步
不需要知道 PDF 如何拆分或候选如何召回。

## 7. Checker 复用

规范化 `rule_text` 后计算 SHA-256：

```text
rule_<rule_id>_<digest前12位>.py
```

生成 checker 时只提供 `rule_id`、`rule_raw` 和 `rule_text`，不提供案件 evidence。运行时再把
当前 `MatchedRule` 传入 checker。规则文本不变时可跨案件复用；规则变化时哈希自动变化。

## 8. 模型边界

步骤二和步骤三共享 `src/llm.py`，统一连接一个 Qwen3-8B vLLM 服务：

- 步骤二：只做候选相关性重排；
- 步骤三：生成 checker；
- 步骤三可选：复核 checker 结果。

程序不会自动启动 vLLM。服务地址、served model name 和 API key 由 `LOCAL_LLM_*` 配置。

## 9. 安全边界

生成代码先进行 AST 检查，再在临时目录的限时子进程中执行，并校验返回类型、`rule_id`、
证据下标及引用原文。该进程隔离不是完整安全沙箱，生产部署仍应使用禁网、只读文件系统、
资源限额和非特权用户容器。
