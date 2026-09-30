"""Get images out of PDF files.

Embedded images are extracted with pikepdf (original quality, duplicates skipped).
Images pikepdf cannot decode fall back to rendering that page with pypdfium2.
PDFium is not thread-safe: only call these functions from one thread at a time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import pikepdf
import pypdfium2 as pdfium
from pikepdf import Name, PdfImage

from app.core.pdfium_lock import PDFIUM_LOCK

MIN_SIDE = 20        # skip tiny images (bullets, lines, spacer pixels)
RENDER_DPI = 300     # good resolution for OCR


class PdfPasswordRequired(Exception):
    """The PDF is encrypted and the password is missing or wrong."""


@dataclass
class PdfImageItem:
    label: str   # shown in the list and used in the FILE: header
    path: str    # temporary PNG on disk


@dataclass
class PdfExtractResult:
    source: str
    images: list[PdfImageItem] = field(default_factory=list)
    skipped_small: int = 0
    rendered_pages: list[int] = field(default_factory=list)


Progress = Callable[[int, int], None]
Cancelled = Callable[[], bool]


def _open(path: Path, password: str | None) -> pikepdf.Pdf:
    try:
        return pikepdf.open(path, password=password or "")
    except pikepdf.PasswordError as exc:
        raise PdfPasswordRequired(str(path)) from exc


def _page_resources(page_obj):
    """Resources may be inherited from a parent node in the page tree."""
    node = page_obj
    while node is not None:
        resources = node.get("/Resources")
        if resources is not None:
            return resources
        node = node.get("/Parent")
    return None


def _image_objects(resources, seen_forms: set) -> Iterator[pikepdf.Object]:
    """Images on the page, including ones nested inside form objects."""
    if resources is None:
        return
    xobjects = resources.get("/XObject")
    if xobjects is None:
        return
    for key in list(xobjects.keys()):
        obj = xobjects[key]
        subtype = obj.get("/Subtype")
        if subtype == Name.Image:
            yield obj
        elif subtype == Name.Form:
            key_id = obj.objgen
            if key_id != (0, 0) and key_id in seen_forms:
                continue
            seen_forms.add(key_id)
            yield from _image_objects(obj.get("/Resources"), seen_forms)


def _saveable(img):
    return img if img.mode in ("RGB", "RGBA", "L", "LA", "1", "P") else img.convert("RGB")


def _render_page(doc: pdfium.PdfDocument, page_no: int, out_file: Path) -> None:
    with PDFIUM_LOCK:
        page = doc[page_no - 1]
        page.render(scale=RENDER_DPI / 72).to_pil().save(out_file, "PNG")


def extract_images(
    pdf_path: str,
    out_dir: str,
    password: str | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> PdfExtractResult:
    src = Path(pdf_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = PdfExtractResult(source=str(src))
    seen_images: set = set()
    render_doc = None
    counter = 0

    try:
        with _open(src, password) as pdf:
            total = len(pdf.pages)
            for page_no, page in enumerate(pdf.pages, start=1):
                if cancelled and cancelled():
                    break
                if progress:
                    progress(page_no, total)
                image_no = 0
                needs_render = False
                for obj in _image_objects(_page_resources(page.obj), set()):
                    key_id = obj.objgen
                    if key_id != (0, 0):
                        if key_id in seen_images:
                            continue
                        seen_images.add(key_id)
                    if int(obj.get("/Width", 0)) < MIN_SIDE or int(obj.get("/Height", 0)) < MIN_SIDE:
                        result.skipped_small += 1
                        continue
                    try:
                        pil = PdfImage(obj).as_pil_image()
                    except Exception:
                        needs_render = True
                        continue
                    image_no += 1
                    counter += 1
                    file = out / f"{counter:05d}.png"
                    _saveable(pil).save(file, "PNG")
                    result.images.append(
                        PdfImageItem(f"{src.name} - page {page_no} - image {image_no}.png", str(file))
                    )
                if needs_render:
                    if render_doc is None:
                        with PDFIUM_LOCK:
                            render_doc = pdfium.PdfDocument(str(src), password=password)
                    counter += 1
                    file = out / f"{counter:05d}.png"
                    _render_page(render_doc, page_no, file)
                    result.images.append(PdfImageItem(f"{src.name} - page {page_no} (full page).png", str(file)))
                    result.rendered_pages.append(page_no)
    finally:
        if render_doc is not None:
            with PDFIUM_LOCK:
                render_doc.close()
    return result


def render_pages(
    pdf_path: str,
    out_dir: str,
    password: str | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> PdfExtractResult:
    """Turn every page into an image (for scanned PDFs or PDFs without images)."""
    src = Path(pdf_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = PdfExtractResult(source=str(src))
    try:
        with PDFIUM_LOCK:
            doc = pdfium.PdfDocument(str(src), password=password)
    except pdfium.PdfiumError as exc:
        if "password" in str(exc).lower():
            raise PdfPasswordRequired(str(src)) from exc
        raise
    try:
        total = len(doc)
        for page_no in range(1, total + 1):
            if cancelled and cancelled():
                break
            if progress:
                progress(page_no, total)
            file = out / f"page_{page_no:05d}.png"
            _render_page(doc, page_no, file)
            result.images.append(PdfImageItem(f"{src.name} - page {page_no}.png", str(file)))
            result.rendered_pages.append(page_no)
    finally:
        with PDFIUM_LOCK:
            doc.close()
    return result
