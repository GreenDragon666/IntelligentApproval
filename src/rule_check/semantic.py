"""使用服务器本地 Qwen 对非结构化规则直接作短输出、可回引的语义判定。"""

from __future__ import annotations

import json
from dataclasses import dataclass

from config import settings
from .. import llm
from ..rule_parts import legal_basis, rule_description
from ..rule_schema import Finding, MatchedRule, RuleResult, Status
from .json_output import extract_json_object

_ALLOWED_STATUSES = {Status.VIOLATION, Status.WARNING, Status.PASS, Status.INSUFFICIENT_INPUT}

SYSTEM_PROMPT = """你是招标文件合规审查器。rule_raw（重点排查情形）决定审查主题；legal_basis_reference 是可参考的法规依据，可补充具体法律要求、数值和期限；description_reference 只用于帮助理解规则适用场景，不得单独据此新增阈值、条件或缺失输入；check_method 仅表示检查路线。严格依据规则和证据作答，不生成 Python 代码，不补充未提供的事实。
必须返回一个 JSON 对象，不得输出 Markdown 或思考过程。JSON 字段：
{"status":"violation|warning|pass|insufficient_input","summary":"简短结论","analysis":"2至4句话说明证据与规则的关系、为什么该状态合理以及判断边界","legal_basis":"规则中已有法规依据，无法确定则空字符串","findings":[{"evidence_index":0,"quote":"证据中的连续原文","reason":"该原文如何触发规则"}],"confidence":0到1,"missing_inputs":["缺失资料"]}
要求：
1. findings 中的 quote 必须逐字来自对应 evidence.text，不能改写。
2. 只有 rule_raw 或 legal_basis_reference 明确要求的外部文件或比较对象未提供时，才能返回 insufficient_input；不得根据公式、开发说明或预设字段推断缺失输入。
3. 没有明确命中时不得仅凭关键词判违规，必须结合上下文和规则条件。
4. status=pass 时 findings 应为空；violation/warning 时至少提供一条可回引证据。
5. 不得把 evidence 数组位置臆测为某类外部文件，只能使用 location 中明确提供的信息。"""


@dataclass(frozen=True)
class SemanticEvaluation:
    result: RuleResult
    attempts: int


def _payload(rule: MatchedRule) -> dict:
    remaining = settings.semantic_max_evidence_chars
    evidence_items = []
    for index, evidence in enumerate(rule.evidence):
        if remaining <= 0:
            break
        text = evidence.text[: min(len(evidence.text), remaining, settings.semantic_max_chars_per_evidence)]
        remaining -= len(text)
        evidence_items.append({
            "evidence_index": index,
            "location": {
                "file": evidence.location.file,
                "section": evidence.location.section,
                "pdf_pages": [evidence.location.pdf_pages.start, evidence.location.pdf_pages.end],
                "page_basis": evidence.location.page_basis,
            },
            "text": text,
        })
    return {
        "rule_id": rule.rule_id,
        "check_method": rule.check_method,
        "rule_raw": rule.rule_raw,
        "description_reference": rule_description(rule.rule_text),
        "legal_basis_reference": legal_basis(rule.rule_text),
        "evidence": evidence_items,
    }


def _source_quote(text: str, quote: str) -> str | None:
    """接受模型折叠 PDF 空白的引用，并回映射为 evidence 中的连续原文。"""
    if quote in text:
        return quote
    text_chars: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(text):
        if not char.isspace():
            text_chars.append(char)
            positions.append(index)
    compact_quote = "".join(char for char in quote if not char.isspace())
    if not compact_quote:
        return None
    start = "".join(text_chars).find(compact_quote)
    if start < 0:
        return None
    end = start + len(compact_quote) - 1
    return text[positions[start]:positions[end] + 1]


def _to_result(rule: MatchedRule, data: dict) -> RuleResult:
    try:
        status = Status(str(data["status"]).strip())
    except Exception as exc:
        raise ValueError(f"非法或缺失 status: {data.get('status')!r}") from exc
    if status not in _ALLOWED_STATUSES:
        raise ValueError(f"LLM 判定不允许返回 {status.value}")
    findings = []
    for item in data.get("findings") or []:
        evidence_index = int(item["evidence_index"])
        if evidence_index < 0 or evidence_index >= len(rule.evidence):
            raise ValueError(f"evidence_index 越界: {evidence_index}")
        quote = str(item.get("quote", "")).strip()
        source_quote = _source_quote(rule.evidence[evidence_index].text, quote)
        if source_quote is None:
            raise ValueError("quote 不是对应 evidence.text 中的连续原文")
        findings.append(Finding(evidence_index=evidence_index, quote=source_quote, reason=str(item.get("reason", "")).strip()))
    if status in {Status.VIOLATION, Status.WARNING} and not findings:
        raise ValueError(f"{status.value} 必须提供至少一条 finding")
    if status == Status.PASS:
        findings = []
    confidence = float(data.get("confidence", 0.0))
    if confidence < 0 or confidence > 1:
        raise ValueError("confidence 必须在 0 到 1 之间")
    summary = str(data.get("summary", "")).strip() or "本地模型未提供结论摘要。"
    analysis = str(data.get("analysis", "")).strip()
    if not analysis:
        raise ValueError("LLM 判定缺少 analysis")
    return RuleResult(
        rule_id=rule.rule_id,
        status=status,
        summary=summary,
        analysis=analysis,
        legal_basis=legal_basis(rule.rule_text),
        findings=findings,
        metrics={"executor": "semantic_llm"},
        confidence=confidence,
        missing_inputs=[str(value).strip() for value in data.get("missing_inputs") or [] if str(value).strip()],
    )


def evaluate_semantic(rule: MatchedRule) -> SemanticEvaluation:
    if not rule.evidence:
        return SemanticEvaluation(RuleResult(rule_id=rule.rule_id, status=Status.INSUFFICIENT_INPUT, summary="未匹配到可供语义审查的原文。", confidence=1.0, missing_inputs=["招标文件相关原文"]), 0)
    payload = json.dumps(_payload(rule), ensure_ascii=False, separators=(",", ":"))
    last_error = ""
    for attempt in range(1, settings.semantic_max_retries + 2):
        correction = f"\n上一次输出校验失败：{last_error}\n请只修正 JSON。" if last_error else ""
        prompt = f"/no_think\n请审查以下规则与证据。{correction}\n输入：{payload}"
        try:
            raw = llm.chat(prompt, system=SYSTEM_PROMPT, temperature=0.0, max_tokens=settings.semantic_max_tokens)
            return SemanticEvaluation(_to_result(rule, extract_json_object(raw)), attempt)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    raise RuntimeError(f"语义判定连续失败 {settings.semantic_max_retries + 1} 次：{last_error}")
