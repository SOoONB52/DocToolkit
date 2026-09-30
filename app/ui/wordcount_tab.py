"""Word Count tab: open a PDF or Word file, see its pages, choose pages, count their words."""
from __future__ import annotations

from pathlib import Path

import shutil
import tempfile
import unicodedata

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

from app.core.docx_pages import analyse_docx
from app.core.wordcount import PdfPasswordRequired, analyse_pdf, parse_page_range
from app.i18n import tr
from app.ui.worker import Job, start_job, stop_job

PAGE_ROLE = Qt.UserRole
THUMB_SIZE = QSize(85, 120)
SUPPORTED = (".pdf", ".docx")


def count_job(job: Job, path: str, password, thumb_dir: str):
    name = Path(path).name

    def progress(page: int, total: int) -> None:
        job.progress.emit(page, total, tr("reading_pdf_page", name=name, page=page, total=total))

    if path.lower().endswith(".docx"):
        return analyse_docx(path, thumb_dir, progress=progress, cancelled=job.is_cancelled)
    return analyse_pdf(path, password=password, progress=progress,
                       cancelled=job.is_cancelled, thumb_dir=thumb_dir)


def _is_rtl(text: str) -> bool:
    for ch in text:
        kind = unicodedata.bidirectional(ch)
        if kind in ("R", "AL"):
            return True
        if kind == "L":
            return False
    return False


def page_icon(path: str) -> QIcon:
    """The rendered page with a thin border, so white pages don't vanish into the list."""
    image = QImage(path)
    if image.isNull():
        return QIcon()
    image = image.convertToFormat(QImage.Format_RGB32)
    painter = QPainter(image)
    painter.setPen(QPen(QColor("#9a9a9a"), 2))
    painter.drawRect(1, 1, image.width() - 2, image.height() - 2)
    painter.end()
    return QIcon(QPixmap.fromImage(image))


def preview_icon(text: str) -> QIcon:
    """A small page drawn from the page's text, for Word files paginated without Word."""
    image = QImage(170, 240, QImage.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(QPen(QColor("#9a9a9a"), 2))
    painter.drawRect(1, 1, 168, 238)
    font = QFont()
    font.setPointSizeF(6.5)
    painter.setFont(font)
    painter.setPen(QColor("#303030"))
    snippet = " ".join(text.split())[:600]
    painter.setLayoutDirection(Qt.RightToLeft if _is_rtl(snippet) else Qt.LeftToRight)
    painter.drawText(QRect(10, 10, 150, 220), Qt.TextWordWrap | Qt.AlignTop, snippet)
    painter.end()
    return QIcon(QPixmap.fromImage(image))


class PageList(QListWidget):
    file_dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setIconSize(THUMB_SIZE)
        self.setSpacing(2)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.toLocalFile().lower().endswith(SUPPORTED):
                self.file_dropped.emit(url.toLocalFile())
                break
        event.acceptProposedAction()


class WordCountTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._path: str | None = None
        self._password: str | None = None
        self._pages = []
        self._kind = "pdf"
        self._job = None
        self._thread = None
        self._temp = tempfile.TemporaryDirectory(prefix="DocToolkitWC_")
        self._load_counter = 0
        self._pending: tuple[str, str | None] | None = None

        open_btn = QPushButton(tr("wc_open"))
        open_btn.clicked.connect(self.choose_file)
        self.file_label = QLabel(tr("wc_none"))
        self.file_label.setWordWrap(True)
        top = QHBoxLayout()
        top.addWidget(open_btn)
        top.addWidget(self.file_label, 1)

        self.page_list = PageList()
        self.page_list.file_dropped.connect(self.load_file)
        self.page_list.itemChanged.connect(self.update_totals)

        self.range_edit = QLineEdit()
        self.range_edit.setPlaceholderText(tr("wc_range_ph"))
        self.range_edit.returnPressed.connect(self.apply_range)
        apply_btn = QPushButton(tr("wc_apply"))
        apply_btn.clicked.connect(self.apply_range)
        all_btn = QPushButton(tr("select_all"))
        all_btn.clicked.connect(lambda: self.set_all(True))
        none_btn = QPushButton(tr("select_none"))
        none_btn.clicked.connect(lambda: self.set_all(False))
        select_row = QHBoxLayout()
        select_row.addWidget(QLabel(tr("wc_range")))
        select_row.addWidget(self.range_edit, 1)
        select_row.addWidget(apply_btn)
        select_row.addWidget(all_btn)
        select_row.addWidget(none_btn)

        big = QFont(self.font())
        big.setPointSize(big.pointSize() + 6)
        big.setBold(True)
        self.words_value = QLabel("0")
        self.words_value.setFont(big)
        self.chars_value = QLabel("0")
        self.pages_value = QLabel("0")
        totals = QGroupBox()
        form = QFormLayout(totals)
        # keep each number right next to its label (in both directions)
        form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        form.setFormAlignment(Qt.AlignLeading | Qt.AlignTop)
        form.setLabelAlignment(Qt.AlignLeading | Qt.AlignVCenter)
        form.addRow(tr("wc_total_words") + ":", self.words_value)
        form.addRow(tr("wc_total_chars") + ":", self.chars_value)
        form.addRow(tr("wc_total_pages") + ":", self.pages_value)

        self.scanned_note = QLabel()
        self.scanned_note.setWordWrap(True)
        self.scanned_note.setVisible(False)
        self.approx_note = QLabel(tr("wc_docx_approx"))
        self.approx_note.setWordWrap(True)
        self.approx_note.setVisible(False)

        self.copy_btn = QPushButton(tr("wc_copy"))
        self.copy_btn.clicked.connect(self.copy_summary)

        self.progress_label = QLabel()
        self.progress_bar = QProgressBar()

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(select_row)
        layout.addWidget(self.page_list, 1)
        layout.addWidget(self.scanned_note)
        layout.addWidget(self.approx_note)
        layout.addWidget(totals)
        layout.addWidget(self.copy_btn)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress_bar)
        self.set_busy(False)
        self.update_totals()

    def status(self, message: str) -> None:
        window = self.window()
        if isinstance(window, QMainWindow):
            window.statusBar().showMessage(message, 10000)

    def set_busy(self, busy: bool) -> None:
        self.progress_label.setVisible(busy)
        self.progress_bar.setVisible(busy)

    # --- loading ---
    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("wc_open_dialog"), "", tr("filter_pdf_docx"))
        if path:
            self.load_file(path)

    def load_file(self, path: str, password: str | None = None) -> None:
        if self._job is not None:
            return
        self._pending = (path, password)
        self._load_counter += 1
        thumb_dir = Path(self._temp.name) / f"load{self._load_counter}"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        job = Job(count_job, path, password, str(thumb_dir))
        job.progress.connect(self.on_progress)
        job.finished.connect(self.on_done)
        job.failed.connect(self.on_failed)
        self._job = job
        self._thread = start_job(self, job)
        self.set_busy(True)

    def on_progress(self, done: int, total: int, text: str) -> None:
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)
        self.progress_label.setText(text)

    def _job_ended(self) -> None:
        self._job = None
        self._thread = None
        self.set_busy(False)

    def on_done(self, pages) -> None:
        self._job_ended()
        self._path, self._password = self._pending
        self._kind = "docx" if self._path.lower().endswith(".docx") else "pdf"
        self._pages = pages
        self.page_list.blockSignals(True)
        self.page_list.clear()
        for p in pages:
            if p.has_text:
                text = tr("wc_page_item", page=p.page, words=p.words)
            elif self._kind == "docx":
                text = tr("wc_page_blank", page=p.page)
            else:
                text = tr("wc_page_scanned", page=p.page)
            icon = page_icon(p.thumb) if p.thumb else preview_icon(p.preview_text)
            item = QListWidgetItem(icon, text)
            item.setData(PAGE_ROLE, p.page)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.page_list.addItem(item)
        self.page_list.blockSignals(False)
        self.file_label.setText(tr("wc_file", name=Path(self._path).name, pages=len(pages)))
        self.approx_note.setVisible(any(p.approximate for p in pages))
        self.status(tr("opened", name=Path(self._path).name))
        self.update_totals()

    def on_failed(self, exc) -> None:
        self._job_ended()
        path, _ = self._pending
        name = Path(path).name
        if isinstance(exc, PdfPasswordRequired):
            password, ok = QInputDialog.getText(
                self, tr("password_needed"), tr("password_prompt", name=name), QLineEdit.Password)
            if ok and password:
                self.load_file(path, password)
            return
        QMessageBox.warning(self, tr("could_not_read"), tr("could_not_read_msg", name=name, error=exc))

    # --- selection ---
    def set_all(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        self.page_list.blockSignals(True)
        for i in range(self.page_list.count()):
            self.page_list.item(i).setCheckState(state)
        self.page_list.blockSignals(False)
        self.update_totals()

    def apply_range(self) -> None:
        text = self.range_edit.text().strip()
        if not text or not self._pages:
            return
        try:
            wanted = parse_page_range(text, len(self._pages))
        except ValueError:
            QMessageBox.warning(self, tr("wc_range_bad_title"), tr("wc_range_bad", text=text))
            return
        self.page_list.blockSignals(True)
        for i in range(self.page_list.count()):
            item = self.page_list.item(i)
            item.setCheckState(Qt.Checked if item.data(PAGE_ROLE) in wanted else Qt.Unchecked)
        self.page_list.blockSignals(False)
        self.update_totals()

    def _selected(self):
        chosen = {self.page_list.item(i).data(PAGE_ROLE) for i in range(self.page_list.count())
                  if self.page_list.item(i).checkState() == Qt.Checked}
        return [p for p in self._pages if p.page in chosen]

    def update_totals(self, *_) -> None:
        selected = self._selected()
        words = sum(p.words for p in selected)
        chars = sum(p.chars for p in selected)
        self.words_value.setText(f"{words:,}")
        self.chars_value.setText(f"{chars:,}")
        self.pages_value.setText(tr("wc_pages_value", pages=len(selected), total=len(self._pages)))
        scanned = sum(1 for p in selected if not p.has_text) if self._kind == "pdf" else 0
        self.scanned_note.setVisible(scanned > 0)
        if scanned:
            self.scanned_note.setText("⚠ " + tr("wc_scanned_note", count=scanned))
        self.copy_btn.setEnabled(bool(self._pages))

    def copy_summary(self) -> None:
        selected = self._selected()
        summary = tr(
            "wc_summary",
            name=Path(self._path).name if self._path else "",
            pages=", ".join(str(p.page) for p in selected),
            words=sum(p.words for p in selected),
            chars=sum(p.chars for p in selected),
        )
        QApplication.clipboard().setText(summary)
        self.status(tr("wc_copied"))

    def shutdown(self) -> bool:
        """Stop background work and delete temporary files. False if a job is still running."""
        stopped = stop_job(self._job, self._thread)
        shutil.rmtree(self._temp.name, ignore_errors=True)
        return stopped
