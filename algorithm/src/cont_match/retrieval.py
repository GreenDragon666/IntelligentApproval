"""字符 TF-IDF 与本地 embedding 融合的规则—章节候选召回。"""

from __future__ import annotations

import math
import re
from collections import Counter

from config import settings
from ..llm import Embedder
from ..page_schema import DocumentSection, PolicyRule, SectionCandidate
from ..rule_parts import legal_basis, rule_description

_PAGE_MARKER = re.compile(r"\[PDF第(?P<page>\d+)页\]")


def _default_hints(rule: PolicyRule) -> list[str]:
    """为当前政策规则补齐可位置的原文表述；外部 match_hints 仍可扩展或覆盖召回。"""
    raw = rule.rule_raw.replace(" ", "")
    if "其他要求" in raw and "地区" in raw:
        return ["注册登记", "固定办公场所", "常驻人员", "本地注册", "本地区企业"]
    if "人员" in raw and "地区" in raw:
        return ["本地户籍", "户口", "户籍证明", "本地缴纳社保", "外地在建项目"]
    if "履约保证金" in raw and "现金" in raw:
        return ["履约保证金形式", "现金形式", "不接受银行保函", "拒收保函", "非现金形式"]
    if "中标候选人公示期" in raw:
        return ["中标候选人公示期", "公示期限", "公示期为1日", "公示期为2日", "不少于两日"]
    if "预付款" in raw:
        return ["不支付预付款", "预付款比例", "预付款为合同", "开工预付款"]
    if "特定行业业绩" in raw:
        return ["行业业绩", "专项业绩", "业绩作为资格", "业绩作为评标加分"]
    if "第三方机构" in raw:
        return ["协会颁发", "协会评定", "信用评价", "荣誉证书", "证明文件"]
    if "行政区域" in raw and "业绩" in raw:
        return ["行政区域内", "境内业绩", "业绩作为资格", "业绩作为评标加分"]
    return []


def _effective_hints(rule: PolicyRule) -> list[str]:
    return list(dict.fromkeys([*rule.match_hints, *_default_hints(rule)]))


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
    """领域无关的字符 TF-IDF 文本块召回器。"""

    def __init__(self, sections: list[DocumentSection], *, split_into_chunks: bool = True):
        """预计算文本块/标题词频和全语料 IDF。"""
        if not sections:
            raise ValueError("没有可匹配章节")
        self.sections = _retrieval_units(sections) if split_into_chunks else sections
        self.section_terms = [_terms(section.title + "\n" + section.text) for section in self.sections]
        self.title_terms = [_terms(section.title) for section in self.sections]
        document_frequency: Counter[str] = Counter()
        for terms in self.section_terms:
            document_frequency.update(terms.keys())
        total = len(self.sections)
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
        hints = _effective_hints(rule)
        raw_query = _terms("\n".join([rule.rule_raw] * 3 + [rule_description(rule.rule_text), *hints]))
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
            compact = re.sub(r"[^0-9a-z一-鿿]+", "", section.text.lower())
            anchor_hits = sum(re.sub(r"[^0-9a-z一-鿿]+", "", hint.lower()) in compact for hint in hints)
            anchor_score = min(0.45, 0.25 * anchor_hits)
            score = 0.55 * raw_content_score + 0.10 * legal_content_score + 0.20 * title_score + anchor_score
            scores.append(float(score))
        return scores

    def rank(self, rule: PolicyRule, top_k: int = 5) -> list[SectionCandidate]:
        """返回字符分数大于零的 top-k 章节。"""
        candidates = [SectionCandidate(section=section, score=score, lexical_score=score) for section, score in zip(self.sections, self.scores(rule))]
        candidates.sort(key=lambda item: item.score, reverse=True)
        return [item for item in candidates[:top_k] if item.score > 0]


def _page_for_offset(section: DocumentSection, offset: int) -> int:
    """使用步骤一写入的页标记推导文本位置所在 PDF 页。"""
    page = section.pdf_start
    for marker in _PAGE_MARKER.finditer(section.text, 0, max(0, offset) + 1):
        page = int(marker.group("page"))
    return min(max(page, section.pdf_start), section.pdf_end)


def _document_page(section: DocumentSection, pdf_page: int) -> int | None:
    if section.document_start is None:
        return None
    return section.document_start + pdf_page - section.pdf_start


def _section_chunks(section: DocumentSection, chunk_chars: int, overlap: int) -> list[DocumentSection]:
    """切分长章节并保留命中文本，不再在排名后回退到整个大章节。"""
    text = section.text
    if not text.strip():
        return [section]
    if len(text) <= chunk_chars:
        return [section]
    step = chunk_chars - overlap
    chunks: list[DocumentSection] = []
    for start in range(0, len(text), step):
        end = min(len(text), start + chunk_chars)
        body = text[start:end].strip()
        if not body:
            continue
        pdf_start = _page_for_offset(section, start)
        pdf_end = _page_for_offset(section, max(start, end - 1))
        page_prefix = f"[PDF第{pdf_start}页]\n" if not body.startswith("[PDF第") else ""
        chunks.append(
            DocumentSection(
                title=section.title,
                pdf_start=pdf_start,
                pdf_end=max(pdf_start, pdf_end),
                document_start=_document_page(section, pdf_start),
                document_end=_document_page(section, max(pdf_start, pdf_end)),
                text=page_prefix + body,
            )
        )
        if end >= len(text):
            break
    return chunks


def _retrieval_units(sections: list[DocumentSection]) -> list[DocumentSection]:
    units: list[DocumentSection] = []
    for section in sections:
        units.extend(_section_chunks(section, settings.embed_chunk_chars, settings.embed_chunk_overlap))
    return units


class HybridSectionMatcher:
    """批量编码章节切片和规则查询，再融合字符与 embedding 分数。"""

    def __init__(self, sections: list[DocumentSection], embedder: Embedder | None = None):
        if not 0 <= settings.embed_weight <= 1:
            raise ValueError("LOCAL_EMBED_WEIGHT 必须在 0 到 1 之间")
        if settings.embed_chunk_chars < 1 or settings.embed_chunk_overlap < 0 or settings.embed_chunk_overlap >= settings.embed_chunk_chars:
            raise ValueError("embedding 切片长度必须大于 0，重叠长度须小于切片长度")
        self.sections = _retrieval_units(sections)
        self.lexical = LexicalSectionMatcher(self.sections, split_into_chunks=False)
        self.embedder = embedder or Embedder()
        self.chunk_embeddings = self.embedder.encode([f"{section.title}\n{section.text}" for section in self.sections])

    def rank_all(self, rules: list[PolicyRule], top_k: int = 5) -> list[list[SectionCandidate]]:
        """一次编码全部规则，并对每条规则返回融合分数 top-k。"""
        if not rules:
            return []
        import numpy as np

        query_specs: list[tuple[int, float, str]] = []
        for rule_index, rule in enumerate(rules):
            query_specs.extend((rule_index, weight, text) for text, weight in rule.query_variants)
            query_specs.extend((rule_index, 1.0, hint) for hint in _default_hints(rule) if hint not in rule.match_hints)
        query_embeddings = self.embedder.encode([text for _rule_index, _weight, text in query_specs])
        similarities = np.asarray(query_embeddings) @ np.asarray(self.chunk_embeddings).T
        results: list[list[SectionCandidate]] = []
        lexical_weight = 1.0 - settings.embed_weight
        for rule_index, rule in enumerate(rules):
            embedding_scores = [0.0] * len(self.sections)
            for query_index, (owner, weight, _text) in enumerate(query_specs):
                if owner != rule_index:
                    continue
                for chunk_index, similarity in enumerate(similarities[query_index]):
                    score = weight * max(0.0, float(similarity))
                    if score > embedding_scores[chunk_index]:
                        embedding_scores[chunk_index] = score
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
