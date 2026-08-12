"""字符 TF-IDF 与本地 embedding 融合的规则—章节候选召回。"""

from __future__ import annotations

import math
import re
from collections import Counter

from config import settings
from ..llm import Embedder
from ..page_schema import DocumentSection, PolicyRule, SectionCandidate
from ..rule_parts import legal_basis

def _terms(text: str) -> Counter[str]:
    """将已选定的查询/章节文本转换为中文、英文字符 n-gram。"""
    text = str(text or "").lower()
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

    def scores(self, rule: PolicyRule) -> list[float]:
        """综合正文与标题相似度，返回与章节顺序一致的字符分数。"""
        # 模块/章节提示比法规长文更能定位原文，因此在查询中适度加权；不引入任何行业词表。
        # rule_raw 决定审查主题；法规依据补充具体法律概念、数字和期限。
        # 公式、量化标准块、开发说明和结构化字段不参与召回。
        raw_query = _terms("\n".join([rule.rule_raw] * 3 + rule.match_hints))
        legal_query = _terms(legal_basis(rule.rule_text))
        scores: list[float] = []
        for section, terms, title_terms in zip(
            self.sections,
            self.section_terms,
            self.title_terms,
        ):
            raw_content_score = self._cosine(raw_query, terms)
            legal_content_score = self._cosine(legal_query, terms) if legal_query else 0.0
            title_score = self._cosine(raw_query, title_terms)
            score = 0.60 * raw_content_score + 0.15 * legal_content_score + 0.25 * title_score
            scores.append(float(score))
        return scores

    def rank(self, rule: PolicyRule, top_k: int = 5) -> list[SectionCandidate]:
        """返回字符分数大于零的 top-k 章节。"""
        candidates = [SectionCandidate(section=section, score=score, lexical_score=score) for section, score in zip(self.sections, self.scores(rule))]
        candidates.sort(key=lambda item: item.score, reverse=True)
        return [item for item in candidates[:top_k] if item.score > 0]


def _section_chunks(section: DocumentSection, chunk_chars: int, overlap: int) -> list[str]:
    """切分长章节，让末尾相关内容也能参与向量召回。"""
    text = section.text.strip()
    if not text:
        return [section.title]
    step = chunk_chars - overlap
    chunks = []
    for start in range(0, len(text), step):
        body = text[start:start + chunk_chars]
        chunks.append(f"{section.title}\n{body}")
        if start + chunk_chars >= len(text):
            break
    return chunks


class HybridSectionMatcher:
    """批量编码章节切片和规则查询，再融合字符与 embedding 分数。"""

    def __init__(self, sections: list[DocumentSection], embedder: Embedder | None = None):
        if not 0 <= settings.embed_weight <= 1:
            raise ValueError("LOCAL_EMBED_WEIGHT 必须在 0 到 1 之间")
        if settings.embed_chunk_chars < 1 or settings.embed_chunk_overlap < 0 or settings.embed_chunk_overlap >= settings.embed_chunk_chars:
            raise ValueError("embedding 切片长度必须大于 0，重叠长度须小于切片长度")
        self.sections = sections
        self.lexical = LexicalSectionMatcher(sections)
        self.embedder = embedder or Embedder()
        chunk_texts: list[str] = []
        self.chunk_owners: list[int] = []
        for section_index, section in enumerate(sections):
            for chunk in _section_chunks(section, settings.embed_chunk_chars, settings.embed_chunk_overlap):
                chunk_texts.append(chunk)
                self.chunk_owners.append(section_index)
        self.chunk_embeddings = self.embedder.encode(chunk_texts)

    def rank_all(self, rules: list[PolicyRule], top_k: int = 5) -> list[list[SectionCandidate]]:
        """一次编码全部规则，并对每条规则返回融合分数 top-k。"""
        if not rules:
            return []
        import numpy as np

        query_embeddings = self.embedder.encode([rule.query_text for rule in rules])
        similarities = np.asarray(query_embeddings) @ np.asarray(self.chunk_embeddings).T
        results: list[list[SectionCandidate]] = []
        lexical_weight = 1.0 - settings.embed_weight
        for rule_index, rule in enumerate(rules):
            embedding_scores = [0.0] * len(self.sections)
            for chunk_index, section_index in enumerate(self.chunk_owners):
                score = max(0.0, float(similarities[rule_index, chunk_index]))
                if score > embedding_scores[section_index]:
                    embedding_scores[section_index] = score
            lexical_scores = self.lexical.scores(rule)
            candidates = [
                SectionCandidate(
                    section=section,
                    score=lexical_weight * lexical_score + settings.embed_weight * embedding_score,
                    lexical_score=lexical_score,
                    embedding_score=embedding_score,
                )
                for section, lexical_score, embedding_score in zip(self.sections, lexical_scores, embedding_scores)
            ]
            candidates.sort(key=lambda item: item.score, reverse=True)
            results.append([candidate for candidate in candidates[:top_k] if candidate.score > 0])
        return results

    def rank(self, rule: PolicyRule, top_k: int = 5) -> list[SectionCandidate]:
        return self.rank_all([rule], top_k=top_k)[0]
