"""In-process adapter around the existing three-stage approval algorithm.

The CLI entry point resets a global ``reports`` directory, which is unsafe when
several enterprise jobs run at once. This adapter invokes the same domain
functions directly and gives every document an isolated work directory.
"""

from __future__ import annotations

import importlib
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import Settings
from ..enums import ReviewStage


ProgressCallback = Callable[[ReviewStage, int], None]


@dataclass(frozen=True)
class AlgorithmArtifacts:
    report: dict[str, Any]
    matched_case: dict[str, Any]
    matched_path: Path
    report_json_path: Path
    report_markdown_path: Path
    log_path: Path


class AlgorithmAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _imports(self) -> tuple[Any, Any, Any, Any]:
        algorithm_root = str(self.settings.algorithm_root)
        if algorithm_root not in sys.path:
            sys.path.insert(0, algorithm_root)
        existing_config = sys.modules.get("config")
        if existing_config is not None:
            loaded_from = Path(str(getattr(existing_config, "__file__", ""))).resolve()
            expected = (self.settings.algorithm_root / "config.py").resolve()
            if loaded_from != expected:
                raise RuntimeError(f"顶层 config 模块冲突：期望 {expected}，实际 {loaded_from}")
        prepare_case = importlib.import_module("src.cont_match").prepare_case
        run_case = importlib.import_module("src.engine").run_case
        report_module = importlib.import_module("src.rule_check.report")
        return prepare_case, run_case, report_module.to_json, report_module.to_markdown

    def validate_runtime(self) -> None:
        if not self.settings.algorithm_root.is_dir():
            raise RuntimeError(f"算法目录不存在: {self.settings.algorithm_root}")
        if not self.settings.policy_rules_path.is_file():
            raise RuntimeError(f"政策规则文件不存在: {self.settings.policy_rules_path}")
        self._imports()

    def run_document(self, *, case_id: str, input_path: Path, policy_rules_path: Path, work_path: Path, progress: ProgressCallback) -> AlgorithmArtifacts:
        prepare_case, run_case, to_json, to_markdown = self._imports()
        matched_path = work_path / "matched" / "rules_matched.json"
        preprocessing_path = work_path / "preprocessing"
        results_path = work_path / "results"
        cache_path = work_path / "decision_cache"
        log_path = work_path / "algorithm.log"
        results_path.mkdir(parents=True, exist_ok=True)

        with log_path.open("a", encoding="utf-8", buffering=1) as log, redirect_stdout(log), redirect_stderr(log):
            progress(ReviewStage.EXTRACTING, 10)
            case = prepare_case(
                case_id=case_id,
                report_path=input_path,
                rules_path=policy_rules_path,
                output_path=matched_path,
                artifacts_dir=preprocessing_path,
                max_section_pages=self.settings.algorithm_max_section_pages,
                candidate_count=self.settings.algorithm_candidate_count,
                evidence_count=self.settings.algorithm_evidence_count,
                minimum_score=self.settings.algorithm_minimum_score,
                use_embedding=self.settings.algorithm_use_embedding,
                use_llm=self.settings.algorithm_use_llm_matching,
                strict_llm=self.settings.algorithm_strict_llm,
                match_workers=self.settings.algorithm_match_workers,
            )
            progress(ReviewStage.CHECKING, 65)
            report = run_case(
                case,
                enable_llm=self.settings.algorithm_enable_llm_check,
                llm_review=self.settings.algorithm_llm_review,
                cache_dir=str(cache_path),
                max_workers=self.settings.algorithm_check_workers,
            )
            progress(ReviewStage.FINALIZING, 92)
            report_json_path = results_path / "summary.json"
            report_markdown_path = results_path / "summary.md"
            report_json_path.write_text(to_json(report) + "\n", encoding="utf-8")
            report_markdown_path.write_text(to_markdown(report, case), encoding="utf-8")

        return AlgorithmArtifacts(
            report=report.to_dict(),
            matched_case=case.to_dict(),
            matched_path=matched_path,
            report_json_path=report_json_path,
            report_markdown_path=report_markdown_path,
            log_path=log_path,
        )


def write_frontend_detail(path: Path, detail: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(detail, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
