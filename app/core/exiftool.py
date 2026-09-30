"""Read a full metadata report with ExifTool (optional).

ExifTool (https://exiftool.org, by Phil Harvey) is free, open-source software.
DocToolkit only uses it to READ. It never writes with it, because ExifTool
edits PDFs by appending an update, which leaves the old values recoverable
inside the file. DocToolkit's own saving rewrites the whole file instead.

Where DocToolkit looks for it, in order:
1. an "exiftool" folder next to main.py (or inside the installed app)
2. anywhere on PATH
3. the usual Windows install folders
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TIMEOUT_SECONDS = 60


class ExifToolMissing(Exception):
    pass


def find_exiftool() -> str | None:
    app_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    candidates = [app_root / "exiftool" / "exiftool.exe", app_root / "exiftool" / "exiftool"]
    on_path = shutil.which("exiftool")
    if on_path:
        candidates.append(Path(on_path))
    if sys.platform == "win32":
        candidates += [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ExifTool" / "ExifTool.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "ExifTool" / "ExifTool.exe",
        ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _text(value) -> str:
    if isinstance(value, list):
        return "; ".join(_text(v) for v in value)
    if isinstance(value, (dict,)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def read_report(path: str) -> list[tuple[str, str]]:
    """[(tag, value), ...] in ExifTool's order, e.g. ('XMP-dc:Creator', 'Atabak Elmi')."""
    exe = find_exiftool()
    if not exe:
        raise ExifToolMissing()

    # The file name goes in a UTF-8 "argument file" so names with Arabic or
    # other non-English letters work on Windows.
    fd, argfile = tempfile.mkstemp(suffix=".args", prefix="doctoolkit-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(str(Path(path).resolve()) + "\n")
    command = [exe, "-charset", "filename=utf8", "-json", "-G1", "-a", "-@", argfile]
    extra = {}
    if sys.platform == "win32":
        extra["creationflags"] = subprocess.CREATE_NO_WINDOW  # no black console window
    try:
        # stdin=DEVNULL: the .exe has no console, and without it Windows says "the handle is invalid"
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=TIMEOUT_SECONDS, **extra)
    finally:
        try:
            os.remove(argfile)
        except OSError:
            pass
    output = result.stdout.decode("utf-8", "replace").strip()
    if not output:
        message = result.stderr.decode("utf-8", "replace").strip() or f"exit code {result.returncode}"
        raise RuntimeError(message)
    # object_pairs_hook keeps repeated tag names (the -a option can list a tag twice)
    records = json.loads(output, object_pairs_hook=list)
    pairs = records[0] if records else []
    return [(tag, _text(value)) for tag, value in pairs if tag != "SourceFile"]
