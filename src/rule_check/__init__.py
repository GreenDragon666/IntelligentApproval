"""步骤三：按检查方式路由到全局确定性执行器或本地 LLM 语义判定器。"""

from .cache import DecisionCache
from .methods import is_structured_method, normalize_check_method
from .semantic import evaluate_semantic
from .structured import evaluate_structured

__all__ = [
    "DecisionCache",
    "evaluate_semantic",
    "evaluate_structured",
    "is_structured_method",
    "normalize_check_method",
]
