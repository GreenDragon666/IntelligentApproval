"""Review query, projection and lifecycle helper functions."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..enums import DocumentStatus, ReviewStatus
from ..models import Review, ReviewDocument
from .result_mapper import DocumentProjection, build_review_summary


TERMINAL_REVIEW_STATUSES = {ReviewStatus.COMPLETED.value, ReviewStatus.PARTIAL_FAILED.value, ReviewStatus.FAILED.value}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def load_review(session: Session, review_id: uuid.UUID, *, for_update: bool = False) -> Review | None:
    statement = select(Review).options(selectinload(Review.documents)).where(Review.id == review_id)
    if for_update:
        statement = statement.with_for_update()
    return session.execute(statement).scalar_one_or_none()


def public_job_status(status: str) -> str:
    if status == ReviewStatus.QUEUED.value:
        return "queued"
    if status == ReviewStatus.PROCESSING.value:
        return "processing"
    if status in {ReviewStatus.COMPLETED.value, ReviewStatus.PARTIAL_FAILED.value}:
        return "completed"
    return "failed"


def project_documents(documents: Iterable[ReviewDocument]) -> list[DocumentProjection]:
    projections = []
    for document in documents:
        summary = document.algorithm_result.get("summary", {}) if isinstance(document.algorithm_result, dict) else {}
        execution_failed = int(summary.get("error", 0)) if isinstance(summary, dict) else 0
        projections.append(DocumentProjection(
            document_id=str(document.id),
            file_name=document.original_filename,
            status=document.status,
            detail=document.frontend_detail if isinstance(document.frontend_detail, dict) else None,
            execution_failed=execution_failed,
            error_message=document.error_message,
        ))
    return projections


def review_summary(review: Review) -> dict:
    return build_review_summary(str(review.id), project_documents(review.documents))


def reset_failed_for_retry(review: Review) -> int:
    reset = 0
    for document in review.documents:
        if document.status == DocumentStatus.FAILED.value:
            document.status = DocumentStatus.QUEUED.value
            document.stage = "queued"
            document.progress = 0
            document.error_message = None
            document.started_at = None
            document.completed_at = None
            reset += 1
    if reset:
        review.status = ReviewStatus.QUEUED.value
        review.stage = "queued"
        review.progress = 0
        review.error_message = None
        review.started_at = None
        review.completed_at = None
        review.completed_documents = sum(item.status == DocumentStatus.COMPLETED.value for item in review.documents)
        review.failed_documents = 0
    return reset

