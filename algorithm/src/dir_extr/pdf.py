"""逐页抽取 PDF 文本并保留物理页码/正文页码。"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..page_schema import PageText


class PdfExtractionError(RuntimeError):
    """所有 PDF 提取器都不可用或外部提取器失败。"""

    pass


@dataclass(frozen=True)
class PageNumberObservation:
    """从某个 PDF 页眉或页脚识别到的印刷页码。"""

    pdf_page: int
    document_page: int
    region: str
    alignment: str
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PageNumberDetection:
    """正文印刷第 1 页的自动检测结果及可追溯依据。"""

    document_page_1_pdf_page: int | None
    confidence: float
    method: str
    observations: list[PageNumberObservation] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "document_page_1_pdf_page": self.document_page_1_pdf_page,
            "confidence": round(self.confidence, 4),
            "method": self.method,
            "observations": [observation.to_dict() for observation in self.observations],
            "reason": self.reason,
        }


_PAGE_NUMBER_PATTERNS = (
    re.compile(r"^(\d{1,4})$"),
    re.compile(r"^[-—–－~～·•]*(\d{1,4})[-—–－~～·•]*$"),
    re.compile(r"^第(\d{1,4})页(?:[/／共](\d{1,4})页?)?$"),
    re.compile(r"^(\d{1,4})[/／](\d{1,4})$"),
    re.compile(r"^页码[:：]?(\d{1,4})$"),
)


def _page_number(text: str) -> int | None:
    """解析一整行常见页码格式，拒绝混在正文中的普通数字。"""
    compact = re.sub(r"\s+", "", text).strip()
    for pattern in _PAGE_NUMBER_PATTERNS:
        match = pattern.fullmatch(compact)
        if match:
            value = int(match.group(1))
            return value if value >= 1 else None
    return None


def _alignment(x0: float, x1: float, width: float) -> str:
    center = (x0 + x1) / 2 / width
    if center < 0.35:
        return "left"
    if center > 0.65:
        return "right"
    return "center"


def _page_observations(page, pdf_page: int) -> list[PageNumberObservation]:
    """只在页眉/页脚区域按视觉行识别页码。"""
    height = float(page.rect.height)
    width = float(page.rect.width)
    lines: dict[tuple[int, int], list[tuple]] = defaultdict(list)
    for word in page.get_text("words", sort=True):
        if len(word) < 7:
            continue
        lines[(int(word[5]), int(word[6]))].append(word)

    observations: list[PageNumberObservation] = []
    for words in lines.values():
        words.sort(key=lambda item: float(item[0]))
        x0 = min(float(word[0]) for word in words)
        y0 = min(float(word[1]) for word in words)
        x1 = max(float(word[2]) for word in words)
        y1 = max(float(word[3]) for word in words)
        if y1 <= height * 0.12:
            region = "header"
        elif y0 >= height * 0.82:
            region = "footer"
        else:
            continue
        text = "".join(str(word[4]) for word in words)
        document_page = _page_number(text)
        if document_page is None:
            continue
        observations.append(
            PageNumberObservation(
                pdf_page=pdf_page,
                document_page=document_page,
                region=region,
                alignment=_alignment(x0, x1, width),
                text=text,
            )
        )
    return observations


def _longest_consecutive(observations: list[PageNumberObservation]) -> int:
    pages = sorted({observation.pdf_page for observation in observations})
    longest = current = 0
    previous = None
    for page in pages:
        current = current + 1 if previous is not None and page == previous + 1 else 1
        longest = max(longest, current)
        previous = page
    return longest


def _sequence_detection(document) -> PageNumberDetection:
    grouped: dict[tuple[int, str], list[PageNumberObservation]] = defaultdict(list)
    for page_index, page in enumerate(document):
        pdf_page = page_index + 1
        for observation in _page_observations(page, pdf_page):
            candidate_start = pdf_page - observation.document_page + 1
            if 1 <= candidate_start <= pdf_page:
                grouped[(candidate_start, observation.region)].append(observation)

    candidates = []
    for (candidate_start, region), observations in grouped.items():
        deduplicated = {observation.pdf_page: observation for observation in observations}
        observations = [deduplicated[page] for page in sorted(deduplicated)]
        longest = _longest_consecutive(observations)
        if longest < 3:
            continue
        alignments = {observation.alignment for observation in observations}
        alignment = next(iter(alignments)) if len(alignments) == 1 else "alternating"
        candidates.append(
            (
                longest,
                len(observations),
                any(item.document_page == 1 for item in observations),
                region == "footer",
                candidate_start,
                region,
                alignment,
                observations,
            )
        )
    if not candidates:
        return PageNumberDetection(
            document_page_1_pdf_page=None,
            confidence=0.0,
            method="not_detected",
            reason="未在页眉或页脚发现至少连续 3 页的印刷页码序列",
        )

    candidates.sort(reverse=True, key=lambda item: item[:4])
    best = candidates[0]
    conflicting = [
        item
        for item in candidates[1:]
        if item[4] != best[4] and item[0] >= best[0] - 1
    ]
    if conflicting:
        return PageNumberDetection(
            document_page_1_pdf_page=None,
            confidence=0.0,
            method="ambiguous",
            observations=best[7][:10],
            reason=f"发现多个强度接近但偏移不同的页码序列: {best[4]} 与 {conflicting[0][4]}",
        )

    longest, count, has_page_one, is_footer, candidate_start, region, alignment, observations = best
    confidence = 0.9
    if longest >= 5:
        confidence += 0.05
    if has_page_one:
        confidence += 0.02
    if is_footer:
        confidence += 0.01
    return PageNumberDetection(
        document_page_1_pdf_page=candidate_start,
        confidence=min(confidence, 0.99),
        method="header_footer_sequence",
        observations=observations[:10],
        reason=f"{region}/{alignment} 检测到 {count} 个页码，最长连续 {longest} 页",
    )


def _page_label_start(document) -> int | None:
    """读取 PDF Page Labels 中从 1 开始的十进制页码段。"""
    try:
        labels = document.get_page_labels()
    except (AttributeError, RuntimeError, ValueError):
        return None
    for label in labels or []:
        if label.get("style") != "D":
            continue
        if int(label.get("firstpagenum", 1)) == 1:
            return int(label.get("startpage", 0)) + 1
    return None


def detect_document_page_1(path: str | Path) -> PageNumberDetection:
    """自动推断正文印刷第 1 页对应的 PDF 物理页，不可靠时返回空结果。"""
    try:
        import fitz
    except ImportError:
        return PageNumberDetection(
            document_page_1_pdf_page=None,
            confidence=0.0,
            method="unavailable",
            reason="自动页码检测需要 PyMuPDF",
        )
    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    try:
        document = fitz.open(str(pdf_path))
        try:
            label_start = _page_label_start(document)
            sequence = _sequence_detection(document)
        finally:
            document.close()
    except Exception as exc:
        return PageNumberDetection(
            document_page_1_pdf_page=None,
            confidence=0.0,
            method="unavailable",
            reason=f"自动页码检测失败: {type(exc).__name__}: {exc}",
        )

    if label_start is not None and sequence.document_page_1_pdf_page == label_start:
        return PageNumberDetection(
            document_page_1_pdf_page=label_start,
            confidence=1.0,
            method="page_labels_and_sequence",
            observations=sequence.observations,
            reason="PDF Page Labels 与页眉/页脚连续页码一致",
        )
    if sequence.document_page_1_pdf_page is not None:
        reason = sequence.reason
        if label_start is not None:
            reason += f"；可见页码与 PDF Page Labels({label_start}) 不一致，采用可见页码"
        return PageNumberDetection(
            document_page_1_pdf_page=sequence.document_page_1_pdf_page,
            confidence=sequence.confidence,
            method=sequence.method,
            observations=sequence.observations,
            reason=reason,
        )
    if label_start is not None:
        return PageNumberDetection(
            document_page_1_pdf_page=label_start,
            confidence=0.98,
            method="page_labels",
            reason="使用 PDF 内置十进制 Page Labels",
        )
    return sequence


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
    auto_detect_document_page: bool = True,
) -> list[PageText]:
    """按优先级选择 PDF 提取器，并为每页计算可选正文印刷页码。"""
    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    if document_page_1_pdf_page is not None and document_page_1_pdf_page < 1:
        raise ValueError("document_page_1_pdf_page 必须是正整数")
    if document_page_1_pdf_page is None and auto_detect_document_page:
        document_page_1_pdf_page = detect_document_page_1(pdf_path).document_page_1_pdf_page
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
