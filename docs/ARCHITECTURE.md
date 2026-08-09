# 架构说明

## 1. 模块

| 路径 | 职责 |
|---|---|
| `src/preprocess/pdf.py` | 逐页抽取 PDF，保留 PDF 物理页和可选正文印刷页 |
| `src/preprocess/sections.py` | 根据 PDF 书签或通用标题拆分章节，限制单段最大页数 |
| `src/preprocess/rules.py` | 从正式 JSON 或政策 XLSX 加载规则，不读取旧匹配结果列 |
| `src/preprocess/retrieval.py` | 无领域词表的字符级 TF-IDF top-k 召回 |
| `src/preprocess/llm_matcher.py` | 可选用本地 Qwen3-7B 对候选重排和拒绝无关候选 |
| `src/preprocess/pipeline.py` | 组装、校验并写出正式 `MatchedCase` JSON 和追溯产物 |
| `src/schema.py` | 正式案件输入、checker 输出、运行记录和汇总报告契约 |
| `src/checker_store.py` | 根据规则哈希保存、发现和复用全局 checker |
| `src/codegen/` | LangGraph 生成、契约验证、错误反馈和重试 |
| `src/engine.py` | 案件级编排：生成/复用、执行、复核、定向迭代 |
| `src/reviewer.py` | 可选的本地 LLM 结果复核 |
| `src/report.py` | JSON 和 Markdown 报告 |
| `src/llm.py` | 本地 vLLM 客户端 |
| `prepare_case.py` | 步骤一、二命令行入口 |
| `main.py` | 完整案件入口 |
| `gen_checker.py` | 单条规则 checker 生成入口 |

## 2. 全链路

```text
政策规则 JSON/XLSX ─┐
                    ├─→ 字符级召回 ─→ 可选本地Qwen重排 ─→ MatchedCase JSON
招标 PDF ─→ 页文本 ─→ 章节 ────────────────────────────────┘
                                                           ↓
                          checker缓存/生成 ─→ 隔离执行 ─→ 汇总报告
```

步骤一、二只负责查找可供审查的招标原文，不直接给出违规结论。步骤三 checker 只消费
正式 JSON，不依赖中间章节或匹配产物。

纯本地模式使用 TF-IDF 结果直接生成 evidence，适合链路调试和高召回候选输出；本地
Qwen3-7B 模式允许从候选中返回空数组，因此更适合正式运行。模型故障默认降级并记录，
`--strict-llm` 可改为失败即中止。

## 3. 输入

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

`source` 只保留 `file`。详细示例见 `docs/MATCHED_JSON.md`。

## 4. Checker 复用

规范化 `rule_text` 后计算 SHA-256：

```text
rule_<rule_id>_<digest前12位>.py
```

生成 checker 时只向模型提供 `rule_id`、`rule_raw` 和 `rule_text`，不提供案件
evidence。生成函数固定为：

```python
def check(rule: MatchedRule) -> RuleResult:
    ...
```

运行时传入当前案件的 `MatchedRule`。这样规则稳定时可以跨案件复用，规则内容变化时
会自动切换到新的哈希版本。

## 5. 执行与反馈

```text
读取 MatchedCase
  → evidence 为空：insufficient_input
  → 查找 checker
      ├── 已存在：复用
      └── 不存在：本地模型生成
  → 临时目录子进程执行
  → 校验 RuleResult 契约、rule_id、证据下标和原文引用
  → 可选 LLM 复核
      ├── 通过：进入汇总
      └── 不通过：反馈 → 只重新生成当前规则 → 再执行/复核
```

代码异常也会作为反馈触发一次定向重新生成。所有规则互相隔离，单条失败不终止整个案件。

## 6. 结果状态

| 状态 | 含义 |
|---|---|
| `violation` | 规则判定违规 |
| `warning` | 需要人工关注 |
| `pass` | 规则判定通过 |
| `insufficient_input` | 没有原文或规则所需信息不足 |
| `error` | checker 缺失、生成失败或执行失败 |

案件总体状态为 `violation`、`warning`、`pass` 或 `partial`。

## 7. 无模型模式

`main.py --no-generate` 不会访问本地模型。已有 checker 仍会执行；缺少 checker 的规则
记录为 `error`，空 evidence 记录为 `insufficient_input`。该模式用于本机框架检查和服务器
模型服务不可用时的降级诊断。

## 8. 安全

生成代码在临时目录的限时子进程中运行，并校验输出契约。进程级隔离不是完整安全沙箱，
生产部署应进一步使用禁网、只读文件系统、资源限额和非特权用户的容器。
