"""统一文档提取适配器：不同源格式归一为分页文本和目录。"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from xml.etree import ElementTree

from ..page_schema import PageText
from .pdf import extract_pdf_outline, extract_pdf_pages


PDF_EXTENSIONS = frozenset({".pdf"})
OFFICE_EXTENSIONS = frozenset({".doc", ".docx", ".docm", ".odt", ".rtf", ".wps"})
TEXT_EXTENSIONS = frozenset({".txt", ".md"})
SUPPORTED_DOCUMENT_EXTENSIONS = PDF_EXTENSIONS | OFFICE_EXTENSIONS | TEXT_EXTENSIONS

_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{_WORD_NAMESPACE}}}"


class DocumentExtractionError(RuntimeError):
    """文档格式不支持、转换失败或文本无法提取。"""


@dataclass(frozen=True)
class ExtractedDocument:
    pages: list[PageText]
    outline: list[tuple[int, str, int]]
    source_format: str
    extraction_method: str
    page_basis: str


def is_supported_document(path: str | Path) -> bool:
    """判断文件扩展名是否属于当前可处理文档格式。"""
    return Path(path).suffix.lower() in SUPPORTED_DOCUMENT_EXTENSIONS


def _normalize(text: str) -> str:
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


def _to_pages(texts: list[str], document_page_1_pdf_page: int | None, page_label: str) -> list[PageText]:
    if document_page_1_pdf_page is not None and document_page_1_pdf_page < 1:
        raise ValueError("document_page_1_pdf_page 必须是正整数")
    offset = None if document_page_1_pdf_page is None else 1 - document_page_1_pdf_page
    pages = []
    for page_number, text in enumerate(texts, start=1):
        document_page = page_number + offset if offset is not None and page_number >= document_page_1_pdf_page else None
        pages.append(PageText(pdf_page=page_number, document_page=document_page, text=_normalize(text), page_label=page_label))
    return pages


def _find_office_binary() -> str | None:
    return shutil.which("libreoffice") or shutil.which("soffice")


def _convert_office_to_pdf(source: Path, work: Path) -> Path:
    executable = _find_office_binary()
    if not executable:
        raise DocumentExtractionError("未找到 LibreOffice/soffice")
    output_dir = work / "output"
    profile_dir = work / "profile"
    output_dir.mkdir()
    profile_dir.mkdir()
    command = [executable, f"-env:UserInstallation={profile_dir.resolve().as_uri()}", "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(source)]
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    expected = output_dir / f"{source.stem}.pdf"
    if proc.returncode != 0 or not expected.is_file():
        generated = sorted(output_dir.glob("*.pdf"))
        if proc.returncode == 0 and len(generated) == 1:
            return generated[0]
        detail = (proc.stdout + proc.stderr).strip() or "未生成 PDF"
        raise DocumentExtractionError(f"LibreOffice 转换失败: {detail}")
    return expected


def _paragraph_text(element: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in element.iter():
        if node.tag == _W + "t":
            parts.append(node.text or "")
        elif node.tag == _W + "tab":
            parts.append("\t")
        elif node.tag == _W + "lastRenderedPageBreak":
            parts.append("\f")
        elif node.tag == _W + "br":
            parts.append("\f" if node.get(_W + "type") == "page" else "\n")
    return "".join(parts)


def _table_text(table: ElementTree.Element) -> str:
    rows = []
    for row in table.findall("./w:tr", {"w": _WORD_NAMESPACE}):
        cells = []
        for cell in row.findall("./w:tc", {"w": _WORD_NAMESPACE}):
            paragraphs = [_paragraph_text(paragraph) for paragraph in cell.findall("./w:p", {"w": _WORD_NAMESPACE})]
            cells.append("\n".join(text for text in paragraphs if text))
        rows.append("\t".join(cells))
    return "\n".join(row for row in rows if row)


def _extract_docx_xml(path: Path, document_page_1_pdf_page: int | None) -> list[PageText]:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        raise DocumentExtractionError(f"DOCX 结构无法读取: {exc}") from exc
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise DocumentExtractionError(f"DOCX XML 无法解析: {exc}") from exc
    body = root.find(".//w:body", {"w": _WORD_NAMESPACE})
    if body is None:
        raise DocumentExtractionError("DOCX 缺少 word/document.xml 正文")
    blocks = []
    for child in body:
        if child.tag == _W + "p":
            blocks.append(_paragraph_text(child))
        elif child.tag == _W + "tbl":
            blocks.append(_table_text(child))
    raw_pages = "\n".join(blocks).split("\f")
    if len(raw_pages) > 1 and not raw_pages[-1].strip():
        raw_pages.pop()
    return _to_pages(raw_pages or [""], document_page_1_pdf_page, "DOCX逻辑")


def _read_text(path: Path) -> str:
    errors = []
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}: {exc}")
    raise DocumentExtractionError("文本文件编码无法识别: " + "；".join(errors))


def extract_document(path: str | Path, *, document_page_1_pdf_page: int | None = None, converted_pdf_output: str | Path | None = None) -> ExtractedDocument:
    """按格式提取文档，并归一为现有分页文本模型。"""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
        raise DocumentExtractionError(f"不支持的文档格式 {suffix or '<无扩展名>'}；当前支持: {supported}")

    if suffix in PDF_EXTENSIONS:
        return ExtractedDocument(pages=extract_pdf_pages(source, document_page_1_pdf_page=document_page_1_pdf_page), outline=extract_pdf_outline(source), source_format="pdf", extraction_method="pdf_text", page_basis="original_pdf")

    if suffix in TEXT_EXTENSIONS:
        texts = _read_text(source).split("\f")
        return ExtractedDocument(pages=_to_pages(texts, document_page_1_pdf_page, "文本逻辑"), outline=[], source_format=suffix[1:], extraction_method="plain_text", page_basis="logical_page")

    conversion_error = ""
    try:
        with tempfile.TemporaryDirectory() as temporary:
            converted_pdf = _convert_office_to_pdf(source, Path(temporary))
            pages = [replace(page, page_label="转换PDF") for page in extract_pdf_pages(converted_pdf, document_page_1_pdf_page=document_page_1_pdf_page)]
            outline = extract_pdf_outline(converted_pdf)
            if converted_pdf_output is not None:
                preserved_pdf = Path(converted_pdf_output)
                preserved_pdf.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(converted_pdf, preserved_pdf)
            return ExtractedDocument(pages=pages, outline=outline, source_format=suffix[1:], extraction_method="libreoffice_pdf", page_basis="converted_pdf")
    except Exception as exc:
        conversion_error = f"{type(exc).__name__}: {exc}"

    if suffix in {".docx", ".docm"}:
        pages = _extract_docx_xml(source, document_page_1_pdf_page)
        return ExtractedDocument(pages=pages, outline=[], source_format=suffix[1:], extraction_method="docx_xml_fallback", page_basis="logical_page")

    raise DocumentExtractionError(f"{suffix} 需要 LibreOffice/soffice 转换为 PDF；转换详情: {conversion_error}")
