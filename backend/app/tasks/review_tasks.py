"""Durable background orchestration of the three-stage algorithm."""

from __future__ import annotations

import logging
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from ..config import get_settings
from ..database import SessionLocal
from ..enums import DocumentStatus, ReviewStage, ReviewStatus
from ..models import Review, ReviewDocument
from ..services.algorithm_adapter import AlgorithmAdapter, write_frontend_detail
from ..services.report_files import write_review_files
from ..services.result_mapper import map_document_detail
from ..services.review_service import load_review, review_summary, sha256_file
from ..services.storage import ensure_within, review_directory
from .celery_app import celery_app


logger = logging.getLogger(__name__)
settings = get_settings()


def _resolve_review_path(review_id: str, relative: str) -> Path:
    root = review_directory(settings.storage_root, review_id)
    return ensure_within(root, root / relative)


def _update_progress(review_id: uuid.UUID, document_id: uuid.UUID, total: int, stage: ReviewStage, progress: int) -> None:
    with SessionLocal.begin() as session:
        document = session.get(ReviewDocument, document_id)
        review = session.get(Review, review_id)
        if document is None or review is None:
            return
        document.stage = stage.value
        document.progress = max(0, min(100, progress))
        review.stage = stage.value
        terminal = review.completed_documents + review.failed_documents
        review.progress = max(1, min(99, int(((terminal + document.progress / 100) / max(1, total)) * 100)))


def _mark_document_started(document_id: uuid.UUID) -> None:
    with SessionLocal.begin() as session:
        document = session.get(ReviewDocument, document_id)
        if document is None:
            raise LookupError(f"文档不存在: {document_id}")
        document.status = DocumentStatus.PROCESSING.value
        document.stage = ReviewStage.EXTRACTING.value
        document.progress = 1
        document.error_message = None
        document.started_at = datetime.now(timezone.utc)


def _complete_document(review_id: uuid.UUID, document_id: uuid.UUID, report: dict, matched_case: dict, detail: dict) -> None:
    with SessionLocal.begin() as session:
        document = session.get(ReviewDocument, document_id)
        review = session.get(Review, review_id)
        if document is None or review is None:
            return
        document.status = DocumentStatus.COMPLETED.value
        document.stage = ReviewStage.COMPLETED.value
        document.progress = 100
        document.algorithm_result = report
        document.matched_case = matched_case
        document.frontend_detail = detail
        document.error_message = None
        document.completed_at = datetime.now(timezone.utc)
        session.flush()
        review.completed_documents = int(session.scalar(select(func.count()).select_from(ReviewDocument).where(ReviewDocument.review_id == review_id, ReviewDocument.status == DocumentStatus.COMPLETED.value)) or 0)
        review.failed_documents = int(session.scalar(select(func.count()).select_from(ReviewDocument).where(ReviewDocument.review_id == review_id, ReviewDocument.status == DocumentStatus.FAILED.value)) or 0)
        review.progress = max(review.progress, int(((review.completed_documents + review.failed_documents) / max(1, review.total_documents)) * 100))


def _fail_document(review_id: str, document_id: uuid.UUID, work_path: Path, exc: Exception) -> None:
    work_path.mkdir(parents=True, exist_ok=True)
    error = f"{type(exc).__name__}: {exc}"
    try:
        (work_path / "task-error.log").write_text(traceback.format_exc(), encoding="utf-8")
    except Exception:
        logger.exception("Could not write task error log for review %s document %s", review_id, document_id)
    with SessionLocal.begin() as session:
        document = session.get(ReviewDocument, document_id)
        review = session.get(Review, uuid.UUID(review_id))
        if document is None or review is None:
            return
        document.status = DocumentStatus.FAILED.value
        document.stage = ReviewStage.FAILED.value
        document.progress = 100
        document.error_message = error[:8000]
        document.completed_at = datetime.now(timezone.utc)
        session.flush()
        review.completed_documents = int(session.scalar(select(func.count()).select_from(ReviewDocument).where(ReviewDocument.review_id == review.id, ReviewDocument.status == DocumentStatus.COMPLETED.value)) or 0)
        review.failed_documents = int(session.scalar(select(func.count()).select_from(ReviewDocument).where(ReviewDocument.review_id == review.id, ReviewDocument.status == DocumentStatus.FAILED.value)) or 0)
        review.progress = max(review.progress, int(((review.completed_documents + review.failed_documents) / max(1, review.total_documents)) * 100))
    logger.exception("Review %s document %s failed", review_id, document_id)


def _finalize_review(review_id: uuid.UUID) -> None:
    with SessionLocal.begin() as session:
        review = load_review(session, review_id, for_update=True)
        if review is None:
            return
        review.completed_documents = sum(item.status == DocumentStatus.COMPLETED.value for item in review.documents)
        review.failed_documents = sum(item.status == DocumentStatus.FAILED.value for item in review.documents)
        if review.completed_documents and review.failed_documents:
            review.status = ReviewStatus.PARTIAL_FAILED.value
        elif review.completed_documents:
            review.status = ReviewStatus.COMPLETED.value
        else:
            review.status = ReviewStatus.FAILED.value
        review.stage = ReviewStage.COMPLETED.value if review.completed_documents else ReviewStage.FAILED.value
        review.progress = 100
        review.completed_at = datetime.now(timezone.utc)
        if review.failed_documents:
            review.error_message = f"{review.failed_documents} 份文件处理失败；请查看文件状态或重新执行失败文件。"
        else:
            review.error_message = None
        summary = review_summary(review)
        review_path = review_directory(settings.storage_root, str(review.id))
    try:
        write_review_files(review_path, summary)
    except Exception:
        # PostgreSQL remains the source of truth; a report download can be
        # regenerated after a transient filesystem failure.
        logger.exception("Could not write run-level report files for review %s", review_id)


@celery_app.task(name="approval.run_review")
def run_review(review_id: str) -> None:
    parsed_id = uuid.UUID(review_id)
    with SessionLocal.begin() as session:
        review = load_review(session, parsed_id, for_update=True)
        if review is None:
            logger.warning("Review %s no longer exists", review_id)
            return
        if review.status != ReviewStatus.QUEUED.value:
            logger.info("Skip duplicate delivery for review %s in status %s", review_id, review.status)
            return
        review.status = ReviewStatus.PROCESSING.value
        review.stage = ReviewStage.EXTRACTING.value
        review.progress = max(1, review.progress)
        review.started_at = review.started_at or datetime.now(timezone.utc)
        review.error_message = None
        document_ids = [item.id for item in review.documents if item.status == DocumentStatus.QUEUED.value]
        total = len(review.documents)
        policy_rules_relative = review.policy_rules_path
        policy_rules_sha256 = review.policy_rules_sha256

    try:
        policy_rules_path = _resolve_review_path(review_id, policy_rules_relative)
        if not policy_rules_path.is_file():
            raise FileNotFoundError(f"政策规则快照不存在: {policy_rules_path}")
        if sha256_file(policy_rules_path) != policy_rules_sha256:
            raise RuntimeError("政策规则快照 SHA-256 与任务创建时不一致，已拒绝执行")
    except Exception as exc:
        for document_id in document_ids:
            with SessionLocal() as session:
                document = session.get(ReviewDocument, document_id)
                if document is None:
                    continue
                work_path = _resolve_review_path(review_id, document.work_path)
            _fail_document(review_id, document_id, work_path, exc)
        _finalize_review(parsed_id)
        return

    adapter = AlgorithmAdapter(settings)
    for document_id in document_ids:
        with SessionLocal() as session:
            snapshot = session.get(ReviewDocument, document_id)
            if snapshot is None:
                continue
            input_path = _resolve_review_path(review_id, snapshot.input_path)
            work_path = _resolve_review_path(review_id, snapshot.work_path)
            filename = snapshot.original_filename
        try:
            _mark_document_started(document_id)
            artifacts = adapter.run_document(
                case_id=str(document_id),
                input_path=input_path,
                policy_rules_path=policy_rules_path,
                work_path=work_path,
                progress=lambda stage, progress, current_document_id=document_id: _update_progress(parsed_id, current_document_id, total, stage, progress),
            )
            detail, _execution_failed = map_document_detail(
                review_id=review_id,
                document_id=str(document_id),
                file_name=filename,
                report=artifacts.report,
                matched_case=artifacts.matched_case,
            )
            write_frontend_detail(work_path / "results" / "frontend_detail.json", detail)
            _complete_document(parsed_id, document_id, artifacts.report, artifacts.matched_case, detail)
        except Exception as exc:
            _fail_document(review_id, document_id, work_path, exc)
    _finalize_review(parsed_id)


@celery_app.task(name="approval.requeue_queued_reviews")
def requeue_queued_reviews() -> int:
    """Recover the narrow commit-before-broker-publish failure window."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=30)
    with SessionLocal() as session:
        ids = list(session.scalars(select(Review.id).where(Review.status == ReviewStatus.QUEUED.value, Review.created_at < cutoff).limit(100)))
    for review_id in ids:
        run_review.delay(str(review_id))
    return len(ids)


@celery_app.task(name="approval.recover_stale_reviews")
def recover_stale_reviews() -> int:
    """Return abandoned processing rows to the queue after a conservative lease timeout."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.task_stale_after_minutes)
    recovered: list[uuid.UUID] = []
    with SessionLocal.begin() as session:
        reviews = list(session.scalars(
            select(Review)
            .where(Review.status == ReviewStatus.PROCESSING.value, Review.updated_at < cutoff)
            .with_for_update(skip_locked=True)
            .limit(20)
        ))
        for review in reviews:
            for document in review.documents:
                if document.status == DocumentStatus.PROCESSING.value:
                    document.status = DocumentStatus.QUEUED.value
                    document.stage = ReviewStage.QUEUED.value
                    document.progress = 0
                    document.error_message = "检测到 worker 超时退出，任务已自动重新排队。"
            review.status = ReviewStatus.QUEUED.value
            review.stage = ReviewStage.QUEUED.value
            review.progress = 0
            review.error_message = "检测到 worker 超时退出，任务已自动重新排队。"
            recovered.append(review.id)
    for review_id in recovered:
        run_review.delay(str(review_id))
    return len(recovered)
