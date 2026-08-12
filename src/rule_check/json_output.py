"""统一提取本地 LLM 输出中的 JSON 对象。"""

from __future__ import annotations

import json
import re

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json_object(raw: str, *, label: str = "LLM 输出") -> dict:
    """兼容纯 JSON、Markdown 代码块、前后说明文字和 think 标签。"""
    text = str(raw or "").strip()
    fenced = _JSON_BLOCK.search(text)
    if fenced:
        try:
            value = json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(value, dict):
                return value
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    if not text:
        raise ValueError(f"{label}为空")
    raise ValueError(f"{label}中没有可解析的 JSON 对象")
