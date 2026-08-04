"""代码生成 prompt 模板。

关键约束写进 prompt，保证产出的 checker 签名统一、可直接注册、可被沙箱单测。
"""

from __future__ import annotations

SYSTEM = "你是资深 Python 工程师，负责把招标审批规则翻译成确定性校验代码。只输出代码，不要解释。"

CHECKER_CONTRACT = '''\
# 生成的 checker 必须满足以下契约：
# 1. 从 src.registry 导入 register，从 src.schema 导入 TenderContext, RuleResult, Status, Evidence
# 2. 用 @register("<rule_id>") 装饰一个函数 check(ctx: TenderContext) -> RuleResult
# 3. 逻辑严格依据规则的【公式】与量化标准段；输入字段取自 ctx（full_text / sections / fields / tables / references）
# 4. 所需输入缺失时返回 RuleResult(rule_id, Status.NA, ...)，不得抛异常
# 5. 违规=Status.VIOLATION，预警=Status.WARNING，通过=Status.PASS
# 6. 命中处填 Evidence(text=原文片段, location=位置, detail=说明)，量化值放入 metrics
# 7. 只用 Python 标准库；需语义相似度时调用 ctx.references 中注入的 embedder（若无则跳过该分支）
'''

TEMPLATE = '''\
下面是一条招标文件审批规则（Markdown），请为它生成 checker 代码。

规则 id：{rule_id}

规则内容：
"""
{rule_text}
"""

{contract}

只输出一个完整的 Python 模块代码（```python 代码块），不要任何额外文字。
'''

RETRY_TEMPLATE = '''\
上一版代码未通过单元测试，请修正。

规则 id：{rule_id}

你上一版代码：
```python
{prev_code}
```

单元测试报错：
"""
{error}
"""

请输出修正后的完整模块代码（```python 代码块），保持前述契约不变。
'''


def build_generate_prompt(rule_id: str, rule_text: str) -> str:
    return TEMPLATE.format(rule_id=rule_id, rule_text=rule_text, contract=CHECKER_CONTRACT)


def build_retry_prompt(rule_id: str, prev_code: str, error: str) -> str:
    return RETRY_TEMPLATE.format(rule_id=rule_id, prev_code=prev_code, error=error)
