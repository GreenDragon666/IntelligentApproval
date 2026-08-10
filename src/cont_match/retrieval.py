"""无领域词表的字符级规则—章节候选召回。"""

from __future__ import annotations

import math
import re
from collections import Counter

from ..page_schema import DocumentSection, PolicyRule, SectionCandidate

_LEGAL_BASIS = re.compile(r"【法规依据】.*?(?=【公式】|【开发说明】|$)", re.DOTALL)


def _terms(text: str) -> Counter[str]:
    """将文本转换为中文/英文字符 n-gram 词频，法规依据块不参与召回。"""
    text = _LEGAL_BASIS.sub(" ", str(text or "").lower())
    compact = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)
    terms: Counter[str] = Counter()
    for size in (2, 3):
        for index in range(max(0, len(compact) - size + 1)):
            terms[compact[index:index + size]] += 1
    for token in re.findall(r"[a-z]+\d*|\d+(?:\.\d+)*", text):
        if len(token) >= 2:
            terms[token] += 2
    return terms


class LexicalSectionMatcher:
    """领域无关的字符 TF-IDF 章节召回器。"""
    def __init__(self, sections: list[DocumentSection]):
        """预计算章节/标题词频和全语料 IDF。"""
        if not sections:
            raise ValueError("没有可匹配章节")
        self.sections = sections
        self.section_terms = [_terms(section.title + "\n" + section.text) for section in sections]
        self.title_terms = [_terms(section.title) for section in sections]
        document_frequency: Counter[str] = Counter()
        for terms in self.section_terms:
            document_frequency.update(terms.keys())
        total = len(sections)
        self.idf = {
            term: math.log((total + 1) / (frequency + 1)) + 1
            for term, frequency in document_frequency.items()
        }

    def _cosine(self, left: Counter[str], right: Counter[str]) -> float:
        """计算带对数词频和 IDF 的稀疏余弦相似度。"""
        shared = set(left) & set(right)
        if not shared:
            return 0.0

        def weight(term: str, count: int) -> float:
            """计算单个词项的对数 TF-IDF 权重。"""
            return (1.0 + math.log(count)) * self.idf.get(term, 1.0)

        numerator = sum(
            weight(term, left[term]) * weight(term, right[term])
            for term in shared
        )
        left_norm = math.sqrt(sum(weight(term, count) ** 2 for term, count in left.items()))
        right_norm = math.sqrt(sum(weight(term, count) ** 2 for term, count in right.items()))
        if not left_norm or not right_norm:
            return 0.0
        return numerator / (left_norm * right_norm)

    def rank(self, rule: PolicyRule, top_k: int = 5) -> list[SectionCandidate]:
        """综合正文与标题相似度，返回分数大于零的 top-k 章节。"""
        # 模块/章节提示比法规长文更能定位原文，因此在查询中适度加权；不引入任何行业词表。
        query = _terms(
            rule.rule_raw
            + "\n"
            + rule.rule_text
            + "\n"
            + "\n".join(rule.match_hints * 3)
        )
        candidates: list[SectionCandidate] = []
        for section, terms, title_terms in zip(
            self.sections,
            self.section_terms,
            self.title_terms,
        ):
            content_score = self._cosine(query, terms)
            title_score = self._cosine(query, title_terms)
            score = 0.75 * content_score + 0.25 * title_score
            candidates.append(SectionCandidate(section=section, score=float(score)))
        candidates.sort(key=lambda item: item.score, reverse=True)
        return [item for item in candidates[:top_k] if item.score > 0]
