from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from src.cont_match.retrieval import HybridSectionMatcher, LexicalSectionMatcher
from config import settings
from src.cont_match.pipeline import prepare_case
from src.page_schema import DocumentSection, PolicyRule


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls = 0

    def encode(self, texts: list[str]):
        self.calls += 1
        vectors = []
        for text in texts:
            vectors.append([1.0, 0.0] if any(word in text for word in ("担保", "保证金")) else [0.0, 1.0])
        return np.asarray(vectors, dtype=float)


class HybridRetrievalTest(unittest.TestCase):
    def test_evidence_count_has_hard_limit_of_three(self) -> None:
        with self.assertRaisesRegex(ValueError, "最大为 3"):
            prepare_case(case_id="report_1", report_path="unused.pdf", rules_path="unused.json", output_path="unused.json", candidate_count=8, evidence_count=4)

    def test_batches_embeddings_and_keeps_component_scores(self) -> None:
        sections = [
            DocumentSection("资格要求", 1, 1, 1, 1, "供应商应提交资格证明。"),
            DocumentSection("合同条款", 2, 2, 2, 2, "中标人应按约定提交保证金。"),
        ]
        rules = [
            PolicyRule(1, "履约担保要求是否合规", "【法规依据】履约担保不得超过法定上限。"),
            PolicyRule(2, "供应商资格条件是否明确", "【法规依据】资格条件应当明确。"),
        ]
        embedder = FakeEmbedder()
        matcher = HybridSectionMatcher(sections, embedder=embedder)

        ranked = matcher.rank_all(rules, top_k=2)

        self.assertEqual(embedder.calls, 2)
        self.assertEqual(ranked[0][0].section.title, "合同条款")
        self.assertEqual(ranked[1][0].section.title, "资格要求")
        self.assertIsNotNone(ranked[0][0].lexical_score)
        self.assertEqual(ranked[0][0].embedding_score, 1.0)

    def test_long_section_keeps_the_matching_chunk_instead_of_whole_section(self) -> None:
        sections = [DocumentSection("投标人须知", 10, 18, 1, 9, "无关内容" * 100 + "\n[PDF第15页]\n中标候选人公示期为2日。" + "其他内容" * 100)]
        rule = PolicyRule(4, "中标候选人公示期不足3日", "【法规依据】公示期不得少于3日。")
        with patch.object(settings, "embed_chunk_chars", 120), patch.object(settings, "embed_chunk_overlap", 20):
            ranked = LexicalSectionMatcher(sections).rank(rule, top_k=1)

        self.assertEqual(len(ranked), 1)
        self.assertIn("公示期为2日", ranked[0].section.text)
        self.assertLess(len(ranked[0].section.text), len(sections[0].text))
        self.assertEqual(ranked[0].section.pdf_end, 15)


if __name__ == "__main__":
    unittest.main()
