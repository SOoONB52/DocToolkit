from __future__ import annotations

import zipfile
from pathlib import Path

from app.core.pdf_images import PdfImageItem

MEDIA_PREFIX = "word/media/"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".emf", ".wmf"}


def extract_docx_images(docx_path: str, out_dir: str, progress=None, cancelled=None) -> list[PdfImageItem]:
    src = Path(docx_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    items: list[PdfImageItem] = []

    with zipfile.ZipFile(src) as zf:
        media = [n for n in zf.namelist()
                 if n.startswith(MEDIA_PREFIX) and Path(n).suffix.lower() in IMAGE_SUFFIXES]
        media.sort()
        total = len(media)
        for index, name in enumerate(media, start=1):
            if cancelled and cancelled():
                break
            if progress:
                progress(index, total)
            original = Path(name).name
            target = out / f"{src.stem} - {original}"
            with zf.open(name) as source, open(target, "wb") as dest:
                dest.write(source.read())
            items.append(PdfImageItem(f"{src.name} - {original}", str(target)))
    return items
