"""Public API schemas. Camel-case aliases match the existing React frontend."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def _camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)


class ReviewJobResponse(ApiModel):
    id: str
    mode: Literal["live"] = "live"
    status: Literal["queued", "processing", "completed", "failed"]


class DocumentProgress(ApiModel):
    id: str
    file_name: str
    status: Literal["queued", "processing", "completed", "failed"]
    stage: str
    progress: int = Field(ge=0, le=100)
    error_message: str | None = None


class ReviewStatusResponse(ApiModel):
    id: str
    mode: Literal["live"] = "live"
    status: Literal["queued", "processing", "completed", "failed"]
    internal_status: str
    stage: str
    progress: int = Field(ge=0, le=100)
    total_documents: int
    completed_documents: int
    failed_documents: int
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    documents: list[DocumentProgress]


class StatusCounts(ApiModel):
    violation: int = 0
    warning: int = 0
    insufficient: int = 0
    passed: int = 0


class DocumentStatusCounts(StatusCounts):
    execution_failed: int = 0


class SafeIndicators(ApiModel):
    requires_review: bool | None = None
    unresolved_fields: list[str] | None = None
    evaluated_subchecks: int | None = None
    field_aliases: list[str] | None = None


class BriefRule(ApiModel):
    id: str
    number: int
    title: str
    status: Literal["violation", "warning", "insufficient", "passed"]


class RuleDetail(BriefRule):
    conclusion: str | None = None
    llm_analysis: str | None = None
    legal_basis: str | None = None
    evidence_locations: str | None = None
    matched_text: str | None = None
    missing_inputs: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    indicators: SafeIndicators | None = None


class ReviewDocumentResponse(ApiModel):
    id: str
    file_name: str
    overall_conclusion: Literal["violation", "warning", "insufficient", "passed"]
    counts: DocumentStatusCounts
    rules: list[BriefRule]
    detail_available: bool


class ReviewSummaryResponse(ApiModel):
    schema_version: str = "1.0"
    review_id: str
    mode: Literal["live"] = "live"
    source_files: list[str]
    overall_conclusion: Literal["violation", "warning", "insufficient", "passed"]
    completed_documents: int
    failed_documents: int
    valid_decision_count: int
    execution_failed_count: int
    counts: StatusCounts
    documents: list[ReviewDocumentResponse]


class DocumentDetailResponse(ApiModel):
    schema_version: str = "1.0"
    review_id: str
    document_id: str
    file_name: str
    overall_conclusion: Literal["violation", "warning", "insufficient", "passed"]
    rules: list[RuleDetail]


class ErrorBody(ApiModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class ErrorResponse(ApiModel):
    error: ErrorBody
