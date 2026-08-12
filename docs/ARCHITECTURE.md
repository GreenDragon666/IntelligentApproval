# 系统架构

## 三步边界

| 步骤 | 包 | 输入 | 输出 |
|---|---|---|---|
| 一：目录提取 | `src/dir_extr/` | 招标文档 | 分页文本、页码、目录、章节 |
| 二：内容匹配 | `src/cont_match/` | 章节、`--policy-rules` | `MatchedCase` / `rules_matched.json` |
| 三：规则校验 | `src/rule_check/`、`src/engine.py` | `MatchedCase` | 判定缓存、审批报告 |

步骤二从规则表读取 `检查方式` 与`结构化数据展示字段`，使用字符与 embedding 混合召回，
并在启用 `--use-llm` 时并发重排候选章节。

内容匹配使用三级流程：

1. 以 `rule_raw` 决定主题，并从 `rule_text` 中只拆取 `【法规依据】` 作为辅助查询；
2. 计算字符 2/3-gram TF-IDF 分数，同时将长章节切片并用 BGE-M3 批量计算向量相似度；默认按
   `0.55 × lexical + 0.45 × embedding` 融合后取 top-k；
3. 每个长章节截取与查询重叠最高的窗口，交给本地 Qwen 选择至多3个 evidence。

`rule_text` 中的公式、开发说明、其他生成块及 `structured_fields` 不参与第一阶段召回。Qwen 返回空选择时保留已达到
`minimum_score` 的融合候选作为兜底；这只表示保留候选供步骤三判断，不表示候选必然违规。

## 步骤三路由

```text
MatchedRule.check_method
  │
  ├─ 包含“结构化数据检查”
  │    → structured.py
  │    → 从 rule_raw + 法规依据派生操作、阈值和方向
  │    → 正则提取金额/比例/日期
  │    → 字段名不一致时由 Qwen 选择正则候选位置
  │    → 全局代码执行计算
  │    → Qwen 解释结果是否有证据支持，但不修改状态
  │
  └─ 其他检查方式
       → semantic.py
       → 本地 Qwen 一次完成短 JSON 判定与解释
       → quote/evidence_index/status/confidence 校验
```

组合检查方式中只要含有 `结构化数据检查`，就走确定性执行器。这是当前明确的产品路由，不会在
运行时让模型改写。

`rule_raw` 决定审查主题，法规依据补充具体要求，`【描述】`只作适用场景说明，`check_method` 仅用于路由。字段语义映射时，模型收到的是将
实际值替换为 `<VALUE>` 的上下文，只返回字段与候选下标；最终值仍来自正则。无法从两项依据
派生并复核结构化条件、字段映射不完整或步骤二没有召回证据时返回 `warning`，而不是把生成字段写成
业务 `insufficient_input`。只有 `rule_raw` 或法规依据明确要求的外部资料或比较对象确实未提供时，语义判定
才允许返回 `insufficient_input`。

embedding 只改进步骤二召回，不决定步骤三状态。非结构化规则的同一次 Qwen 调用同时返回状态、
简要结论和分析；结构化状态由确定性程序给出，随后由 `explainer.py` 增加分析与一致性意见，模型意见
不会覆盖原状态。

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
- 判定合理性分析；
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
