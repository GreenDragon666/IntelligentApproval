"""案件级步骤三：全局结构化执行器、并发语义判定、缓存与可选复核。"""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace

from config import settings
from .rule_check import DecisionCache, evaluate_semantic, evaluate_structured, explain_result, is_structured_method
from .rule_check.cache import decision_key
from .rule_check.explainer import ExplanationError
from .rule_check.reviewer import review as review_result
from .rule_schema import ApprovalReport, MatchedCase, MatchedRule, RuleResult, RuleRun, Status


def _failure(rule: MatchedRule, summary: str) -> RuleResult:
    return RuleResult(rule_id=rule.rule_id, status=Status.ERROR, summary=summary)


def _select_rules(case: MatchedCase, rule_ids: Iterable[int] | None) -> list[MatchedRule]:
    if rule_ids is None:
        return case.rules
    return [case.get_rule(rule_id) for rule_id in rule_ids]


def _add_explanation(rule: MatchedRule, run: RuleRun) -> bool:
    """为已有结果补分析；失败时保留原判定，避免解释服务覆盖确定性结果。"""
    if run.result is None or run.result.analysis:
        return True
    try:
        explanation = explain_result(rule, run.result)
    except ExplanationError as exc:
        run.attempts += exc.attempts
        run.analysis_error = f"{type(exc).__name__}: {exc}"
        run.analysis_raw = exc.raw
        return False
    except Exception as exc:
        run.analysis_error = f"{type(exc).__name__}: {exc}"
        return False
    run.result = explanation.result
    run.attempts += explanation.attempts
    run.analysis_error = ""
    run.analysis_raw = ""
    return True


def _adjudicate_structured_warning(rule: MatchedRule, run: RuleRun) -> bool:
    """正则无法完成时，用与普通语义规则相同的输入契约形成最终判断。"""
    if run.structured_result is None:
        return False
    try:
        evaluation = evaluate_semantic(rule)
    except Exception as exc:
        run.attempts += settings.semantic_max_retries + 1
        run.analysis_error = f"结构化兜底语义判定失败: {type(exc).__name__}: {exc}"
        run.result = run.structured_result
        return False
    run.attempts += evaluation.attempts
    run.result = replace(evaluation.result, metrics={**evaluation.result.metrics, "structured_fallback": True, "structured_status": run.structured_result.status.value})
    run.analysis_error = ""
    run.analysis_raw = ""
    return True


def _run_one(rule: MatchedRule, *, cache: DecisionCache, enable_llm: bool, force_recheck: bool, llm_review: bool, rollback: bool) -> RuleRun:
    structured = is_structured_method(rule.check_method)
    executor = "structured" if structured else "semantic_llm"
    run = RuleRun(rule_id=rule.rule_id, rule_raw=rule.rule_raw, check_method=rule.check_method, executor=executor, cache_key=decision_key(rule))

    if rollback:
        if not cache.rollback(rule):
            run.error = "没有可恢复的上一版判定缓存，已按当前配置重新执行。"

    if not force_recheck:
        cached = cache.load(rule)
        if cached is not None:
            run.result, metadata = cached
            structured_data = metadata.get("structured_result")
            run.structured_result = RuleResult.from_dict(structured_data) if isinstance(structured_data, dict) else None
            if structured and run.structured_result is None:
                # 兼容旧缓存：当时 result 本身就是结构化初判，但尚未单独保存 structured_result。
                run.structured_result = run.result
            run.cached = True
            run.attempts = int(metadata.get("attempts", 0))
            run.analysis_error = str(metadata.get("analysis_error", ""))
            run.analysis_raw = str(metadata.get("analysis_raw", ""))
            if enable_llm and not run.result.analysis:
                if structured and run.structured_result and run.structured_result.metrics.get("requires_review"):
                    _adjudicate_structured_warning(rule, run)
                else:
                    _add_explanation(rule, run)
                # 成功和失败都保存：避免旧缓存每次续跑都重复相同失败，也保留实际调用次数和原始输出。
                cache.save(rule, run.result, executor=executor, attempts=run.attempts, error=run.error, structured_result=run.structured_result, analysis_error=run.analysis_error, analysis_raw=run.analysis_raw)
            if not llm_review:
                return run

    if run.result is None and not rule.evidence:
        run.result = RuleResult(rule_id=rule.rule_id, status=Status.WARNING, summary="内容匹配阶段未定位到相关原文，当前不能自动判断；这不代表规则要求的输入资料缺失。", confidence=0.0, metrics={"reason": "evidence_not_retrieved"})
        if enable_llm:
            _add_explanation(rule, run)

    if run.result is None:
        try:
            if structured:
                run.structured_result = evaluate_structured(rule, enable_semantic_aliases=enable_llm)
                run.result = run.structured_result
                if enable_llm and run.structured_result.metrics.get("requires_review"):
                    _adjudicate_structured_warning(rule, run)
                elif enable_llm:
                    _add_explanation(rule, run)
            elif enable_llm:
                evaluation = evaluate_semantic(rule)
                run.result = evaluation.result
                run.attempts = evaluation.attempts
            else:
                run.result = RuleResult(rule_id=rule.rule_id, status=Status.INSUFFICIENT_INPUT, summary="该规则需要本地 LLM 语义判定，但本次已禁用 LLM。", confidence=1.0, missing_inputs=["启用本地 LLM 语义判定"])
                return run
        except Exception as exc:
            run.error = f"{executor} 执行失败: {type(exc).__name__}: {exc}"
            run.result = _failure(rule, "规则校验执行失败。")
            return run

    if llm_review and run.result is not None and enable_llm:
        try:
            run.review = review_result(rule, run.result)
        except Exception as exc:
            run.error = f"LLM 复核失败: {type(exc).__name__}: {exc}"
        else:
            if not run.review.approved:
                run.error = f"LLM 复核未通过: {run.review.feedback}"

    if not run.cached:
        cache.save(rule, run.result, executor=executor, attempts=run.attempts, error=run.error, structured_result=run.structured_result, analysis_error=run.analysis_error, analysis_raw=run.analysis_raw)
    return run


def run_case(
    case: MatchedCase,
    *,
    rule_ids: Iterable[int] | None = None,
    enable_llm: bool = True,
    force_recheck: bool = False,
    llm_review: bool = False,
    cache_dir: str = "decision_cache",
    max_workers: int | None = None,
    rollback_rule_ids: Iterable[int] | None = None,
    generate_missing: bool | None = None,
    force_regenerate: bool | None = None,
    checker_dir: str | None = None,
) -> ApprovalReport:
    """执行步骤三；旧参数保留为兼容别名，不再生成案件专用 Python checker。"""
    if generate_missing is not None:
        enable_llm = generate_missing
    if force_regenerate is not None:
        force_recheck = force_regenerate
    if checker_dir and cache_dir == "decision_cache":
        cache_dir = checker_dir
    selected = _select_rules(case, rule_ids)
    rollback_ids = set(rollback_rule_ids or [])
    unknown = rollback_ids - {rule.rule_id for rule in selected}
    if unknown:
        raise KeyError(f"回滚规则不在本次执行范围: {sorted(unknown)}")
    cache = DecisionCache(cache_dir)
    workers = max(1, max_workers or settings.semantic_workers)
    runs: list[RuleRun | None] = [None] * len(selected)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rule-check") as pool:
        futures = {
            pool.submit(_run_one, rule, cache=cache, enable_llm=enable_llm, force_recheck=force_recheck, llm_review=llm_review, rollback=rule.rule_id in rollback_ids): (index, rule)
            for index, rule in enumerate(selected)
        }
        total = len(futures)
        completed = 0
        for future in as_completed(futures):
            index, rule = futures[future]
            try:
                runs[index] = future.result()
            except Exception as exc:
                runs[index] = RuleRun(rule_id=rule.rule_id, rule_raw=rule.rule_raw, check_method=rule.check_method, executor="structured" if is_structured_method(rule.check_method) else "semantic_llm", cache_key=decision_key(rule), result=_failure(rule, "规则校验流程异常。"), error=f"未捕获流程异常: {type(exc).__name__}: {exc}")
            completed += 1
            interval = max(1, total // 10)
            if completed == total or completed % interval == 0:
                print(f"步骤三规则校验进度: {completed}/{total}", flush=True)
    return ApprovalReport(case_id=case.case_id, source_file=case.source.file, rules=[run for run in runs if run is not None])
