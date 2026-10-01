from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET

from app.core.wordcount import PageCount, count_chars, count_words

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"


def _walk(el, out: list, marker: str) -> None:
    tag = el.tag
    if tag == MC + "Fallback":
        return
    if tag == W + "t":
        out.append(("text", el.text or ""))
        return
    if tag == W + "tab":
        out.append(("text", " "))
        return
    if marker == "rendered" and tag == W + "lastRenderedPageBreak":
        out.append(("page", ""))
    elif marker == "explicit" and tag == W + "br" and el.get(W + "type") == "page":
        out.append(("page", ""))
    for child in el:
        _walk(child, out, marker)
    if tag == W + "p":
        out.append(("text", "\n"))


def analyse_docx_approx(path: str) -> list[PageCount]:
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    body = root.find(W + "body")
    has_rendered = body.find(".//" + W + "lastRenderedPageBreak") is not None
    has_explicit = any(br.get(W + "type") == "page" for br in body.iter(W + "br"))
    marker = "rendered" if has_rendered else "explicit" if has_explicit else "none"

    tokens: list = []
    _walk(body, tokens, marker)
    pages, current = [], []
    for kind, value in tokens:
        if kind == "page":
            pages.append("".join(current))
            current = []
        else:
            current.append(value)
    pages.append("".join(current))
    while len(pages) > 1 and not pages[-1].strip():
        pages.pop()
    while len(pages) > 1 and not pages[0].strip():
        pages.pop(0)

    results = []
    for number, text in enumerate(pages, start=1):
        chars = count_chars(text)
        results.append(PageCount(
            page=number, words=count_words(text), chars=chars, has_text=chars > 0,
            thumb=None, preview_text=text.strip(), approximate=True,
        ))
    return results


def analyse_docx(path: str, thumb_dir: str | None = None, progress=None, cancelled=None) -> list[PageCount]:
    try:
        from app.core.docx_word import analyse_with_word, word_available
        if word_available():
            return analyse_with_word(path, thumb_dir, progress=progress, cancelled=cancelled)
    except Exception:
        pass
    return analyse_docx_approx(path)
