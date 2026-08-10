"""把规则文本翻译为全局可复用 checker 的提示词。"""

from __future__ import annotations

SYSTEM = "你是资深 Python 工程师，负责把招标审批规则翻译成确定性校验代码。只输出代码。"

CHECKER_CONTRACT = '''\
生成模块必须满足：
1. 从 src.rule_schema 导入 MatchedRule, RuleResult, Status, Finding。
2. 暴露函数 check(rule: MatchedRule) -> RuleResult；不使用注册装饰器。
3. 只能依据 rule.rule_text 编写通用逻辑，运行时读取 rule.evidence；禁止写入某个案件的原文。
4. Finding.evidence_index 必须指向 rule.evidence 的下标，quote 必须来自对应 evidence.text。
5. 输入不足时返回 Status.INSUFFICIENT_INPUT，不得猜测或抛异常。
6. 违规、预警、通过分别使用 Status.VIOLATION、Status.WARNING、Status.PASS。
7. 只用 Python 标准库；禁止网络、文件读写、子进程、动态执行和调用大模型。
8. 返回结果的 rule_id 必须等于 rule.rule_id。
'''


def build_generate_prompt(
    rule_id: int,
    rule_raw: str,
    rule_text: str,
    feedback: str = "",
) -> str:
    feedback_block = f"\n额外修正要求：\n{feedback}\n" if feedback else ""
    return f'''\
请为下面规则生成一个完整 Python checker 模块。

规则序号：{rule_id}
重点排查情形：{rule_raw}

规则内容：
"""
{rule_text}
"""
{feedback_block}
{CHECKER_CONTRACT}

只输出一个 ```python 代码块，不要解释。
'''


def build_retry_prompt(
    rule_id: int,
    rule_raw: str,
    rule_text: str,
    prev_code: str,
    error: str,
    feedback: str = "",
) -> str:
    return f'''\
上一版 checker 未通过验证，请输出修正后的完整模块。

规则序号：{rule_id}
重点排查情形：{rule_raw}
规则内容：
"""
{rule_text}
"""

上一版代码：
```python
{prev_code}
```

失败信息：
"""
{error}
"""

额外修正要求：
{feedback or "无"}

{CHECKER_CONTRACT}

只输出一个 ```python 代码块，不要解释。
'''
