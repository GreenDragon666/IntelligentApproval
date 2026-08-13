from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from main import _reset_reports
from src.rule_check.report import to_brief_markdown, to_markdown
from src.rule_schema import ApprovalReport, EvidenceLocation, MatchedCase, MatchedEvidence, MatchedRule, PageRange, RuleResult, RuleRun, SourceDocument, Status


def _case_and_report(source: str = "招标文件.pdf") -> tuple[MatchedCase, ApprovalReport]:
    location = EvidenceLocation(file=source, section="投标人须知", pdf_pages=PageRange(8, 9), document_pages=PageRange(1, 2))
    evidence = MatchedEvidence(location, "投标保证金不得超过项目估算价的2%。\n本项目保证金为10万元。")
    passed = MatchedRule(rule_id=1, rule_raw="投标保证金比例是否合法", rule_text="【法规依据】不得超过2%。", evidence=[evidence], check_method="结构化数据检查")
    violated = MatchedRule(rule_id=2, rule_raw="评分标准是否明确", rule_text="【法规依据】评标标准应当明确。", evidence=[evidence], check_method="大模型分析")
    case = MatchedCase(case_id="report_1", source=SourceDocument(source), rules=[passed, violated])
    report = ApprovalReport(case_id="report_1", source_file=source, rules=[
        RuleRun(rule_id=1, rule_raw=passed.rule_raw, check_method=passed.check_method, executor="structured", result=RuleResult(rule_id=1, status=Status.PASS, summary="比例合规", analysis="正则提取的比例未超过法规上限，因此通过结果合理。")),
        RuleRun(rule_id=2, rule_raw=violated.rule_raw, check_method=violated.check_method, executor="semantic_llm", result=RuleResult(rule_id=2, status=Status.VIOLATION, summary="标准不明确", analysis="证据没有给出可执行的评分分档标准。")),
    ])
    return case, report


class ReportMarkdownTest(unittest.TestCase):
    def test_detailed_report_uses_analysis_and_locations_instead_of_full_pass_evidence(self) -> None:
        case, report = _case_and_report()
        markdown = to_markdown(report, case)
        self.assertIn("**LLM 分析**：正则提取的比例未超过法规上限", markdown)
        self.assertIn("投标人须知（PDF第8-9页，文件内页码1-2）", markdown)
        self.assertNotIn("> 投标保证金不得超过项目估算价的2%。", markdown)

    def test_brief_combines_multiple_documents_and_lists_rules(self) -> None:
        _case1, report1 = _case_and_report("文件一.pdf")
        _case2, report2 = _case_and_report("文件二.pdf")
        markdown = to_brief_markdown([report1, report2])
        self.assertIn("本次完成校验 **2** 份文件", markdown)
        self.assertIn("| 文件一.pdf | 违规 | 1 | 0 | 1 | 0 | 0 |", markdown)
        self.assertIn("### 通过规则（1）", markdown)
        self.assertIn("规则 2：评分标准是否明确", markdown)

    def test_new_full_run_replaces_previous_reports_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "reports"
            old = root / "report_9" / "results"
            old.mkdir(parents=True)
            (old / "summary.md").write_text("旧结果", encoding="utf-8")
            result = _reset_reports(root)
            self.assertEqual(result, root.resolve())
            self.assertTrue(root.is_dir())
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
