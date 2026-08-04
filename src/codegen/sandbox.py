"""沙箱：在隔离子进程中执行生成的 checker + 单测，返回通过与否及错误。

安全性：生成代码由本地模型产出，不完全可信。此处用子进程 + 超时隔离；
生产环境建议进一步在容器（如受限 Docker）内执行。
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

_CODE_BLOCK = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


def extract_code(text: str) -> str:
    """从模型输出中抽取代码块；无围栏则原样返回。"""
    m = _CODE_BLOCK.search(text)
    return (m.group(1) if m else text).strip()


def run_checker_test(code: str, test_code: str, timeout: int = 30) -> tuple[bool, str]:
    """把 checker 代码与测试代码写入临时文件并在子进程执行。

    test_code 约定：import 生成的 checker 模块（名为 candidate）后自行断言，
    退出码 0 视为通过。返回 (success, output)。
    """
    project_root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        (tdp / "candidate.py").write_text(code, encoding="utf-8")
        (tdp / "run_test.py").write_text(test_code, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(tdp / "run_test.py")],
            cwd=str(tdp),
            env={"PYTHONPATH": f"{project_root}:{td}"},
            capture_output=True, text=True, timeout=timeout,
        )
    ok = proc.returncode == 0
    return ok, (proc.stdout + proc.stderr).strip()
