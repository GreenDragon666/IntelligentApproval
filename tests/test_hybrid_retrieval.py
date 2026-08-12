from __future__ import annotations

import unittest

import numpy as np

from src.cont_match.retrieval import HybridSectionMatcher
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


if __name__ == "__main__":
    unittest.main()
