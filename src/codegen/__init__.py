"""Code-Agent 代码生成流水线（编写期使用，非运行时）。

职责：读一条规则 Markdown → 本地模型生成 checker → 沙箱执行单测 → 失败带错误反馈重试
→ 通过后落库为版本化 checker（供人工 review 后并入 src/checkers）。
"""
