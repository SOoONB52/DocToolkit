"""Count words in PDF pages.

Reads the text layer of each page with pypdfium2. Pages with no text layer
(usually scanned images) are reported as such instead of silently counting 0.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pypdfium2 as pdfium

from app.core.pdfium_lock import PDFIUM_LOCK


class PdfPasswordRequired(Exception):
    pass


THUMB_HEIGHT = 240  # pixels; enough to be crisp in the list


@dataclass
class PageCount:
    page: int              # 1-based
    words: int
    chars: int             # characters excluding whitespace
    has_text: bool
    thumb: str | None = None      # picture of the page, if one could be made
    preview_text: str = ""        # used to draw a preview when there is no picture
    approximate: bool = False     # True for Word files paginated without Word


def count_words(text: str) -> int:
    """Words are runs of non-space characters (how Word and most counters do it)."""
    return len(text.split())


def count_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def analyse_pdf(
    path: str,
    password: str | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    thumb_dir: str | None = None,
) -> list[PageCount]:
    with PDFIUM_LOCK:
        try:
            doc = pdfium.PdfDocument(path, password=password)
        except pdfium.PdfiumError as exc:
            if "password" in str(exc).lower():
                raise PdfPasswordRequired(path) from exc
            raise
        try:
            total = len(doc)
            results: list[PageCount] = []
            for index in range(total):
                if cancelled and cancelled():
                    break
                if progress:
                    progress(index + 1, total)
                page = doc[index]
                textpage = page.get_textpage()
                thumb = None
                try:
                    text = textpage.get_text_range()
                    if thumb_dir:
                        scale = THUMB_HEIGHT / max(page.get_height(), 1)
                        thumb = str(Path(thumb_dir) / f"page_{index + 1:05d}.png")
                        page.render(scale=scale).to_pil().save(thumb, "PNG")
                finally:
                    textpage.close()
                    page.close()
                chars = count_chars(text)
                results.append(PageCount(index + 1, count_words(text), chars, chars > 0, thumb))
            return results
        finally:
            doc.close()


_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def parse_page_range(text: str, total: int) -> set[int]:
    """'1-5, 8, 10-12' -> {1,2,3,4,5,8,10,11,12}. Accepts Arabic digits and commas.

    Raises ValueError if the text can't be understood or pages are out of range.
    """
    cleaned = text.translate(_ARABIC_DIGITS).replace("،", ",").replace("–", "-").replace("—", "-")
    pages: set[int] = set()
    for part in cleaned.split(","):
        part = part.strip()
        if not part:
            continue
        match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            if start > end:
                start, end = end, start
        elif part.isdigit():
            start = end = int(part)
        else:
            raise ValueError(part)
        if start < 1 or end > total:
            raise ValueError(part)
        pages.update(range(start, end + 1))
    if not pages:
        raise ValueError(text)
    return pages
