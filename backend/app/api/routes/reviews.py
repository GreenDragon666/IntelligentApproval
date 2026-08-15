"""Review upload, progress, result, retry and artifact endpoints."""

from __future__ import annotations

import logging
import shutil
import uuid

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ...config import Settings, get_settings
from ...database import get_db
from ...enums import DocumentStatus, ReviewStage, ReviewStatus
from ...errors import AppError
from ...models import Review, ReviewDocument
from ...schemas import DocumentDetailResponse, ReviewJobResponse, ReviewStatusResponse, ReviewSummaryResponse
from ...services.report_files import write_review_files
from ...services.review_service import TERMINAL_REVIEW_STATUSES, load_review, public_job_status, reset_failed_for_retry, review_summary, sha256_file
from ...services.storage import UploadValidationError, document_directory, ensure_within, remove_review_directory, review_directory, save_upload
from ...tasks.review_tasks import run_review


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reviews", tags=["reviews"])


def _parse_id(value: str, label: str = "任务") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError) as exc:
        raise AppError(404, "NOT_FOUND", f"{label}不存在") from exc


def _get_review_or_404(db: Session, review_id: str, *, lock: bool = False) -> Review:
    review = load_review(db, _parse_id(review_id), for_update=lock)
    if review is None:
        raise AppError(404, "REVIEW_NOT_FOUND", "审查任务不存在")
    return review


def _get_document_or_404(review: Review, document_id: str) -> ReviewDocument:
    parsed_document_id = _parse_id(document_id, "文档")
    document = next((item for item in review.documents if item.id == parsed_document_id), None)
    if document is None:
        raise AppError(404, "DOCUMENT_NOT_FOUND", "审查任务中不存在该文档")
    return document


def _job(review: Review) -> ReviewJobResponse:
    return ReviewJobResponse(id=str(review.id), status=public_job_status(review.status))


def _status(review: Review) -> ReviewStatusResponse:
    return ReviewStatusResponse(
        id=str(review.id),
        status=public_job_status(review.status),
        internal_status=review.status,
        stage=review.stage,
        progress=review.progress,
        total_documents=review.total_documents,
        completed_documents=review.completed_documents,
        failed_documents=review.failed_documents,
        error_message=review.error_message,
        created_at=review.created_at,
        started_at=review.started_at,
        completed_at=review.completed_at,
        documents=[{
            "id": str(item.id),
            "fileName": item.original_filename,
            "status": item.status,
            "stage": item.stage,
            "progress": item.progress,
            "errorMessage": item.error_message,
        } for item in review.documents],
    )


@router.post("", response_model=ReviewJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_review(
    documents: list[UploadFile] = File(..., description="重复 documents 字段上传一至多份待审批文件"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ReviewJobResponse:
    if not documents:
        raise AppError(422, "DOCUMENTS_REQUIRED", "至少上传一份待审批文件")
    if len(documents) > settings.max_documents_per_review:
        raise AppError(422, "TOO_MANY_DOCUMENTS", f"单次最多上传 {settings.max_documents_per_review} 份文件")
    if not settings.policy_rules_path.is_file():
        raise AppError(503, "POLICY_RULES_UNAVAILABLE", "服务器政策规则文件不存在")

    review_id = uuid.uuid4()
    root = review_directory(settings.storage_root, str(review_id))
    root.mkdir(parents=True, exist_ok=False)
    try:
        rules_dir = root / "policy_rules"
        rules_dir.mkdir()
        rules_snapshot = rules_dir / settings.policy_rules_path.name
        shutil.copy2(settings.policy_rules_path, rules_snapshot)
        review = Review(
            id=review_id,
            mode="live",
            status=ReviewStatus.QUEUED.value,
            stage=ReviewStage.QUEUED.value,
            progress=0,
            total_documents=len(documents),
            policy_rules_path=str(rules_snapshot.relative_to(root)),
            policy_rules_sha256=sha256_file(rules_snapshot),
        )
        for position, upload in enumerate(documents):
            document_id = uuid.uuid4()
            document_root = document_directory(settings.storage_root, str(review_id), str(document_id))
            saved = await save_upload(
                upload,
                document_root / "input",
                max_bytes=settings.max_upload_bytes,
                chunk_bytes=settings.upload_chunk_bytes,
            )
            work_path = document_root / "work"
            review.documents.append(ReviewDocument(
                id=document_id,
                position=position,
                original_filename=saved.original_filename,
                stored_filename=saved.stored_filename,
                file_extension=saved.extension,
                file_size=saved.size,
                file_sha256=saved.sha256,
                input_path=str(saved.path.relative_to(root)),
                work_path=str(work_path.relative_to(root)),
                status=DocumentStatus.QUEUED.value,
                stage=ReviewStage.QUEUED.value,
                progress=0,
            ))
        db.add(review)
        db.commit()
        db.refresh(review)
    except UploadValidationError as exc:
        db.rollback()
        remove_review_directory(settings.storage_root, str(review_id))
        raise AppError(422, "INVALID_DOCUMENT", str(exc)) from exc
    except Exception:
        db.rollback()
        remove_review_directory(settings.storage_root, str(review_id))
        raise
    finally:
        for upload in documents:
            await upload.close()

    try:
        run_review.delay(str(review.id))
    except Exception:
        # Celery beat re-publishes queued rows, closing the DB-commit/broker-publish window.
        logger.exception("Initial task dispatch failed for review %s; recovery dispatcher will retry", review.id)
    return _job(review)


@router.get("/{review_id}/status", response_model=ReviewStatusResponse)
def get_review_status(review_id: str, db: Session = Depends(get_db)) -> ReviewStatusResponse:
    return _status(_get_review_or_404(db, review_id))


@router.get("/{review_id}", response_model=ReviewSummaryResponse)
def get_review_summary(review_id: str, db: Session = Depends(get_db)) -> dict:
    review = _get_review_or_404(db, review_id)
    if review.status not in TERMINAL_REVIEW_STATUSES:
        raise AppError(409, "REVIEW_NOT_READY", "审查尚未完成", {"status": public_job_status(review.status), "progress": review.progress})
    return review_summary(review)


@router.get("/{review_id}/documents/{document_id}", response_model=DocumentDetailResponse)
def get_document_detail(review_id: str, document_id: str, db: Session = Depends(get_db)) -> dict:
    review = _get_review_or_404(db, review_id)
    document = _get_document_or_404(review, document_id)
    if document.status in {DocumentStatus.QUEUED.value, DocumentStatus.PROCESSING.value}:
        raise AppError(409, "DOCUMENT_NOT_READY", "文档审查尚未完成", {"status": document.status, "progress": document.progress})
    if isinstance(document.frontend_detail, dict):
        return document.frontend_detail
    return {
        "schemaVersion": "1.0",
        "reviewId": review_id,
        "documentId": document_id,
        "fileName": document.original_filename,
        "overallConclusion": "insufficient",
        "rules": [],
    }


@router.post("/{review_id}/retry", response_model=ReviewJobResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_failed_documents(review_id: str, db: Session = Depends(get_db)) -> ReviewJobResponse:
    review = _get_review_or_404(db, review_id, lock=True)
    if review.status not in TERMINAL_REVIEW_STATUSES:
        raise AppError(409, "REVIEW_ACTIVE", "运行中的任务不能重新执行")
    count = reset_failed_for_retry(review)
    if not count:
        raise AppError(409, "NO_FAILED_DOCUMENTS", "该任务没有可重新执行的失败文件")
    db.commit()
    try:
        run_review.delay(str(review.id))
    except Exception:
        logger.exception("Retry dispatch failed for review %s; recovery dispatcher will retry", review.id)
    return _job(review)


def _artifact(review_id: str, relative: str, settings: Settings) -> FileResponse:
    root = review_directory(settings.storage_root, review_id)
    path = ensure_within(root, root / relative)
    if not path.is_file():
        raise AppError(404, "ARTIFACT_NOT_FOUND", "报告文件尚未生成或不存在")
    media_type = "text/markdown; charset=utf-8" if path.suffix == ".md" else "text/plain; charset=utf-8" if path.suffix == ".log" else "application/json"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/{review_id}/artifacts/brief")
def download_brief(review_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> FileResponse:
    review = _get_review_or_404(db, review_id)
    root = review_directory(settings.storage_root, review_id)
    if review.status in TERMINAL_REVIEW_STATUSES and not (root / "summary_brief.md").is_file():
        write_review_files(root, review_summary(review))
    return _artifact(review_id, "summary_brief.md", settings)


@router.get("/{review_id}/artifacts/summary")
def download_summary_json(review_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> FileResponse:
    review = _get_review_or_404(db, review_id)
    root = review_directory(settings.storage_root, review_id)
    if review.status in TERMINAL_REVIEW_STATUSES and not (root / "summary.json").is_file():
        write_review_files(root, review_summary(review))
    return _artifact(review_id, "summary.json", settings)


@router.get("/{review_id}/documents/{document_id}/artifacts/report")
def download_document_report(review_id: str, document_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> FileResponse:
    review = _get_review_or_404(db, review_id)
    document = _get_document_or_404(review, document_id)
    return _artifact(review_id, f"{document.work_path}/results/summary.md", settings)


@router.get("/{review_id}/documents/{document_id}/artifacts/algorithm-result")
def download_document_algorithm_result(review_id: str, document_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> FileResponse:
    review = _get_review_or_404(db, review_id)
    document = _get_document_or_404(review, document_id)
    return _artifact(review_id, f"{document.work_path}/results/summary.json", settings)


@router.get("/{review_id}/documents/{document_id}/artifacts/matched")
def download_document_matched_case(review_id: str, document_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> FileResponse:
    review = _get_review_or_404(db, review_id)
    document = _get_document_or_404(review, document_id)
    return _artifact(review_id, f"{document.work_path}/matched/rules_matched.json", settings)


@router.get("/{review_id}/documents/{document_id}/artifacts/log")
def download_document_log(review_id: str, document_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> FileResponse:
    review = _get_review_or_404(db, review_id)
    document = _get_document_or_404(review, document_id)
    return _artifact(review_id, f"{document.work_path}/algorithm.log", settings)


@router.get("/{review_id}/documents/{document_id}/artifacts/error-log")
def download_document_error_log(review_id: str, document_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> FileResponse:
    review = _get_review_or_404(db, review_id)
    document = _get_document_or_404(review, document_id)
    return _artifact(review_id, f"{document.work_path}/task-error.log", settings)
