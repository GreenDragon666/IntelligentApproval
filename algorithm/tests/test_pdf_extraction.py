from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.dir_extr.pdf import extract_pdf_pages


class PdfExtractionFallbackTest(unittest.TestCase):
    def test_empty_fitz_result_falls_back_to_pdftotext(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pdf = Path(temporary) / "input.pdf"
            pdf.touch()
            with (
                patch("src.dir_extr.pdf._extract_with_fitz", return_value=["", ""]),
                patch("src.dir_extr.pdf._extract_with_pypdf", return_value=None),
                patch("src.dir_extr.pdf._extract_with_pdftotext", return_value=["第一页有效文本", "第二页有效文本"]) as fallback,
            ):
                pages = extract_pdf_pages(pdf, auto_detect_document_page=False)

        fallback.assert_called_once()
        self.assertEqual([page.text for page in pages], ["第一页有效文本", "第二页有效文本"])

    def test_usable_fitz_result_does_not_run_slower_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pdf = Path(temporary) / "input.pdf"
            pdf.touch()
            with (
                patch("src.dir_extr.pdf._extract_with_fitz", return_value=["这是一段足够长的可提取正文内容。" * 2]),
                patch("src.dir_extr.pdf._extract_with_pypdf") as pypdf,
                patch("src.dir_extr.pdf._extract_with_pdftotext") as pdftotext,
            ):
                pages = extract_pdf_pages(pdf, auto_detect_document_page=False)

        pypdf.assert_not_called()
        pdftotext.assert_not_called()
        self.assertEqual(len(pages), 1)


if __name__ == "__main__":
    unittest.main()
