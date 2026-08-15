"""Safe local/shared-volume storage for uploads and algorithm artifacts."""

from __future__ import annotations

import hashlib
import os
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


SUPPORTED_EXTENSIONS = frozenset({".pdf", ".doc", ".docx", ".docm", ".odt", ".rtf", ".wps", ".txt", ".md"})


class ReadableUpload(Protocol):
    filename: str | None

    async def read(self, size: int = -1) -> bytes: ...


class UploadValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SavedUpload:
    original_filename: str
    stored_filename: str
    path: Path
    size: int
    sha256: str
    extension: str


def safe_filename(value: str | None) -> str:
    """Return a display-friendly basename that cannot escape its upload directory."""
    candidate = (value or "").replace("\\", "/").split("/")[-1]
    candidate = unicodedata.normalize("NFKC", candidate)
    candidate = "".join(char for char in candidate if unicodedata.category(char) != "Cc")
    candidate = candidate.strip().strip(".")
    if not candidate:
        raise UploadValidationError("上传文件名为空")
    suffix = Path(candidate).suffix
    stem_limit = max(1, 180 - len(suffix))
    return f"{Path(candidate).stem[:stem_limit]}{suffix}"


def validate_extension(filename: str) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        supported = "、".join(sorted(SUPPORTED_EXTENSIONS))
        raise UploadValidationError(f"不支持的文件格式 {extension or '<无扩展名>'}；当前支持：{supported}")
    return extension


def ensure_within(root: Path, candidate: Path) -> Path:
    resolved_root = root.expanduser().resolve()
    resolved_candidate = candidate.expanduser().resolve()
    if resolved_candidate != resolved_root and resolved_root not in resolved_candidate.parents:
        raise ValueError(f"路径不在存储根目录中: {resolved_candidate}")
    return resolved_candidate


async def save_upload(upload: ReadableUpload, destination_dir: Path, *, max_bytes: int, chunk_bytes: int) -> SavedUpload:
    original = safe_filename(upload.filename)
    extension = validate_extension(original)
    destination_dir.mkdir(parents=True, exist_ok=True)
    final_path = destination_dir / original
    partial_path = destination_dir / f".{original}.uploading"
    digest = hashlib.sha256()
    total = 0
    try:
        with partial_path.open("wb") as handle:
            while True:
                chunk = await upload.read(chunk_bytes)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise UploadValidationError(f"文件 {original} 超过大小限制")
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if total == 0:
            raise UploadValidationError(f"文件 {original} 为空")
        os.replace(partial_path, final_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise
    return SavedUpload(original, final_path.name, final_path, total, digest.hexdigest(), extension)


def review_directory(storage_root: Path, review_id: str) -> Path:
    return ensure_within(storage_root, storage_root / review_id)


def document_directory(storage_root: Path, review_id: str, document_id: str) -> Path:
    return ensure_within(storage_root, review_directory(storage_root, review_id) / "documents" / document_id)


def remove_review_directory(storage_root: Path, review_id: str) -> None:
    target = review_directory(storage_root, review_id)
    if target.exists():
        shutil.rmtree(target)

