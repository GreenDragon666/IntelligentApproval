"""逐页抽取 PDF 文本并保留物理页码/正文页码。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..page_schema import PageText


class PdfExtractionError(RuntimeError):
    """所有 PDF 提取器都不可用或外部提取器失败。"""

    pass


def _normalize(text: str) -> str:
    """清理 PDF 提取文本的换行/空行，不改变正文词序。"""
    lines = [line.rstrip() for line in str(text or "").replace("\r", "\n").split("\n")]
    compact: list[str] = []
    blank = False
    for line in lines:
        if line.strip():
            compact.append(line.strip())
            blank = False
        elif not blank:
            compact.append("")
            blank = True
    return "\n".join(compact).strip()


def _extract_with_fitz(path: Path) -> list[str] | None:
    """用 PyMuPDF 逐页提取；依赖不存在时返回 ``None`` 以便降级。"""
    try:
        import fitz
    except ImportError:
        return None
    document = fitz.open(str(path))
    try:
        return [_normalize(page.get_text("text", sort=True)) for page in document]
    finally:
        document.close()


def _extract_with_pypdf(path: Path) -> list[str] | None:
    """用 pypdf 逐页提取；作为 PyMuPDF 后备实现。"""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    reader = PdfReader(str(path))
    return [_normalize(page.extract_text() or "") for page in reader.pages]


def _extract_with_pdftotext(path: Path) -> list[str] | None:
    """调用系统 pdftotext 并按换页符恢复页边界。"""
    executable = shutil.which("pdftotext")
    if not executable:
        return None
    proc = subprocess.run(
        [executable, "-layout", str(path), "-"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if proc.returncode != 0:
        raise PdfExtractionError(proc.stderr.strip() or "pdftotext 执行失败")
    pages = proc.stdout.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return [_normalize(page) for page in pages]


def extract_pdf_pages(
    path: str | Path,
    *,
    document_page_1_pdf_page: int | None = None,
) -> list[PageText]:
    """按优先级选择 PDF 提取器，并为每页计算可选正文印刷页码。"""
    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    if document_page_1_pdf_page is not None and document_page_1_pdf_page < 1:
        raise ValueError("document_page_1_pdf_page 必须是正整数")
    texts: list[str] | None = None
    errors: list[str] = []
    for extractor in (_extract_with_fitz, _extract_with_pypdf, _extract_with_pdftotext):
        try:
            texts = extractor(pdf_path)
        except Exception as exc:
            errors.append(f"{extractor.__name__}: {exc!r}")
            continue
        if texts is not None:
            break
    if texts is None:
        raise PdfExtractionError(
            "缺少可用 PDF 提取器。请安装 PyMuPDF 或 pypdf，或提供 pdftotext。"
            + ("；" + "；".join(errors) if errors else "")
        )
    offset = None if document_page_1_pdf_page is None else 1 - document_page_1_pdf_page
    pages: list[PageText] = []
    for pdf_page, text in enumerate(texts, start=1):
        document_page = None
        if offset is not None and pdf_page >= document_page_1_pdf_page:
            document_page = pdf_page + offset
        pages.append(PageText(pdf_page=pdf_page, document_page=document_page, text=text))
    return pages


def extract_pdf_outline(path: str | Path) -> list[tuple[int, str, int]]:
    """返回 ``(层级, 标题, PDF页码)``；无书签或无 PyMuPDF 时返回空列表。"""

    try:
        import fitz
    except ImportError:
        return []
    try:
        document = fitz.open(str(path))
    except Exception:
        return []
    try:
        try:
            outline = []
            for level, title, page, *_ in document.get_toc(simple=True):
                if page >= 1 and str(title).strip():
                    outline.append((int(level), str(title).strip(), int(page)))
            return outline
        except Exception:
            return []
    finally:
        document.close()
