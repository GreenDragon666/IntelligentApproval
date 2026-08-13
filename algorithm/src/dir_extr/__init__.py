"""步骤一：提取多格式文档的逐页文本、目录并拆分章节。"""

from .documents import DocumentExtractionError, ExtractedDocument, SUPPORTED_DOCUMENT_EXTENSIONS, extract_document, is_supported_document
from .pdf import PdfExtractionError, extract_pdf_outline, extract_pdf_pages
from .sections import split_sections

__all__ = [
    "DocumentExtractionError",
    "ExtractedDocument",
    "PdfExtractionError",
    "SUPPORTED_DOCUMENT_EXTENSIONS",
    "extract_document",
    "extract_pdf_outline",
    "extract_pdf_pages",
    "is_supported_document",
    "split_sections",
]
