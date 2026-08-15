"""Validated backend configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_REPOSITORY_ROOT / ".env"), str(_REPOSITORY_ROOT / "backend/.env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "IntelligentApproval API"
    environment: str = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:5173"

    database_url: str = "postgresql+psycopg://approval:approval@127.0.0.1:5432/intelligent_approval"
    redis_url: str = "redis://127.0.0.1:6379/0"

    storage_root: Path = _REPOSITORY_ROOT / "runtime/reviews"
    algorithm_root: Path = _REPOSITORY_ROOT / "algorithm"
    policy_rules_path: Path = _REPOSITORY_ROOT / "data/招标文件预警规则梳理_V1.0_yy_20260610.xlsx"
    max_upload_bytes: int = 30 * 1024 * 1024
    max_documents_per_review: int = 10
    upload_chunk_bytes: int = 1024 * 1024

    algorithm_use_embedding: bool = True
    algorithm_use_llm_matching: bool = True
    algorithm_strict_llm: bool = True
    algorithm_enable_llm_check: bool = True
    algorithm_llm_review: bool = False
    algorithm_max_section_pages: int = 8
    algorithm_candidate_count: int = 8
    algorithm_evidence_count: int = 3
    algorithm_minimum_score: float = 0.03
    algorithm_match_workers: int | None = None
    algorithm_check_workers: int | None = None
    task_stale_after_minutes: int = 360

    @field_validator("database_url")
    @classmethod
    def require_postgresql(cls, value: str) -> str:
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL 必须使用 postgresql+psycopg:// PostgreSQL 连接地址")
        return value

    @field_validator("redis_url")
    @classmethod
    def require_redis(cls, value: str) -> str:
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("REDIS_URL 必须是 redis:// 或 rediss:// 连接地址")
        return value

    @field_validator("storage_root", "algorithm_root", "policy_rules_path", mode="after")
    @classmethod
    def resolve_paths(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @model_validator(mode="after")
    def validate_ranges(self) -> "Settings":
        if self.max_upload_bytes < 1 or self.upload_chunk_bytes < 1:
            raise ValueError("上传大小和分块配置必须大于 0")
        if not 1 <= self.max_documents_per_review <= 100:
            raise ValueError("MAX_DOCUMENTS_PER_REVIEW 必须在 1 到 100 之间")
        if not 1 <= self.algorithm_evidence_count <= 3:
            raise ValueError("ALGORITHM_EVIDENCE_COUNT 必须在 1 到 3 之间")
        if self.algorithm_candidate_count < self.algorithm_evidence_count:
            raise ValueError("ALGORITHM_CANDIDATE_COUNT 不得小于 ALGORITHM_EVIDENCE_COUNT")
        if self.algorithm_minimum_score < 0:
            raise ValueError("ALGORITHM_MINIMUM_SCORE 不得小于 0")
        if self.algorithm_max_section_pages < 1:
            raise ValueError("ALGORITHM_MAX_SECTION_PAGES 必须大于 0")
        if self.task_stale_after_minutes < 30:
            raise ValueError("TASK_STALE_AFTER_MINUTES 不得小于 30")
        for name, value in (("ALGORITHM_MATCH_WORKERS", self.algorithm_match_workers), ("ALGORITHM_CHECK_WORKERS", self.algorithm_check_workers)):
            if value is not None and value < 1:
                raise ValueError(f"{name} 必须大于 0")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
