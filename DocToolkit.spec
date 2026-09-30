# PyInstaller recipe for DocToolkit.exe
#
# Build (from the project folder):
#     venv\Scripts\pyinstaller --noconfirm --clean DocToolkit.spec
#
# Result: dist\DocToolkit\DocToolkit.exe  (keep the whole dist\DocToolkit folder together)
#
# Before building, copy Tesseract into a folder named "tesseract" next to this
# file (see README). An "exiftool" folder is added too if it exists.
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH)
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "app" / "__init__.py").read_text()).group(1)

# --- programs bundled inside the app ----------------------------------------
tesseract = ROOT / "tesseract"
missing = [p for p in ("tesseract.exe", "tessdata/eng.traineddata", "tessdata/ara.traineddata")
           if not (tesseract / p).is_file()]
if missing:
    sys.exit(
        "\nBUILD STOPPED: Tesseract isn't ready to bundle. Missing in the 'tesseract' folder: "
        + ", ".join(missing)
        + "\nCopy it with:  Copy-Item -Recurse \"C:\\Program Files\\Tesseract-OCR\" tesseract\n"
        "(Arabic must be installed in Tesseract first. See README.)\n"
    )

datas = [
    (str(tesseract), "tesseract"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD-PARTY-NOTICES.md"), "."),
]
if (ROOT / "exiftool" / "exiftool.exe").is_file():
    datas.append((str(ROOT / "exiftool"), "exiftool"))
else:
    print("NOTE: no exiftool folder found. Building without the optional ExifTool report.")

# --- file properties shown in Windows (right-click > Properties > Details) --
version_info = None
if sys.platform == "win32":
    from PyInstaller.utils.win32 import versioninfo as vi

    numbers = (tuple(int(n) for n in re.findall(r"\d+", VERSION)) + (0, 0, 0, 0))[:4]
    version_info = vi.VSVersionInfo(
        ffi=vi.FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            vi.StringFileInfo([vi.StringTable("040904B0", [
                vi.StringStruct("CompanyName", "Tariq Alanazi"),
                vi.StringStruct("FileDescription", "DocToolkit"),
                vi.StringStruct("FileVersion", VERSION),
                vi.StringStruct("InternalName", "DocToolkit"),
                vi.StringStruct("LegalCopyright", "Copyright (c) 2026 Tariq Alanazi. MIT License."),
                vi.StringStruct("OriginalFilename", "DocToolkit.exe"),
                vi.StringStruct("ProductName", "DocToolkit"),
                vi.StringStruct("ProductVersion", VERSION),
            ])]),
            vi.VarFileInfo([vi.VarStruct("Translation", [0x0409, 1200])]),
        ],
    )

icon = ROOT / "app" / "icon.ico"  # optional: add an icon file here and it's used automatically

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    # never used by DocToolkit; excluded so they are not packed in by accident
    excludes=["tkinter", "numpy", "pandas", "scipy", "matplotlib", "IPython", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,       # folder build: starts fast and antivirus flags it less than one big exe
    name="DocToolkit",
    console=False,               # a normal window app, no black console window
    upx=False,                   # compressing with UPX often triggers antivirus false alarms
    version=version_info,
    icon=str(icon) if icon.is_file() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="DocToolkit", upx=False)
