"""在限时子进程中验证和执行本地模型生成的 checker。"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from config import settings
from ..schema import MatchedRule, RuleResult

_CODE_BLOCK = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)

_FORBIDDEN_MODULES = {
    "asyncio",
    "http",
    "importlib",
    "multiprocessing",
    "os",
    "pathlib",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "sys",
    "urllib",
}
_FORBIDDEN_CALLS = {"__import__", "compile", "eval", "exec", "input", "open"}
_FORBIDDEN_ATTRIBUTES = {
    "connect",
    "popen",
    "read_bytes",
    "read_text",
    "request",
    "run",
    "system",
    "urlopen",
    "write_bytes",
    "write_text",
}

_RUNNER = '''\
import json
from pathlib import Path

import candidate
from src.schema import MatchedRule, RuleResult

rule = MatchedRule.from_dict(json.loads(Path("input.json").read_text(encoding="utf-8")))
result = candidate.check(rule)
if not isinstance(result, RuleResult):
    raise TypeError(f"check 必须返回 RuleResult，实际为 {type(result)!r}")
Path("output.json").write_text(
    json.dumps(result.to_dict(), ensure_ascii=False), encoding="utf-8"
)
'''


def extract_code(text: str) -> str:
    match = _CODE_BLOCK.search(text)
    return (match.group(1) if match else text).strip()


def validate_source(code: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"Python 语法错误: {exc}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] in _FORBIDDEN_MODULES:
                    return False, f"禁止导入模块: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".", 1)[0]
            if module in _FORBIDDEN_MODULES:
                return False, f"禁止导入模块: {node.module}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_CALLS:
                return False, f"禁止调用: {node.func.id}"
            if isinstance(node.func, ast.Attribute) and node.func.attr in _FORBIDDEN_ATTRIBUTES:
                return False, f"禁止调用属性: {node.func.attr}"
    return True, ""


def run_checker(
    code: str,
    rule: MatchedRule,
    timeout: int | None = None,
) -> tuple[RuleResult | None, str]:
    """执行 checker，返回 ``(结果, 错误)``，不会向上抛 checker 异常。"""

    safe, source_error = validate_source(code)
    if not safe:
        return None, source_error
    project_root = Path(__file__).resolve().parents[2]
    timeout = timeout or settings.checker_timeout
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            work = Path(temp_dir)
            (work / "candidate.py").write_text(code, encoding="utf-8")
            (work / "runner.py").write_text(_RUNNER, encoding="utf-8")
            (work / "input.json").write_text(
                json.dumps(rule.to_dict(), ensure_ascii=False), encoding="utf-8"
            )
            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join(
                value for value in (str(project_root), env.get("PYTHONPATH", "")) if value
            )
            proc = subprocess.run(
                [sys.executable, "runner.py"],
                cwd=work,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if proc.returncode != 0:
                return None, (proc.stdout + proc.stderr).strip()
            output_path = work / "output.json"
            if not output_path.is_file():
                return None, "checker 未生成 output.json"
            result = RuleResult.from_dict(
                json.loads(output_path.read_text(encoding="utf-8"))
            )
    except subprocess.TimeoutExpired:
        return None, f"checker 执行超过 {timeout} 秒"
    except Exception as exc:
        return None, f"checker 执行失败: {exc!r}"

    if result.rule_id != rule.rule_id:
        return None, f"checker 返回 rule_id={result.rule_id}，期望 {rule.rule_id}"
    for finding in result.findings:
        if finding.evidence_index < 0 or finding.evidence_index >= len(rule.evidence):
            return None, f"Finding.evidence_index 越界: {finding.evidence_index}"
        source_text = rule.evidence[finding.evidence_index].text
        if not finding.quote:
            return None, "Finding.quote 不能为空"
        if finding.quote not in source_text:
            return None, "Finding.quote 不是对应 evidence.text 的原文片段"
    return result, ""


def validate_checker(code: str, rule: MatchedRule) -> tuple[bool, str]:
    result, error = run_checker(code, rule)
    return result is not None, error
