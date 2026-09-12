from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from main import _load_case
from src.cont_match.rules import load_policy_rules
from src.rule_check.methods import executor_name, is_structured_method, normalize_check_method
from src.rule_schema import MatchedRule


class RuleRoutingTest(unittest.TestCase):
    def test_combined_structured_method_routes_to_global_executor(self) -> None:
        self.assertEqual(normalize_check_method("结构化数据检查 ＋ 大模型分析"), "结构化数据检查+大模型分析")
        self.assertTrue(is_structured_method("结构化数据检查+大模型分析"))
        self.assertEqual(executor_name("关键词匹配+大模型分析"), "semantic_llm")

    def test_json_policy_loader_keeps_method_and_fields(self) -> None:
        rows = [{"rule_id": 1, "rule_raw": "检查金额", "rule_text": "【公式】IF 金额 > 1", "check_method": "结构化数据检查", "structured_fields": "金额字段"}]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rules.json"
            path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            rule = load_policy_rules(path)[0]
        self.assertEqual(rule.check_method, "结构化数据检查")
        self.assertEqual(rule.structured_fields, "金额字段")

    def test_json_policy_loader_reassembles_nested_rule_text(self) -> None:
        from src.rule_parts import legal_basis, rule_description
        rows = {"version": "1.0", "rules": [{"rule_id": 3, "rule_raw": "检查期限", "rule_text": {"description": "检查公告期限是否充分。", "legal_basis": "法定期限至少5日。", "formula": "IF 天数 < 5 THEN 违规", "dev_note": "输入：公告发布日期"}, "check_method": "大模型分析", "match_hints": ["招标公告"]}]}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rules.json"
            path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            rule = load_policy_rules(path)[0]
        # 子字段被重组为块字符串，下游 rule_parts 能原样解析出描述与法规依据。
        self.assertEqual(rule_description(rule.rule_text), "检查公告期限是否充分。")
        self.assertEqual(legal_basis(rule.rule_text), "法定期限至少5日。")
        self.assertIn("【公式】", rule.rule_text)
        self.assertEqual(rule.match_hints, ["招标公告"])

    def test_non_json_rule_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rules.xlsx"
            path.write_text("irrelevant", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_policy_rules(path)

    def test_old_matched_json_defaults_to_semantic(self) -> None:
        rule = MatchedRule.from_dict({"rule_id": 1, "rule_raw": "旧规则", "rule_text": "旧逻辑", "evidence": []})
        self.assertEqual(rule.check_method, "大模型分析")

    def test_existing_case_can_refresh_method_without_rematching(self) -> None:
        case_data = {"case_id": "report_1", "source": {"file": "a.pdf"}, "rules": [{"rule_id": 1, "rule_raw": "旧规则", "rule_text": "旧逻辑", "evidence": []}]}
        policies = [{"rule_id": 1, "rule_raw": "当前规则", "rule_text": "当前逻辑", "check_method": "结构化数据检查", "structured_fields": "金额字段"}]
        with tempfile.TemporaryDirectory() as temporary:
            case_path = Path(temporary) / "matched.json"
            policy_path = Path(temporary) / "rules.json"
            case_path.write_text(json.dumps(case_data, ensure_ascii=False), encoding="utf-8")
            policy_path.write_text(json.dumps(policies, ensure_ascii=False), encoding="utf-8")
            case = _load_case(case_path, str(policy_path))
        self.assertEqual(case.rules[0].rule_text, "旧逻辑")
        self.assertEqual(case.rules[0].check_method, "结构化数据检查")
        self.assertEqual(case.rules[0].structured_fields, "金额字段")


if __name__ == "__main__":
    unittest.main()
