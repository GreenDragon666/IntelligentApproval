"""Create review job and document tables.

Revision ID: 20260815_0001
Revises:
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260815_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("total_documents", sa.Integer(), nullable=False),
        sa.Column("completed_documents", sa.Integer(), nullable=False),
        sa.Column("failed_documents", sa.Integer(), nullable=False),
        sa.Column("policy_rules_path", sa.Text(), nullable=False),
        sa.Column("policy_rules_sha256", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("completed_documents >= 0 AND failed_documents >= 0", name="ck_reviews_document_counts"),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_reviews_progress"),
        sa.CheckConstraint("status IN ('queued','processing','completed','partial_failed','failed')", name="ck_reviews_status"),
        sa.CheckConstraint("total_documents > 0", name="ck_reviews_total_documents"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reviews_status_created_at", "reviews", ["status", "created_at"])
    op.create_table(
        "review_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("stored_filename", sa.Text(), nullable=False),
        sa.Column("file_extension", sa.String(length=16), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("input_path", sa.Text(), nullable=False),
        sa.Column("work_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("algorithm_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("matched_case", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("frontend_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("file_size >= 0", name="ck_review_documents_file_size"),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_review_documents_progress"),
        sa.CheckConstraint("status IN ('queued','processing','completed','failed')", name="ck_review_documents_status"),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id", "position", name="uq_review_documents_review_position"),
    )
    op.create_index("ix_review_documents_review_status", "review_documents", ["review_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_review_documents_review_status", table_name="review_documents")
    op.drop_table("review_documents")
    op.drop_index("ix_reviews_status_created_at", table_name="reviews")
    op.drop_table("reviews")
