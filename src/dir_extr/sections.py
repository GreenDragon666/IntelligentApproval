"""根据 PDF 书签或招标文件常见标题模式构建章节。"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..page_schema import DocumentSection, PageText

_HEADING_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十百零〇\d]+[章节篇卷]\s*.+$"),
    re.compile(r"^[一二三四五六七八九十]+[、.．]\s*\S.+$"),
    re.compile(r"^\d+(?:\.\d+){0,3}[、.．\s]+\S.+$"),
    re.compile(r"^(招标公告|投标人须知|评标办法|合同条款及格式|委托人要求|投标文件格式)$"),
]


def _heading_from_page(page: PageText) -> str | None:
    """从页面开头寻找通用中文章/节/编号标题。"""
    lines = [line.strip() for line in page.text.splitlines() if line.strip()]
    for line in lines[:30]:
        if len(line) > 80:
            continue
        if any(pattern.fullmatch(line) for pattern in _HEADING_PATTERNS):
            return line
    return None


def _make_section(title: str, pages: list[PageText]) -> DocumentSection:
    """把连续页打包成章节，保留双页码并给原文添加物理页标记。"""
    document_pages = [page.document_page for page in pages if page.document_page is not None]
    text = "\n\n".join(
        f"[PDF第{page.pdf_page}页]\n{page.text}" for page in pages if page.text
    )
    return DocumentSection(
        title=title,
        pdf_start=pages[0].pdf_page,
        pdf_end=pages[-1].pdf_page,
        document_start=document_pages[0] if document_pages else None,
        document_end=document_pages[-1] if document_pages else None,
        text=text,
    )


def _split_long(
    title: str,
    pages: list[PageText],
    max_pages: int,
) -> Iterable[DocumentSection]:
    """将超长章节按固定最大页数切成多个可检索块。"""
    for offset in range(0, len(pages), max_pages):
        chunk = pages[offset:offset + max_pages]
        suffix = "" if len(pages) <= max_pages else f"（第{offset // max_pages + 1}部分）"
        yield _make_section(title + suffix, chunk)


def _from_outline(
    pages: list[PageText],
    outline: list[tuple[int, str, int]],
    max_pages: int,
) -> list[DocumentSection]:
    """使用 PDF 书签的起始页切分章节。"""
    starts: list[tuple[int, str]] = []
    seen_pages: set[int] = set()
    for _level, title, page in sorted(outline, key=lambda item: item[2]):
        if page < 1 or page > len(pages) or page in seen_pages:
            continue
        seen_pages.add(page)
        starts.append((page, title))
    if starts and starts[0][0] > 1:
        starts.insert(0, (1, "文档开始"))
    sections: list[DocumentSection] = []
    for index, (start, title) in enumerate(starts):
        end = starts[index + 1][0] - 1 if index + 1 < len(starts) else len(pages)
        sections.extend(_split_long(title, pages[start - 1:end], max_pages))
    return sections


def _heuristic(pages: list[PageText], max_pages: int) -> list[DocumentSection]:
    """PDF 无书签时，使用页首标题启发式切分。"""
    groups: list[tuple[str, list[PageText]]] = []
    current_title = "文档开始"
    current_pages: list[PageText] = []
    for page in pages:
        heading = _heading_from_page(page)
        if heading and current_pages:
            groups.append((current_title, current_pages))
            current_pages = []
        if heading:
            current_title = heading
        current_pages.append(page)
    if current_pages:
        groups.append((current_title, current_pages))
    sections: list[DocumentSection] = []
    for title, group_pages in groups:
        sections.extend(_split_long(title, group_pages, max_pages))
    return sections


def split_sections(
    pages: list[PageText],
    *,
    outline: list[tuple[int, str, int]] | None = None,
    max_pages: int = 8,
) -> list[DocumentSection]:
    """章节拆分对外入口：书签优先，通用标题启发式兜底。"""
    if not pages:
        return []
    if max_pages < 1:
        raise ValueError("max_pages 必须大于 0")
    if outline:
        sections = _from_outline(pages, outline, max_pages)
        if sections:
            return sections
    return _heuristic(pages, max_pages)
