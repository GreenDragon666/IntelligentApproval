"""步骤一、二共享的内部数据结构；正式输出使用 ``src.rule_schema``。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .rule_parts import legal_basis


@dataclass(frozen=True)
class PageText:
    """归一化单页文本，同时保存来源页和可选正文印刷页。"""
    pdf_page: int
    document_page: int | None
    text: str
    page_label: str = "PDF"

    def to_dict(self) -> dict:
        """转换为可写入调试 JSON 的普通字典。"""
        return asdict(self)


@dataclass(frozen=True)
class DocumentSection:
    """用于规则匹配的连续 PDF 章节块及其双页码范围。"""
    title: str
    pdf_start: int
    pdf_end: int
    document_start: int | None
    document_end: int | None
    text: str

    def to_dict(self) -> dict:
        """转换为可写入 ``sections.json`` 的普通字典。"""
        return asdict(self)


@dataclass(frozen=True)
class PolicyRule:
    """从政策 JSON/XLSX 读取的规则及只用于召回的提示字段。"""
    rule_id: int
    rule_raw: str
    rule_text: str
    match_hints: list[str] = field(default_factory=list)
    check_method: str = "大模型分析"
    structured_fields: str = ""

    @property
    def query_text(self) -> str:
        """返回规则原文、法规依据和可选章节提示；公式/开发说明不参与。"""
        return "\n".join(value for value in [self.rule_raw, legal_basis(self.rule_text), *self.match_hints] if value)


@dataclass(frozen=True)
class SectionCandidate:
    """一条政策规则召回的招标章节及其字符级相关分数。"""
    section: DocumentSection
    score: float

    def to_dict(self) -> dict:
        """输出候选定位和舍入后的分数，不重复写完整章节原文。"""
        return {
            "title": self.section.title,
            "pdf_start": self.section.pdf_start,
            "pdf_end": self.section.pdf_end,
            "score": round(self.score, 6),
        }
