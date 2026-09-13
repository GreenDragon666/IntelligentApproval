"""步骤一、二共享的内部数据结构；正式输出使用 ``src.rule_schema``。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .rule_parts import legal_basis, rule_description


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
        """返回面向语义召回的短查询；避免长法规条文淹没审查主题。"""
        return "\n".join(value for value in [self.rule_raw, rule_description(self.rule_text), *self.match_hints] if value)

    @property
    def query_variants(self) -> list[tuple[str, float]]:
        """返回独立编码的查询变体及权重，公式和开发说明始终不参与。"""
        variants: list[tuple[str, float]] = [(self.rule_raw, 1.0)]
        description = rule_description(self.rule_text)
        if description:
            variants.append((description, 0.9))
        variants.extend((hint, 1.0) for hint in self.match_hints if hint)
        basis = legal_basis(self.rule_text)
        if basis:
            variants.append((basis, 0.55))
        unique: list[tuple[str, float]] = []
        seen: set[str] = set()
        for text, weight in variants:
            compact = text.strip()
            if compact and compact not in seen:
                seen.add(compact)
                unique.append((compact, weight))
        return unique


@dataclass(frozen=True)
class SectionCandidate:
    """一条政策规则召回的章节及字符、向量和融合相关分数。"""
    section: DocumentSection
    score: float
    lexical_score: float | None = None
    embedding_score: float | None = None

    def to_dict(self) -> dict:
        """输出候选定位和舍入后的分数，不重复写完整章节原文。"""
        return {
            "title": self.section.title,
            "pdf_start": self.section.pdf_start,
            "pdf_end": self.section.pdf_end,
            "score": round(self.score, 6),
            "lexical_score": round(self.lexical_score, 6) if self.lexical_score is not None else None,
            "embedding_score": round(self.embedding_score, 6) if self.embedding_score is not None else None,
        }
