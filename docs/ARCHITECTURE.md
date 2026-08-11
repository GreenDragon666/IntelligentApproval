# 系统架构

## 三步边界

| 步骤 | 包 | 输入 | 输出 |
|---|---|---|---|
| 一：目录提取 | `src/dir_extr/` | 招标文档 | 分页文本、页码、目录、章节 |
| 二：内容匹配 | `src/cont_match/` | 章节、`--policy-rules` | `MatchedCase` / `rules_matched.json` |
| 三：规则校验 | `src/rule_check/`、`src/engine.py` | `MatchedCase` | 判定缓存、审批报告 |

步骤一、二的主要算法保持不变。步骤二新增两项职责：从规则表读取 `检查方式` 与
`结构化数据展示字段`；并在启用 `--use-llm` 时并发重排候选章节。

## 步骤三路由

```text
MatchedRule.check_method
  │
  ├─ 包含“结构化数据检查”
  │    → structured.py
  │    → 解释规则公式
  │    → 金额/比例/百分比/日期/关键词操作
  │
  └─ 其他检查方式
       → semantic.py
       → 本地 Qwen 短 JSON 判定
       → quote/evidence_index/status/confidence 校验
```

组合检查方式中只要含有 `结构化数据检查`，就走确定性执行器。这是当前明确的产品路由，不会在
运行时让模型改写。

结构化执行器无法可靠取得所有必要操作数时返回 `insufficient_input`。这是业务输入缺失，不是
流程异常，也不能当成规则通过。

## 并发和 vLLM

步骤二用 `ThreadPoolExecutor` 并发调用候选重排，步骤三并发执行各规则。结构化规则在本机快速
完成，语义规则通过共享 OpenAI/httpx 连接池调用 vLLM。

默认并发：

- `MATCHING_WORKERS=4`
- `SEMANTIC_WORKERS=4`

语义判定固定 `/no_think`、`temperature=0`、短输出。静态系统提示放在共同前缀中，便于 vLLM
前缀缓存；不同规则并发到达后可由 vLLM 连续批处理。

`src/llm.py` 的 httpx 客户端设置 `trust_env=False`，本机 vLLM 请求不会读取 SOCKS/HTTP 代理。

## 缓存与回滚

`DecisionCache` 的摘要输入包括：

- 执行器版本；
- 规则序号、原文、完整逻辑；
- 检查方式、结构化字段；
- 当前案件 evidence 及定位。

因此缓存是案件判定缓存，不是全局规则代码缓存。规则或原文变化时自动产生新 key，不会误用旧
结果。

`--force-recheck` 重写当前 key 前，会把旧结果复制到 `decision_cache/history/`；
`--rollback-rules` 恢复指定规则最近一版历史。写入使用临时文件加原子替换，中断不会留下半个
JSON。

## 输出验证

语义判定必须返回：

- 合法 `status`；
- 结论摘要；
- 0～1 的置信度；
- 缺失输入；
- 违规/预警时至少一条 finding；
- finding 的 `evidence_index` 不越界；
- `quote` 是对应 evidence.text 中的连续原文。

输出校验失败时只进行一次短 JSON 修正，不再生成或执行 Python。

## 旧版本兼容

- 旧 `rules_matched.json` 没有 `check_method` 时按 `大模型分析` 读取。
- 旧 JSON 使用 `--input` 时可同时传 `--policy-rules`，按 `rule_id` 补齐检查方式和结构化字段，不重跑步骤一、二。
- `--no-generate` 是 `--no-llm-check` 的兼容别名。
- `--force-regenerate` 是 `--force-recheck` 的兼容别名。
- `--checker-dir` 是 `--check-cache-dir` 的兼容别名。

旧的按规则生成 Python checker 生产模块已移除，避免两个第三步实现并存。
