"""OCR helpers: find Tesseract, clean up images, extract text, format output."""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

import pytesseract
from PIL import Image, ImageFilter, ImageOps, ImageStat

LANGUAGES = {
    "English": "eng",
    "Arabic": "ara",
}

SEP_MAJOR = "=" * 70
SEP_MINOR = "-" * 70
OCR_TIMEOUT_SECONDS = 180


# --- Tesseract location --------------------------------------------------
def _bundled_tesseract() -> Path:
    app_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return app_root / "tesseract" / "tesseract.exe"


def find_tesseract() -> str | None:
    """Bundled copy first (packaged app), then PATH, then the default install folder."""
    candidates = [_bundled_tesseract()]
    on_path = shutil.which("tesseract")
    if on_path:
        candidates.append(Path(on_path))
    candidates.append(Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def setup_tesseract() -> str | None:
    path = find_tesseract()
    if path:
        pytesseract.pytesseract.tesseract_cmd = path
        tessdata = Path(path).parent / "tessdata"
        if Path(path) == _bundled_tesseract() and tessdata.is_dir():
            # Use the bundled language files, even if another Tesseract on this
            # computer set TESSDATA_PREFIX to its own folder.
            os.environ["TESSDATA_PREFIX"] = str(tessdata)
    return path


def missing_languages(lang_code: str) -> list[str]:
    installed = set(pytesseract.get_languages(config=""))
    return [code for code in lang_code.split("+") if code not in installed]


# --- Image clean-up ("Auto-enhance") -------------------------------------
def _flatten(img: Image.Image) -> Image.Image:
    """Put transparent images on white and fix phone photo rotation."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        img = Image.alpha_composite(background, rgba)
    return img.convert("RGB")


def _otsu(gray: Image.Image) -> Image.Image:
    """Automatic black/white threshold."""
    hist = gray.histogram()
    total = sum(hist)
    weighted_total = sum(i * h for i, h in enumerate(hist))
    background_weight = background_sum = 0
    best_variance, threshold = -1.0, 127
    for t in range(256):
        background_weight += hist[t]
        if background_weight == 0 or background_weight == total:
            continue
        background_sum += t * hist[t]
        foreground_weight = total - background_weight
        mean_bg = background_sum / background_weight
        mean_fg = (weighted_total - background_sum) / foreground_weight
        variance = background_weight * foreground_weight * (mean_bg - mean_fg) ** 2
        if variance > best_variance:
            best_variance, threshold = variance, t
    return gray.point(lambda v: 255 if v > threshold else 0)


def enhance(img: Image.Image, is_photo: bool = False) -> Image.Image:
    """Clean up a copy of the image so Tesseract reads it better.

    - dark-mode screenshots are inverted to dark-on-light
    - small images are upscaled (the smaller the text, the more it is enlarged)
    - the result is sharpened
    - photos (JPEG) also get noise removal and a black/white threshold
    """
    gray = ImageOps.grayscale(_flatten(img))
    if ImageStat.Stat(gray).median[0] < 128:
        gray = ImageOps.invert(gray)
    if is_photo:
        gray = gray.filter(ImageFilter.MedianFilter(3))
    # Aim for a longest side around 3500-4000px: tiny screenshots get enlarged most.
    longest = max(gray.size)
    factor = 1
    for candidate in (4, 3, 2):
        if longest * candidate <= 4200:
            factor = candidate
            break
    if factor > 1:
        gray = gray.resize((gray.width * factor, gray.height * factor), Image.LANCZOS)
        gray = gray.filter(ImageFilter.UnsharpMask(radius=1.5, percent=150))
    if is_photo:
        gray = _otsu(ImageOps.autocontrast(gray, cutoff=1))
    return gray


# --- OCR -----------------------------------------------------------------
def _tidy(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\f", "").splitlines()]
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def ocr_pil(img: Image.Image, lang_code: str, auto_enhance: bool, is_photo: bool) -> str:
    prepared = enhance(img, is_photo) if auto_enhance else _flatten(img)
    text = pytesseract.image_to_string(
        prepared, lang=lang_code, config="--psm 6", timeout=OCR_TIMEOUT_SECONDS
    )
    return _tidy(text)


def ocr_image(path: str, lang_code: str, auto_enhance: bool = True) -> str:
    with Image.open(path) as img:
        img.load()
        is_photo = (img.format or "").upper() in {"JPEG", "MPO"}
        return ocr_pil(img, lang_code, auto_enhance, is_photo)


def format_block(label: str, text: str) -> str:
    body = text if text else "(no text found)"
    return f"{SEP_MAJOR}\nFILE: {label}\n{SEP_MINOR}\n{body}\n"
