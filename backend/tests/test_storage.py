from __future__ import annotations

import tempfile
import unittest
from asyncio import run
from pathlib import Path

from app.services.storage import UploadValidationError, ensure_within, safe_filename, save_upload, validate_extension


class FakeUpload:
    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self.content = content
        self.offset = 0

    async def read(self, size: int = -1) -> bytes:
        if self.offset >= len(self.content):
            return b""
        end = len(self.content) if size < 0 else self.offset + size
        chunk = self.content[self.offset:end]
        self.offset += len(chunk)
        return chunk


class StorageSafetyTests(unittest.TestCase):
    def test_filename_removes_path_components(self) -> None:
        self.assertEqual(safe_filename("../../采购/招标文件.pdf"), "招标文件.pdf")
        self.assertEqual(safe_filename(r"C:\temp\rules.docx"), "rules.docx")

    def test_extension_is_case_insensitive(self) -> None:
        self.assertEqual(validate_extension("REPORT.PDF"), ".pdf")

    def test_unsupported_extension_is_rejected(self) -> None:
        with self.assertRaises(UploadValidationError):
            validate_extension("payload.exe")

    def test_path_cannot_escape_storage_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(ensure_within(root, root / "a/b"), (root / "a/b").resolve())
            with self.assertRaises(ValueError):
                ensure_within(root, root / "../outside")

    def test_upload_is_hashed_and_atomically_saved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = run(save_upload(FakeUpload("招标文件.pdf", b"abc"), Path(temporary), max_bytes=10, chunk_bytes=2))
            self.assertEqual(result.size, 3)
            self.assertEqual(result.sha256, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
            self.assertEqual(result.path.read_bytes(), b"abc")
            self.assertFalse((Path(temporary) / ".招标文件.pdf.uploading").exists())

    def test_oversized_upload_removes_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(UploadValidationError):
                run(save_upload(FakeUpload("large.pdf", b"12345"), Path(temporary), max_bytes=4, chunk_bytes=2))
            self.assertEqual(list(Path(temporary).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
