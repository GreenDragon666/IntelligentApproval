"""Backend-owned lifecycle enums.

Values are stored as strings in PostgreSQL so operational data remains easy to
inspect and migrations do not depend on PostgreSQL enum type changes.
"""

from enum import Enum


class ReviewStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"


class DocumentStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReviewStage(str, Enum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    MATCHING = "matching"
    CHECKING = "checking"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
