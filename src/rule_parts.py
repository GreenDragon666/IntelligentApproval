"""拆分规则表中混合存放的描述、法规依据、公式和开发说明。"""

from __future__ import annotations

import re

_HEADING = re.compile(r"【(?P<title>[^】]+)】")


def rule_blocks(rule_text: str) -> dict[str, str]:
    """按【标题】拆块；同名块按原顺序拼接。"""
    text = str(rule_text or "")
    matches = list(_HEADING.finditer(text))
    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group("title").strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            blocks[title] = "\n".join(value for value in (blocks.get(title), body) if value)
    return blocks


def legal_basis(rule_text: str) -> str:
    """只返回明确标为“法规依据”的块，不混入公式、量化标准或开发说明。"""
    return rule_blocks(rule_text).get("法规依据", "")


def rule_description(rule_text: str) -> str:
    return rule_blocks(rule_text).get("描述", "")
