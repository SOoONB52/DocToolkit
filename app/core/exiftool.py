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
    exe = find_exiftool()
    if not exe:
        raise ExifToolMissing()

    fd, argfile = tempfile.mkstemp(suffix=".args", prefix="doctoolkit-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(str(Path(path).resolve()) + "\n")
    command = [exe, "-charset", "filename=utf8", "-json", "-G1", "-a", "-@", argfile]
    extra = {}
    if sys.platform == "win32":
        extra["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
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
    records = json.loads(output, object_pairs_hook=list)
    pairs = records[0] if records else []
    return [(tag, _text(value)) for tag, value in pairs if tag != "SourceFile"]
