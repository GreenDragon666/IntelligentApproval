"""案件级流程：checker 复用/生成、执行、可选复核与定向迭代。"""

from __future__ import annotations

from collections.abc import Iterable

from config import settings
from .code_gen.checker_store import CheckerStore, checker_key
from .code_gen.graph import generate_checker
from .code_gen.reviewer import review as review_result
from .code_gen.sandbox import run_checker
from .rule_schema import ApprovalReport, MatchedCase, MatchedRule, RuleResult, RuleRun, Status


def _failure(rule: MatchedRule, summary: str) -> RuleResult:
    return RuleResult(rule_id=rule.rule_id, status=Status.ERROR, summary=summary)


def _select_rules(case: MatchedCase, rule_ids: Iterable[int] | None) -> list[MatchedRule]:
    if rule_ids is None:
        return case.rules
    requested = list(rule_ids)
    return [case.get_rule(rule_id) for rule_id in requested]


def _generate(
    rule: MatchedRule,
    store: CheckerStore,
    feedback: str = "",
    previous_code: str = "",
) -> tuple[str | None, int, str]:
    try:
        state = generate_checker(
            rule,
            feedback=feedback,
            store_root=str(store.root),
            previous_code=previous_code,
        )
    except Exception as exc:
        return None, 0, f"checker 生成流程异常: {exc!r}"
    attempts = int(state.get("attempts", 0))
    if not state.get("success"):
        return None, attempts, state.get("error", "checker 生成失败")
    return state.get("code", ""), attempts, ""


def _run_one(
    rule: MatchedRule,
    *,
    store: CheckerStore,
    generate_missing: bool,
    force_regenerate: bool,
    llm_review: bool,
) -> RuleRun:
    run = RuleRun(rule_id=rule.rule_id, rule_raw=rule.rule_raw)

    if not rule.evidence:
        run.result = RuleResult(
            rule_id=rule.rule_id,
            status=Status.INSUFFICIENT_INPUT,
            summary="未匹配到可供校验的原文。",
        )
        return run

    run.checker_key = checker_key(rule)

    code: str | None = None
    if store.exists(rule) and not force_regenerate:
        code = store.load(rule)
        run.checker_reused = True
    elif generate_missing:
        previous_code = store.load(rule) if store.exists(rule) else ""
        code, attempts, error = _generate(rule, store, previous_code=previous_code)
        run.generation_attempts += attempts
        if error:
            run.error = error
            run.result = _failure(rule, "checker 生成失败。")
            return run
    else:
        run.error = f"未找到 checker: {run.checker_key}"
        run.result = _failure(rule, "未找到可复用 checker，且本次禁止调用模型生成。")
        return run

    assert code is not None
    result, error = run_checker(code, rule)
    if error and generate_missing:
        code, attempts, generation_error = _generate(
            rule,
            store,
            feedback=f"真实输入执行失败：\n{error}",
            previous_code=code,
        )
        run.generation_attempts += attempts
        run.checker_reused = False
        if generation_error:
            run.error = generation_error
            run.result = _failure(rule, "checker 执行失败，重新生成后仍未通过验证。")
            return run
        assert code is not None
        result, error = run_checker(code, rule)

    if error or result is None:
        run.error = error or "checker 未返回结果"
        run.result = _failure(rule, "checker 执行失败。")
        return run
    run.result = result

    if not llm_review:
        return run

    for review_attempt in range(settings.review_max_retries + 1):
        try:
            run.review = review_result(rule, run.result)
        except Exception as exc:
            run.error = f"LLM 复核失败: {exc!r}"
            return run
        if run.review.approved:
            return run
        if review_attempt >= settings.review_max_retries:
            run.error = f"LLM 复核未通过且已达到迭代上限: {run.review.feedback}"
            return run
        if not generate_missing:
            run.error = f"LLM 复核未通过: {run.review.feedback}"
            return run
        code, attempts, generation_error = _generate(
            rule,
            store,
            feedback=run.review.feedback,
            previous_code=code,
        )
        run.generation_attempts += attempts
        run.checker_reused = False
        if generation_error or code is None:
            run.error = generation_error or "复核反馈后的 checker 生成失败"
            return run
        revised, execution_error = run_checker(code, rule)
        if execution_error or revised is None:
            run.error = execution_error or "修正后的 checker 未返回结果"
            return run
        run.result = revised

    return run


def run_case(
    case: MatchedCase,
    *,
    rule_ids: Iterable[int] | None = None,
    generate_missing: bool = True,
    force_regenerate: bool = False,
    llm_review: bool = False,
    checker_dir: str | None = None,
) -> ApprovalReport:
    store = CheckerStore(checker_dir)
    runs = [
        _run_one(
            rule,
            store=store,
            generate_missing=generate_missing,
            force_regenerate=force_regenerate,
            llm_review=llm_review,
        )
        for rule in _select_rules(case, rule_ids)
    ]
    return ApprovalReport(case_id=case.case_id, source_file=case.source.file, rules=runs)
