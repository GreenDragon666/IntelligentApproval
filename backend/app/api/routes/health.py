"""Liveness and dependency readiness probes."""

from fastapi import APIRouter, Depends
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...config import get_settings
from ...database import get_db
from ...errors import AppError


router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    return readiness(db)


def readiness(db: Session) -> dict[str, str]:
    settings = get_settings()
    failures: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        failures["postgresql"] = f"{type(exc).__name__}: {exc}"
    try:
        Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2).ping()
    except Exception as exc:
        failures["redis"] = f"{type(exc).__name__}: {exc}"
    if not settings.algorithm_root.is_dir():
        failures["algorithm"] = f"目录不存在: {settings.algorithm_root}"
    if not settings.policy_rules_path.is_file():
        failures["policyRules"] = f"文件不存在: {settings.policy_rules_path}"
    if failures:
        raise AppError(503, "SERVICE_NOT_READY", "服务依赖尚未就绪", failures)
    return {"status": "ok"}
