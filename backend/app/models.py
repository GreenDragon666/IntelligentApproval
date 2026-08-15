"""PostgreSQL persistence models for review jobs and uploaded documents."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .enums import DocumentStatus, ReviewStage, ReviewStatus


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_reviews_progress"),
        CheckConstraint("total_documents > 0", name="ck_reviews_total_documents"),
        CheckConstraint("completed_documents >= 0 AND failed_documents >= 0", name="ck_reviews_document_counts"),
        CheckConstraint("status IN ('queued','processing','completed','partial_failed','failed')", name="ck_reviews_status"),
        Index("ix_reviews_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="live")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=ReviewStatus.QUEUED.value)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default=ReviewStage.QUEUED.value)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_documents: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_documents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_documents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    policy_rules_path: Mapped[str] = mapped_column(Text, nullable=False)
    policy_rules_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    documents: Mapped[list["ReviewDocument"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan",
        order_by="ReviewDocument.position",
    )


class ReviewDocument(Base):
    __tablename__ = "review_documents"
    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_review_documents_progress"),
        CheckConstraint("file_size >= 0", name="ck_review_documents_file_size"),
        CheckConstraint("status IN ('queued','processing','completed','failed')", name="ck_review_documents_status"),
        UniqueConstraint("review_id", "position", name="uq_review_documents_review_position"),
        Index("ix_review_documents_review_status", "review_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    stored_filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_extension: Mapped[str] = mapped_column(String(16), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_path: Mapped[str] = mapped_column(Text, nullable=False)
    work_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=DocumentStatus.QUEUED.value)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default=ReviewStage.QUEUED.value)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    algorithm_result: Mapped[dict | None] = mapped_column(JSONB)
    matched_case: Mapped[dict | None] = mapped_column(JSONB)
    frontend_detail: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    review: Mapped[Review] = relationship(back_populates="documents")
