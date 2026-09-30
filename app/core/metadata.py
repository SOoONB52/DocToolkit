"""Read and write metadata for PDF and Word (.docx) files.

Metadata is shown in sections (PDF, XMP, ExifTool for PDF files; Core,
Application, Custom and ExifTool for Word files). The user edits values in
section windows, and every edit is written together in one save.

Safety rules:
- Only values the user changed are written. Everything else stays as it was.
- Saving writes a temporary file first and then swaps it in, so a failed save
  never damages the original.
- "Save a copy" never replaces an existing file; it picks a free name.
- Password-protected PDFs keep their password, and "fast web view"
  (linearized) PDFs stay linearized.
- DocToolkit never writes its own name or a timestamp of its own into a file.
"""
from __future__ import annotations

import datetime as dt
import html
import os
import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf
from lxml import etree

from app.i18n import tr


class MetadataError(Exception):
    """A problem the user can act on. The message is shown as it is."""


class PdfPasswordRequired(MetadataError):
    pass


# --------------------------------------------------------------- model -------
@dataclass
class Entry:
    key: str                 # unique inside its section, e.g. "Info.Author"
    tag: str                 # readable name, e.g. "Info / Author"
    value: str = ""          # the value as shown to the user
    editable: bool = True
    kind: str = "text"       # text | date | list | int | number | bool
    note: str = ""           # help text, or why the value is read only
    raw: str = ""            # the value exactly as stored, when it differs from `value`


@dataclass
class Section:
    id: str
    title: str
    description: str
    entries: list[Entry] = field(default_factory=list)
    read_only: bool = False
    message: str = ""        # shown above the table, e.g. "This file has no XMP yet"
    message_is_rich: bool = False
    lazy: bool = False       # filled only when first opened (the ExifTool report)
    loaded: bool = True

    def entry(self, key: str) -> Entry | None:
        return next((e for e in self.entries if e.key == key), None)


@dataclass
class FileMetadata:
    path: str
    kind: str                # "pdf" or "docx"
    sections: list[Section]
    password: str | None = None

    def section(self, section_id: str) -> Section | None:
        return next((s for s in self.sections if s.id == section_id), None)


Changes = dict  # {section_id: {entry_key: new text}}


def load(path: str, password: str | None = None) -> FileMetadata:
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return load_pdf(path, password)
    if suffix == ".docx":
        return load_docx(path)
    raise MetadataError(tr("unsupported"))


def save(meta: FileMetadata, changes: Changes, overwrite: bool, sync: bool = True) -> str:
    problems = find_problems(meta, changes)
    if problems:
        raise MetadataError("\n".join(problems))
    if meta.kind == "pdf":
        return save_pdf(meta, changes, overwrite, sync)
    return save_docx(meta, changes, overwrite)


def clear(meta: FileMetadata, overwrite: bool) -> str:
    return clear_pdf(meta, overwrite) if meta.kind == "pdf" else clear_docx(meta, overwrite)


# --------------------------------------------------------------- values ------
def humanize(name: str) -> str:
    """'CreationDate' -> 'Creation Date', 'creator' -> 'Creator'."""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    return spaced[:1].upper() + spaced[1:]


def check_value(entry: Entry, text: str) -> str | None:
    """An error message if `text` can't be stored in this entry, otherwise None."""
    value = text.strip()
    if not value:
        return None  # empty means "remove this value"
    if entry.kind == "date":
        try:
            parse_date(value)
        except ValueError:
            return tr("invalid_date", value=value)
    elif entry.kind == "int":
        if not re.fullmatch(r"[+-]?\d+", value):
            return tr("invalid_number", value=value)
    elif entry.kind == "number":
        try:
            float(value)
        except ValueError:
            return tr("invalid_decimal", value=value)
    elif entry.kind == "bool":
        if value.lower() not in ("true", "false", "1", "0"):
            return tr("invalid_bool")
    return None


def find_problems(meta: FileMetadata, changes: Changes) -> list[str]:
    problems = []
    for section_id, edits in changes.items():
        section = meta.section(section_id)
        for key, text in edits.items():
            entry = section.entry(key) if section else None
            if entry is None or not entry.editable:
                continue
            error = check_value(entry, text)
            if error:
                problems.append(f"{section.title} / {entry.tag}: {error}")
    return problems


def split_list(text: str) -> list[str]:
    return [part.strip() for part in text.split(";") if part.strip()]


# --------------------------------------------------------------- dates -------
_HUMAN_DATE = re.compile(
    r"^(\d{4})[-:/](\d{1,2})[-:/](\d{1,2})"
    r"(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?"
    r"\s*(Z|[+-]\d{2}:?\d{2})?$",
    re.IGNORECASE,
)
_PDF_DATE = re.compile(
    r"^(?:D:)?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?"
    r"\s*(Z(?:00'?00'?)?|[+-]\d{2}'?(?:\d{2}'?)?)?$",
    re.IGNORECASE,
)


def _offset(text: str | None) -> dt.tzinfo | None:
    if not text:
        return None
    t = text.upper().replace("'", "").replace(":", "")
    if t.startswith("Z"):
        return dt.timezone.utc
    sign = -1 if t[0] == "-" else 1
    hours, minutes = int(t[1:3]), int(t[3:5] or 0)
    return dt.timezone(sign * dt.timedelta(hours=hours, minutes=minutes))


def parse_date(text: str) -> dt.datetime:
    """Understands the ways dates are written in documents and by people.

    '2026-07-17 14:05:22 +10:00', '2026-07-17 14:05', '2026-07-17',
    '2026-07-17T14:05:22Z' (XMP / Word), '2026:07:17 14:05:22+10:00' (ExifTool)
    and "D:20260717140522+10'00'" (PDF Info). Without a time zone, the
    computer's own time zone is used. Raises ValueError.
    """
    s = text.strip()
    match = _HUMAN_DATE.match(s) or _PDF_DATE.match(s)
    if not match:
        raise ValueError(text)
    year, month, day, hour, minute, second, zone = match.groups()
    naive = dt.datetime(int(year), int(month or 1), int(day or 1),
                        int(hour or 0), int(minute or 0), int(second or 0))
    tz = _offset(zone)
    if tz is not None:
        return naive.replace(tzinfo=tz)
    try:
        return naive.astimezone()  # the computer's local time zone
    except (OSError, OverflowError, ValueError):
        return naive.replace(tzinfo=dt.timezone.utc)


def _offset_parts(moment: dt.datetime) -> tuple[str, int, int]:
    minutes = int((moment.utcoffset() or dt.timedelta(0)).total_seconds() // 60)
    sign = "-" if minutes < 0 else "+"
    minutes = abs(minutes)
    return sign, minutes // 60, minutes % 60


def format_date(moment: dt.datetime) -> str:
    sign, hours, minutes = _offset_parts(moment)
    return f"{moment:%Y-%m-%d %H:%M:%S} {sign}{hours:02d}:{minutes:02d}"


def to_pdf_date(moment: dt.datetime) -> str:
    sign, hours, minutes = _offset_parts(moment)
    zone = "Z" if (hours, minutes) == (0, 0) else f"{sign}{hours:02d}'{minutes:02d}'"
    return f"D:{moment:%Y%m%d%H%M%S}{zone}"


def to_xmp_date(moment: dt.datetime) -> str:
    sign, hours, minutes = _offset_parts(moment)
    zone = "Z" if (hours, minutes) == (0, 0) else f"{sign}{hours:02d}:{minutes:02d}"
    return f"{moment:%Y-%m-%dT%H:%M:%S}{zone}"


def to_utc_w3c(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_entry(key: str, tag: str, raw: str, local: bool = False) -> Entry:
    """A date value shown as 2026-07-17 14:05:22 +10:00. `local` shows it in this
    computer's time zone (for Word files, which always store dates in UTC)."""
    shown = raw
    if raw:
        try:
            moment = parse_date(raw)
            if local:
                try:
                    moment = moment.astimezone()
                except (OSError, OverflowError, ValueError):
                    pass
            shown = format_date(moment)
        except ValueError:
            pass
    return Entry(key, tag, shown, kind="date", raw=raw if raw != shown else "")


# =============================================================== PDF ========
PDF_INFO_FIELDS = ["/Title", "/Author", "/Subject", "/Keywords", "/Creator",
                   "/Producer", "/CreationDate", "/ModDate"]
PDF_INFO_DATES = {"/CreationDate", "/ModDate"}

# XMP values always listed (even when missing), so they can be added.
XMP_FIELDS = [
    ("dc:title", "text"), ("dc:creator", "list"), ("dc:description", "text"),
    ("dc:subject", "list"), ("pdf:Keywords", "text"), ("pdf:Producer", "text"),
    ("xmp:CreatorTool", "text"), ("xmp:CreateDate", "date"), ("xmp:ModifyDate", "date"),
    ("xmp:MetadataDate", "date"), ("xmpMM:DocumentID", "text"), ("xmpMM:InstanceID", "text"),
]
XMP_SEQ = {"dc:creator", "dc:date"}                     # ordered lists
XMP_BAG = {"dc:subject", "dc:contributor", "dc:publisher", "dc:type", "dc:language", "dc:relation"}
XMP_DATES = {"xmp:CreateDate", "xmp:ModifyDate", "xmp:MetadataDate", "photoshop:DateCreated"}
XMP_TOOLKIT = "x:xmptk"

# Info value <-> XMP value that means the same thing.
SYNC_PAIRS = [
    ("Info.Title", "dc:title"), ("Info.Author", "dc:creator"), ("Info.Subject", "dc:description"),
    ("Info.Keywords", "pdf:Keywords"), ("Info.Creator", "xmp:CreatorTool"),
    ("Info.Producer", "pdf:Producer"), ("Info.CreationDate", "xmp:CreateDate"),
    ("Info.ModDate", "xmp:ModifyDate"),
]

_NS_PREFIX = {uri: prefix for uri, prefix in [
    ("adobe:ns:meta/", "x"), ("http://purl.org/dc/elements/1.1/", "dc"),
    ("http://ns.adobe.com/pdf/1.3/", "pdf"), ("http://ns.adobe.com/xap/1.0/", "xmp"),
    ("http://ns.adobe.com/xap/1.0/mm/", "xmpMM"), ("http://ns.adobe.com/xap/1.0/rights/", "xmpRights"),
    ("http://www.aiim.org/pdfa/ns/id/", "pdfaid"), ("http://www.aiim.org/pdfua/ns/id/", "pdfuaid"),
    ("http://www.npes.org/pdfx/ns/id/", "pdfxid"), ("http://ns.adobe.com/pdfx/1.3/", "pdfx"),
    ("http://ns.adobe.com/photoshop/1.0/", "photoshop"),
    ("http://prismstandard.org/namespaces/basic/2.0/", "prism"),
    ("http://ns.adobe.com/xap/1.0/sType/ResourceEvent#", "stEvt"),
    ("http://ns.adobe.com/xap/1.0/sType/ResourceRef#", "stRef"),
    ("http://ns.adobe.com/tiff/1.0/", "tiff"), ("http://ns.adobe.com/exif/1.0/", "exif"),
]}


class _OrderedBag(set):
    """A set that remembers the order values were typed in (for XMP Bag values)."""

    def __init__(self, items):
        self._order = list(dict.fromkeys(items))
        super().__init__(self._order)

    def __iter__(self):
        return iter(self._order)


def _short_name(clark: str) -> str:
    """'{http://purl.org/dc/elements/1.1/}creator' -> 'dc:creator'."""
    match = re.match(r"^\{(.*)\}(.*)$", clark)
    if not match:
        return clark
    uri, local = match.groups()
    prefix = _NS_PREFIX.get(uri)
    return f"{prefix}:{local}" if prefix else clark


def _local(name: str) -> str:
    return re.split(r"[:}]", name)[-1]


def _open_pdf(path: str, password: str | None, writing: bool = False) -> pikepdf.Pdf:
    try:
        # allow_overwriting_input reads the whole file into memory, so the file
        # itself isn't held open (Windows would refuse to replace it otherwise).
        return pikepdf.open(path, password=password or "", allow_overwriting_input=writing)
    except pikepdf.PasswordError as exc:
        raise PdfPasswordRequired(str(path)) from exc


def load_pdf(path: str, password: str | None = None) -> FileMetadata:
    with _open_pdf(path, password) as pdf:
        sections = [_pdf_section(pdf), _xmp_section(pdf)]
    sections.append(exiftool_placeholder())
    return FileMetadata(str(path), "pdf", sections, password)


def _flag(key: str, tag: str, value: bool, note: str) -> Entry:
    return Entry(key, tag, "true" if value else "false", editable=False, note=note)


def _version_key(version: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", version)) or (0,)


def _pdf_section(pdf: pikepdf.Pdf) -> Section:
    root = pdf.Root
    acro = root.get("/AcroForm")
    fields = acro.get("/Fields") if acro is not None else None
    sig_flags = int(acro.get("/SigFlags", 0)) if acro is not None else 0
    structure = tr("note_structure")

    entries = [
        _flag("Document.Encrypted", "Document / Encrypted", pdf.is_encrypted, tr("note_encrypted")),
        _flag("Document.MetadataStream", "Document / Metadata Stream", "/Metadata" in root,
              tr("note_metadata_stream")),
        _flag("Info.IsAcroFormPresent", "Info / Is Acro Form Present",
              fields is not None and len(fields) > 0, structure),
        _flag("Info.IsCollectionPresent", "Info / Is Collection Present", "/Collection" in root, structure),
        _flag("Info.IsLinearized", "Info / Is Linearized", pdf.is_linearized, structure),
        _flag("Info.IsSignaturesPresent", "Info / Is Signatures Present", bool(sig_flags & 1), structure),
        _flag("Info.IsXFAPresent", "Info / Is XFAPresent", acro is not None and "/XFA" in acro, structure),
    ]
    ids = pdf.trailer.get("/ID")
    fingerprints = ", ".join(bytes(part).hex() for part in ids) if ids is not None else ""
    entries.append(Entry("Fingerprints", "Fingerprints", fingerprints, editable=False,
                         note=tr("note_fingerprints")))
    lang = root.get("/Lang")
    entries.append(Entry("Info.Language", "Info / Language", str(lang) if lang is not None else "",
                         note=tr("note_language")))
    header = pdf.pdf_version
    catalog_version = str(root.get("/Version", "")).lstrip("/")
    effective = max([header, catalog_version], key=_version_key) if catalog_version else header
    entries += [
        Entry("Info.PDFFormatVersion", "Info / PDFFormat Version", header, editable=False, note=structure),
        Entry("PageCount", "Page Count", str(len(pdf.pages)), editable=False, note=structure),
        Entry("PDFVersion", "PDFVersion", effective, editable=False, note=structure),
    ]

    info = pdf.trailer.get("/Info")  # read it without creating one
    present = [str(k) for k in info.keys()] if info is not None else []
    for name in dict.fromkeys(PDF_INFO_FIELDS + present):
        key, tag = f"Info.{name[1:]}", f"Info / {humanize(name[1:])}"
        value = info.get(name) if info is not None else None
        if name in PDF_INFO_DATES:
            entries.append(_date_entry(key, tag, str(value) if value is not None else ""))
        elif value is None or isinstance(value, pikepdf.String):
            entries.append(Entry(key, tag, str(value) if value is not None else ""))
        else:
            entries.append(Entry(key, tag, str(value), editable=False, note=tr("note_other_type")))

    entries.sort(key=lambda e: e.tag.lower())
    return Section("pdf", tr("sec_pdf"), tr("sec_pdf_desc"), entries)


def _xmp_raw(pdf: pikepdf.Pdf) -> bytes | None:
    stream = pdf.Root.get("/Metadata")
    if stream is None:
        return None
    try:
        return bytes(stream.read_bytes())
    except Exception:
        return None


def _xmp_section(pdf: pikepdf.Pdf) -> Section:
    section = Section("xmp", tr("sec_xmp"), tr("sec_xmp_desc"))
    raw = _xmp_raw(pdf)
    values: dict[str, object] = {}
    if raw is None:
        section.message = tr("msg_no_xmp")
    else:
        try:
            meta = pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False)
            for clark in meta:
                name = _short_name(str(clark))
                try:
                    values[name] = meta[clark]
                except Exception:
                    values[name] = None
        except Exception:
            section.read_only = True
            section.message = tr("msg_bad_xmp")

    toolkit = re.search(rb'x:xmptk="([^"]*)"', raw or b"")
    toolkit_text = html.unescape(toolkit.group(1).decode("utf-8", "replace")) if toolkit else ""
    section.entries.append(Entry(XMP_TOOLKIT, "XMP / Toolkit", toolkit_text,
                                 editable=not section.read_only))

    kinds = dict(XMP_FIELDS)
    for name in dict.fromkeys([k for k, _ in XMP_FIELDS] + list(values)):
        tag = f"XMP / {humanize(_local(name))}"
        value = values.get(name)
        kind = kinds.get(name) or ("date" if name in XMP_DATES else "text")
        editable, note = not section.read_only, ""
        if isinstance(value, (list, set, tuple)):
            shown = "; ".join(str(v) for v in value)
            if all(isinstance(v, str) for v in value) and name in XMP_SEQ | XMP_BAG:
                kind = "list"
            else:
                editable, note = False, tr("note_complex")
        elif value is None:
            shown = ""
            if name in values:  # present, but not something we can show as text
                editable, note = False, tr("note_complex")
        elif isinstance(value, str):
            shown = value
        else:
            editable, note, shown = False, tr("note_complex"), str(value)
        if kind == "date" and editable:
            entry = _date_entry(name, tag, shown)
        else:
            entry = Entry(name, tag, shown, kind=kind if editable else "text")
        entry.editable, entry.note = editable, note
        section.entries.append(entry)
    section.entries.sort(key=lambda e: e.tag.lower())
    return section


def _set_info(pdf: pikepdf.Pdf, key: str, text: str) -> None:
    value = text.strip()
    if key == "Info.Language":  # stored in the document catalog, not in Info
        if value:
            pdf.Root.Lang = pikepdf.String(value)
        elif "/Lang" in pdf.Root:
            del pdf.Root.Lang
        return
    name = "/" + key.split(".", 1)[1]
    if not value:
        info = pdf.trailer.get("/Info")
        if info is not None and name in info:
            del info[name]
        return
    if name in PDF_INFO_DATES:
        value = to_pdf_date(parse_date(value))
    pdf.docinfo[name] = pikepdf.String(value)


def _set_xmp_toolkit(raw: bytes, toolkit: str | None, created: bool) -> bytes:
    """Change the XMP toolkit name (a software fingerprint)."""
    if toolkit is None and not created:
        return raw
    if toolkit is None:
        toolkit = ""  # pikepdf writes its own name into a brand-new XMP packet; remove it
    raw = re.sub(rb'\s+x:xmptk="[^"]*"', b"", raw)
    if toolkit:
        attr = ' x:xmptk="{}"'.format(html.escape(toolkit, quote=True)).encode("utf-8")
        raw = re.sub(rb"(<x:xmpmeta\b)", lambda m: m.group(1) + attr, raw, count=1)
    return raw


def _apply_xmp(pdf: pikepdf.Pdf, edits: dict[str, str], section: Section | None) -> None:
    created = "/Metadata" not in pdf.Root
    toolkit = edits.pop(XMP_TOOLKIT, None)
    kinds = {e.key: e.kind for e in section.entries} if section else {}
    with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as meta:
        for key, text in edits.items():
            value = text.strip()
            if not value:
                if key in meta:
                    del meta[key]
                continue
            kind = kinds.get(key) or ("date" if key in XMP_DATES else
                                      "list" if key in XMP_SEQ | XMP_BAG else "text")
            if kind == "date":
                meta[key] = to_xmp_date(parse_date(value))
            elif kind == "list":
                items = split_list(value)
                meta[key] = _OrderedBag(items) if key in XMP_BAG else items
            else:
                meta[key] = value
    raw = _xmp_raw(pdf)
    if raw is not None:
        fixed = _set_xmp_toolkit(raw, toolkit, created)
        if fixed != raw:
            pdf.Root.Metadata.write(fixed)


def _sync(info_edits: dict, xmp_edits: dict, has_xmp: bool) -> None:
    """Copy each edit to its twin in the other section, unless the user edited both."""
    for info_key, xmp_key in SYNC_PAIRS:
        if info_key in info_edits and xmp_key not in xmp_edits:
            if has_xmp:  # never create an XMP section just to mirror an Info edit
                xmp_edits[xmp_key] = info_edits[info_key]
        elif xmp_key in xmp_edits and info_key not in info_edits:
            text = xmp_edits[xmp_key]
            info_edits[info_key] = "; ".join(split_list(text)) if xmp_key in XMP_SEQ | XMP_BAG else text


def save_pdf(meta: FileMetadata, changes: Changes, overwrite: bool, sync: bool = True) -> str:
    pdf_section, xmp_section = meta.section("pdf"), meta.section("xmp")
    info_edits = {k: v for k, v in changes.get("pdf", {}).items()
                  if (e := pdf_section.entry(k)) is not None and e.editable}
    xmp_edits = {} if xmp_section.read_only else {
        k: v for k, v in changes.get("xmp", {}).items()
        if (e := xmp_section.entry(k)) is not None and e.editable}
    with _open_pdf(meta.path, meta.password, writing=True) as pdf:
        if sync and not xmp_section.read_only:
            _sync(info_edits, xmp_edits, has_xmp="/Metadata" in pdf.Root)
        for key, text in info_edits.items():
            _set_info(pdf, key, text)
        if xmp_edits:
            _apply_xmp(pdf, xmp_edits, xmp_section)
        return _save_pdf(pdf, Path(meta.path), overwrite)


def clear_pdf(meta: FileMetadata, overwrite: bool) -> str:
    """Remove the Info dictionary values and the XMP metadata (privacy).

    PDF/A and PDF/UA files must keep their identification in XMP, so only that
    part is kept for them.
    """
    with _open_pdf(meta.path, meta.password, writing=True) as pdf:
        info = pdf.trailer.get("/Info")
        if info is not None:
            for key in list(info.keys()):
                del info[key]
        if "/Metadata" in pdf.Root:
            keep = False
            try:
                with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as xmp:
                    for key in list(xmp):
                        if _short_name(str(key)).startswith(("pdfaid:", "pdfuaid:")):
                            keep = True
                        else:
                            del xmp[key]
            except Exception:
                keep = False
            if keep:
                pdf.Root.Metadata.write(_set_xmp_toolkit(_xmp_raw(pdf), "", created=False))
            else:
                del pdf.Root.Metadata
        return _save_pdf(pdf, Path(meta.path), overwrite)


def _save_pdf(pdf: pikepdf.Pdf, src: Path, overwrite: bool) -> str:
    target = src if overwrite else copy_path(src)
    options = {"linearize": pdf.is_linearized}
    if pdf.is_encrypted:
        options["encryption"] = True  # keep the same password and permissions
    fd, tmp = tempfile.mkstemp(suffix=".pdf", prefix=".doctoolkit-", dir=str(target.parent))
    os.close(fd)
    try:
        pdf.save(tmp, **options)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return str(target)


# =============================================================== DOCX =======
CORE = "docProps/core.xml"
APP = "docProps/app.xml"
CUSTOM = "docProps/custom.xml"

NS = {
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
    "op": "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties",
}

CORE_FIELDS = [
    ("dc:title", "Title", "text"), ("dc:subject", "Subject", "text"),
    ("dc:creator", "Author", "text"), ("cp:keywords", "Keywords", "text"),
    ("dc:description", "Comments", "text"), ("cp:lastModifiedBy", "Last Modified By", "text"),
    ("cp:revision", "Revision", "int"), ("cp:category", "Category", "text"),
    ("cp:contentStatus", "Content Status", "text"), ("dc:language", "Language", "text"),
    ("dc:identifier", "Identifier", "text"), ("cp:version", "Version", "text"),
    ("dcterms:created", "Created", "date"), ("dcterms:modified", "Modified", "date"),
    ("cp:lastPrinted", "Last Printed", "date"),
]
APP_EDITABLE = [("Application", "text"), ("AppVersion", "text"), ("Company", "text"),
                ("Manager", "text"), ("Template", "text"), ("TotalTime", "int"),
                ("HyperlinkBase", "text")]
APP_CLEAR = ["Application", "AppVersion", "Company", "Manager", "Template", "TotalTime",
             "HyperlinkBase", "HeadingPairs", "TitlesOfParts"]
CUSTOM_KINDS = {"lpwstr": "text", "lpstr": "text", "bstr": "text",
                "i1": "int", "i2": "int", "i4": "int", "i8": "int", "int": "int",
                "ui1": "int", "ui2": "int", "ui4": "int", "ui8": "int", "uint": "int",
                "r4": "number", "r8": "number", "decimal": "number",
                "bool": "bool", "filetime": "date", "date": "date"}

# resolve_entities=False and no_network=True: never let a file make the parser
# read other files or go online.
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


def _q(name: str) -> str:
    prefix, local = name.split(":")
    return f"{{{NS[prefix]}}}{local}"


def _ep(name: str) -> str:
    return f"{{{NS['ep']}}}{name}"


def _read_zip(path: str) -> tuple[list[zipfile.ZipInfo], dict[str, bytes]]:
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        return infos, {info.filename: zf.read(info) for info in infos}


def load_docx(path: str) -> FileMetadata:
    _infos, parts = _read_zip(path)
    if "word/document.xml" not in parts:
        raise MetadataError(tr("err_bad_docx"))
    sections = [_core_section(parts.get(CORE)), _app_section(parts.get(APP)),
                _custom_section(parts.get(CUSTOM)), exiftool_placeholder()]
    return FileMetadata(str(path), "docx", sections)


def _core_section(xml: bytes | None) -> Section:
    section = Section("core", tr("sec_core"), tr("sec_core_desc"))
    root = etree.fromstring(xml, _PARSER) if xml else None
    if root is None:
        section.read_only, section.message = True, tr("msg_no_part", part=CORE)
    for name, label, kind in CORE_FIELDS:
        el = root.find(_q(name)) if root is not None else None
        text = (el.text or "") if el is not None else ""
        tag = f"Core / {label}"
        entry = _date_entry(name, tag, text, local=True) if kind == "date" else Entry(name, tag, text, kind=kind)
        entry.editable = not section.read_only
        section.entries.append(entry)
    return section


def _app_section(xml: bytes | None) -> Section:
    section = Section("app", tr("sec_app"), tr("sec_app_desc"))
    root = etree.fromstring(xml, _PARSER) if xml else None
    if root is None:
        section.read_only, section.message = True, tr("msg_no_part", part=APP)
    kinds = dict(APP_EDITABLE)
    present = [etree.QName(el).localname for el in root if isinstance(el.tag, str)] if root is not None else []
    for name in dict.fromkeys([n for n, _ in APP_EDITABLE] + present):
        el = root.find(_ep(name)) if root is not None else None
        tag = f"App / {humanize(name)}"
        if el is not None and len(el):  # lists such as TitlesOfParts
            values = [t.text or "" for t in el.iter() if isinstance(t.tag, str)
                      and etree.QName(t).localname in ("lpstr", "lpwstr")]
            section.entries.append(Entry(name, tag, "; ".join(values), editable=False,
                                         note=tr("note_complex")))
            continue
        text = (el.text or "") if el is not None else ""
        if name in kinds:
            section.entries.append(Entry(name, tag, text, kind=kinds[name], editable=not section.read_only))
        else:
            section.entries.append(Entry(name, tag, text, editable=False, note=tr("note_statistic")))
    return section


def _custom_section(xml: bytes | None) -> Section:
    section = Section("custom", tr("sec_custom"), tr("sec_custom_desc"))
    root = etree.fromstring(xml, _PARSER) if xml else None
    if root is None:
        section.read_only, section.message = True, tr("msg_no_custom")
        return section
    for prop in root.findall(f"{{{NS['op']}}}property"):
        name = prop.get("name", "")
        child = prop[0] if len(prop) else None
        kind = CUSTOM_KINDS.get(etree.QName(child).localname) if child is not None else None
        key, tag = f"custom:{name}", f"Custom / {name}"
        text = (child.text or "") if child is not None else ""
        if kind is None or len(child):
            section.entries.append(Entry(key, tag, text, editable=False, note=tr("note_other_type")))
        elif kind == "date":
            section.entries.append(_date_entry(key, tag, text, local=True))
        else:
            section.entries.append(Entry(key, tag, text, kind=kind))
    if not section.entries:
        section.message = tr("msg_no_custom")
    return section


def _xml_bytes(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _edit_core(xml: bytes, edits: dict[str, str]) -> bytes:
    root = etree.fromstring(xml, _PARSER)
    kinds = {name: kind for name, _l, kind in CORE_FIELDS}
    for name, text in edits.items():
        value = text.strip()
        el = root.find(_q(name))
        if not value:  # an empty date would be invalid, so remove the value entirely
            if el is not None:
                root.remove(el)
            continue
        if el is None:
            el = etree.SubElement(root, _q(name))
        if kinds.get(name) == "date":
            value = to_utc_w3c(parse_date(value))
            if name.startswith("dcterms:"):
                el.set(_q("xsi:type"), "dcterms:W3CDTF")
        el.text = value
    return _xml_bytes(root)


def _edit_app(xml: bytes, edits: dict[str, str]) -> bytes:
    root = etree.fromstring(xml, _PARSER)
    for name, text in edits.items():
        value = text.strip()
        el = root.find(_ep(name))
        if not value:
            if el is not None:
                root.remove(el)
            continue
        if el is None:
            el = etree.SubElement(root, _ep(name))
        el.text = value
    return _xml_bytes(root)


def _edit_custom(xml: bytes, edits: dict[str, str]) -> bytes:
    root = etree.fromstring(xml, _PARSER)
    for prop in list(root.findall(f"{{{NS['op']}}}property")):
        key = f"custom:{prop.get('name', '')}"
        if key not in edits or not len(prop):
            continue
        value = edits[key].strip()
        if not value:
            root.remove(prop)
            continue
        child = prop[0]
        kind = CUSTOM_KINDS.get(etree.QName(child).localname)
        if kind == "date":
            value = to_utc_w3c(parse_date(value))
        elif kind == "bool":
            value = "true" if value.lower() in ("true", "1") else "false"
        child.text = value
    return _xml_bytes(root)


def save_docx(meta: FileMetadata, changes: Changes, overwrite: bool) -> str:
    infos, parts = _read_zip(meta.path)
    editors = [("core", CORE, _edit_core), ("app", APP, _edit_app), ("custom", CUSTOM, _edit_custom)]
    for section_id, part, editor in editors:
        section = meta.section(section_id)
        if section is None or section.read_only or part not in parts:
            continue
        edits = {k: v for k, v in changes.get(section_id, {}).items()
                 if (e := section.entry(k)) is not None and e.editable}
        if edits:
            parts[part] = editor(parts[part], edits)
    return _write_docx(Path(meta.path), infos, parts, overwrite)


def clear_docx(meta: FileMetadata, overwrite: bool) -> str:
    """Remove the document properties, company, template, editing time and
    custom properties. Word's statistics (pages, words) are kept."""
    infos, parts = _read_zip(meta.path)
    if CORE in parts:
        root = etree.fromstring(parts[CORE], _PARSER)
        for el in list(root):
            root.remove(el)
        parts[CORE] = _xml_bytes(root)
    if APP in parts:
        root = etree.fromstring(parts[APP], _PARSER)
        for name in APP_CLEAR:
            for el in root.findall(_ep(name)):
                root.remove(el)
        parts[APP] = _xml_bytes(root)
    if CUSTOM in parts:
        root = etree.fromstring(parts[CUSTOM], _PARSER)
        for el in list(root):
            root.remove(el)
        parts[CUSTOM] = _xml_bytes(root)
    return _write_docx(Path(meta.path), infos, parts, overwrite)


def _write_docx(src: Path, infos: list[zipfile.ZipInfo], parts: dict[str, bytes], overwrite: bool) -> str:
    target = src if overwrite else copy_path(src)
    fd, tmp = tempfile.mkstemp(suffix=".docx", prefix=".doctoolkit-", dir=str(target.parent))
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for info in infos:  # same order and same entry details as the original
                zf.writestr(info, parts[info.filename])
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return str(target)


# =============================================================== ExifTool ===
def exiftool_placeholder() -> Section:
    return Section("exiftool", tr("sec_exiftool"), tr("sec_exiftool_desc"),
                   read_only=True, lazy=True, loaded=False)


def fill_exiftool(section: Section, path: str) -> None:
    """Run ExifTool (if it's installed) and put its report into the section."""
    from app.core import exiftool
    section.loaded = True
    try:
        report = exiftool.read_report(path)
    except exiftool.ExifToolMissing:
        section.entries, section.message, section.message_is_rich = [], tr("exif_missing"), True
        return
    except Exception as exc:
        section.entries = []
        section.message, section.message_is_rich = tr("exif_failed", error=html.escape(str(exc))), True
        return
    section.message, section.message_is_rich = tr("exif_note"), False
    section.entries = [Entry(f"ExifTool.{tag}", tag, value, editable=False) for tag, value in report]


# =============================================================== shared =====
def copy_path(src: Path) -> Path:
    """'report.pdf' -> 'report-modified.pdf', or 'report-modified (2).pdf' if that
    exists. Saving a copy of a copy doesn't pile up '-modified-modified'."""
    stem = re.sub(r"-modified(?: \(\d+\))?$", "", src.stem)
    candidate = src.with_name(f"{stem}-modified{src.suffix}")
    number = 2
    while candidate.exists():
        candidate = src.with_name(f"{stem}-modified ({number}){src.suffix}")
        number += 1
    return candidate


def document_dates(meta: FileMetadata) -> tuple[dt.datetime | None, dt.datetime | None]:
    """The document's own created / modified dates (for the Windows file dates option)."""
    if meta.kind == "pdf":
        sources = [("pdf", "Info.CreationDate", "Info.ModDate"), ("xmp", "xmp:CreateDate", "xmp:ModifyDate")]
    else:
        sources = [("core", "dcterms:created", "dcterms:modified")]
    found: list[dt.datetime | None] = [None, None]
    for section_id, *keys in sources:
        section = meta.section(section_id)
        for index, key in enumerate(keys):
            entry = section.entry(key) if section else None
            if found[index] is None and entry is not None and entry.value:
                try:
                    found[index] = parse_date(entry.value)
                except ValueError:
                    pass
    return found[0], found[1]


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, MetadataError):
        return str(exc)
    if isinstance(exc, PermissionError):
        return tr("err_details", message=tr("err_locked"), error=exc)
    if isinstance(exc, (zipfile.BadZipFile, etree.XMLSyntaxError, KeyError)):
        return tr("err_details", message=tr("err_bad_docx"), error=exc)
    if isinstance(exc, pikepdf.PdfError):
        return tr("err_details", message=tr("err_bad_pdf"), error=exc)
    return str(exc) or exc.__class__.__name__


def set_file_times(path: str, created: dt.datetime | None = None,
                   modified: dt.datetime | None = None) -> bool:
    """Set the Windows file dates shown in File Explorer.

    Modified (and last accessed) works everywhere. Created can only be set on
    Windows. Returns True if the created date was applied.
    """
    if modified is not None:
        stamp = modified.timestamp()
        os.utime(path, (stamp, stamp))
    if created is None or sys.platform != "win32":
        return False

    import ctypes
    from ctypes import wintypes

    def filetime(moment: dt.datetime) -> wintypes.FILETIME:
        # 100-nanosecond intervals since 1601-01-01 (UTC)
        value = int(moment.timestamp() * 10_000_000) + 116_444_736_000_000_000
        return wintypes.FILETIME(value & 0xFFFFFFFF, value >> 32)

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.SetFileTime.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
                                     ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    FILE_WRITE_ATTRIBUTES, SHARE_ALL, OPEN_EXISTING = 0x100, 0x7, 3
    handle = kernel32.CreateFileW(path, FILE_WRITE_ATTRIBUTES, SHARE_ALL, None, OPEN_EXISTING, 0, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        c = filetime(created)
        m = filetime(modified) if modified is not None else None
        ok = kernel32.SetFileTime(handle, ctypes.byref(c), None, ctypes.byref(m) if m else None)
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)
    return True
