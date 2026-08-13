from __future__ import annotations

import unittest

from src.rule_check.json_output import extract_json_object


class JsonOutputTest(unittest.TestCase):
    def test_extracts_json_after_qwen_think_wrapper(self) -> None:
        raw = '<think>\n\n</think>\n\n{"consistent":true,"analysis":"结果合理","confidence":0.8}'
        data = extract_json_object(raw, label="测试输出")
        self.assertTrue(data["consistent"])

    def test_extracts_json_from_markdown_and_surrounding_text(self) -> None:
        raw = '分析结果如下：\n```json\n{"approved":true,"feedback":"通过"}\n```\n以上。'
        data = extract_json_object(raw, label="测试输出")
        self.assertTrue(data["approved"])

    def test_empty_output_has_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "测试输出为空"):
            extract_json_object("", label="测试输出")


if __name__ == "__main__":
    unittest.main()
