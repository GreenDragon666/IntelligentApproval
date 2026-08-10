"""从正式 JSON 或 XLSX 加载政策规则。"""

from __future__ import annotations

import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ..page_schema import PolicyRule

_ID_COLUMNS = ("序号", "rule_id", "规则序号")
_RAW_COLUMNS = ("重点排查情形", "rule_raw", "规则原文", "规则描述")
_TEXT_COLUMNS = ("触发逻辑公式", "rule_text", "规则逻辑描述")
_HINT_COLUMNS = (
    "触发逻辑",
    "非结构化文件中模块",
    "非结构化文件",
    "检查方式",
    "结构化数据展示字段",
    "章节",
    "关键词",
)


def _first(row: dict[str, Any], names: tuple[str, ...]) -> str:
    """从兼容列名中取第一个非空值。"""
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _rule_id(value: str, fallback: int) -> int:
    """从单元格中解析整数序号，空值时使用行号。"""
    if not value:
        return fallback
    match = re.search(r"\d+", value)
    if not match:
        raise ValueError(f"无法解析规则序号: {value!r}")
    return int(match.group())


def _rows_to_rules(rows: list[dict[str, Any]]) -> list[PolicyRule]:
    """将表格/JSON 行转成规则，收集匹配提示并校验重复序号。"""
    rules: list[PolicyRule] = []
    for row_number, row in enumerate(rows, start=1):
        rule_raw = _first(row, _RAW_COLUMNS)
        rule_text = _first(row, _TEXT_COLUMNS)
        if not rule_raw and not rule_text:
            continue
        if not rule_raw or not rule_text:
            raise ValueError(f"第 {row_number} 条规则缺少 rule_raw 或 rule_text")
        hints = []
        for column in _HINT_COLUMNS:
            value = str(row.get(column) or "").strip()
            if value and value not in hints:
                hints.append(value)
        rules.append(
            PolicyRule(
                rule_id=_rule_id(_first(row, _ID_COLUMNS), row_number),
                rule_raw=rule_raw,
                rule_text=rule_text,
                match_hints=hints,
            )
        )
    ids = [rule.rule_id for rule in rules]
    if not rules:
        raise ValueError("规则文件中没有可用规则")
    if len(ids) != len(set(ids)):
        raise ValueError("规则序号重复")
    return rules


def _load_json(path: Path) -> list[dict[str, Any]]:
    """读取规则数组或正式案件对象中的 ``rules`` 数组。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        rows = data.get("rules")
    else:
        rows = data
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("JSON 必须是规则数组，或包含 rules 数组的对象")
    return rows


def _column_index(reference: str) -> int:
    """将 XLSX 的 A/AA 等列引用转换成零基下标。"""
    letters = re.match(r"[A-Z]+", reference)
    if not letters:
        raise ValueError(f"非法单元格引用: {reference}")
    index = 0
    for char in letters.group():
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def _load_xlsx(path: Path) -> list[dict[str, Any]]:
    """直接解析 XLSX ZIP/XML 的第一个工作表，不依赖 openpyxl。"""
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    relationship_key = (
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    )
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relation_map = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in strings:
                shared.append("".join(node.text or "" for node in item.iter(namespace + "t")))
        sheets = workbook.find(namespace + "sheets")
        if sheets is None or not list(sheets):
            raise ValueError("XLSX 中没有工作表")
        relation_id = list(sheets)[0].attrib[relationship_key]
        target = relation_map[relation_id].lstrip("/")
        sheet_path = target if target.startswith("xl/") else "xl/" + target
        sheet = ET.fromstring(archive.read(sheet_path))
        matrix: list[list[str]] = []
        for row in sheet.iter(namespace + "row"):
            values: dict[int, str] = {}
            for cell in row:
                if cell.tag != namespace + "c":
                    continue
                index = _column_index(cell.attrib.get("r", ""))
                cell_type = cell.attrib.get("t")
                value_node = cell.find(namespace + "v")
                if value_node is not None:
                    value = value_node.text or ""
                    if cell_type == "s":
                        value = shared[int(value)]
                else:
                    inline = cell.find(namespace + "is")
                    value = (
                        "".join(node.text or "" for node in inline.iter(namespace + "t"))
                        if inline is not None
                        else ""
                    )
                values[index] = value
            if values:
                width = max(values) + 1
                matrix.append([values.get(index, "") for index in range(width)])
    if not matrix:
        return []
    headers = [str(value).strip().lstrip("\ufeff") for value in matrix[0]]
    rows: list[dict[str, Any]] = []
    for values in matrix[1:]:
        rows.append(
            {
                header: values[index] if index < len(values) else ""
                for index, header in enumerate(headers)
                if header
            }
        )
    return rows


def load_policy_rules(path: str | Path) -> list[PolicyRule]:
    """政策规则加载入口；当前只接受正式 JSON 或 XLSX。"""
    rule_path = Path(path)
    if not rule_path.is_file():
        raise FileNotFoundError(rule_path)
    suffix = rule_path.suffix.lower()
    if suffix == ".json":
        rows = _load_json(rule_path)
    elif suffix == ".xlsx":
        rows = _load_xlsx(rule_path)
    else:
        raise ValueError(f"不支持的规则文件格式: {suffix}")
    return _rows_to_rules(rows)
