"""Exact .docx pages using Microsoft Word through COM (Windows only).

Word opens the file read-only and invisibly, is not added to Word's recent
files, and closes without saving, so the original file is never touched.
Word's own ComputeStatistics gives the counts (same as Word's status bar);
a temporary PDF export gives the page pictures.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from app.core.wordcount import PageCount, analyse_pdf

WD_GOTO_PAGE, WD_GOTO_ABSOLUTE = 1, 1
WD_STAT_WORDS, WD_STAT_PAGES, WD_STAT_CHARS_NO_SPACES = 0, 2, 3
WD_EXPORT_PDF = 17
WD_DO_NOT_SAVE = 0


def word_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID"))
        import win32com.client  # noqa: F401  (pywin32)
        return True
    except Exception:
        return False


def analyse_with_word(path: str, thumb_dir: str | None, progress=None, cancelled=None) -> list[PageCount]:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()  # we run in a background thread
    word = doc = None
    fd, tmp_pdf = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        word = win32com.client.DispatchEx("Word.Application")  # private instance
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(
            str(Path(path).resolve()), ConfirmConversions=False, ReadOnly=True,
            AddToRecentFiles=False, Visible=False,
        )
        total = int(doc.ComputeStatistics(WD_STAT_PAGES))
        end_of_doc = doc.Content.End
        starts = [doc.GoTo(WD_GOTO_PAGE, WD_GOTO_ABSOLUTE, n).Start for n in range(1, total + 1)]
        counts = []
        for i, start in enumerate(starts):
            if cancelled and cancelled():
                break
            if progress:
                progress(i + 1, total)
            end = starts[i + 1] if i + 1 < total else end_of_doc
            rng = doc.Range(start, end)
            counts.append((
                int(rng.ComputeStatistics(WD_STAT_WORDS)),
                int(rng.ComputeStatistics(WD_STAT_CHARS_NO_SPACES)),
                rng.Text or "",
            ))
        thumbs: dict[int, str] = {}
        if thumb_dir:
            doc.ExportAsFixedFormat(tmp_pdf, WD_EXPORT_PDF)
            for p in analyse_pdf(tmp_pdf, thumb_dir=thumb_dir):
                if p.thumb:
                    thumbs[p.page] = p.thumb
        return [
            PageCount(page=n, words=w, chars=c, has_text=c > 0, thumb=thumbs.get(n),
                      preview_text=text.strip(), approximate=False)
            for n, (w, c, text) in enumerate(counts, start=1)
        ]
    finally:
        try:
            if doc is not None:
                doc.Close(SaveChanges=WD_DO_NOT_SAVE)
        finally:
            if word is not None:
                word.Quit(SaveChanges=WD_DO_NOT_SAVE)
            pythoncom.CoUninitialize()
            try:
                os.remove(tmp_pdf)
            except OSError:
                pass
