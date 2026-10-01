from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.docx_images import extract_docx_images
from app.core.pdf_images import PdfPasswordRequired, extract_images, render_pages
from app.i18n import tr
from app.ui.worker import Job, start_job, stop_job

THUMB_SIZE = QSize(120, 80)
PATH_ROLE = Qt.UserRole
LABEL_ROLE = Qt.UserRole + 1
MODE_EMBEDDED = "Images inside the file"
MODE_PAGES = "Whole pages as images (PDF only)"


def load_thumbnail(path: str) -> QIcon:
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():
        reader.setScaledSize(size.scaled(THUMB_SIZE, Qt.KeepAspectRatio))
    image = reader.read()
    return QIcon(QPixmap.fromImage(image)) if not image.isNull() else QIcon()


def extract_job(job: Job, path: str, out_dir: str, password, mode: str):
    name = Path(path).name
    suffix = Path(path).suffix.lower()

    def progress(done: int, total: int) -> None:
        job.progress.emit(done, total, tr("reading_file", name=name, done=done, total=total))

    if suffix == ".docx":
        items = extract_docx_images(path, out_dir, progress=progress, cancelled=job.is_cancelled)
        return items, 0, []
    if mode == MODE_PAGES:
        result = render_pages(path, out_dir, password=password, progress=progress, cancelled=job.is_cancelled)
    else:
        result = extract_images(path, out_dir, password=password, progress=progress, cancelled=job.is_cancelled)
    return result.images, result.skipped_small, result.rendered_pages


class ImageResultList(QListWidget):
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setIconSize(THUMB_SIZE)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setAcceptDrops(True)
        self.setUniformItemSizes(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        docs = [p for p in paths if p.lower().endswith((".pdf", ".docx"))]
        if docs:
            self.files_dropped.emit(docs)
        event.acceptProposedAction()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count() == 0:
            painter = QPainter(self.viewport())
            painter.setPen(self.palette().placeholderText().color())
            painter.drawText(
                self.viewport().rect(),
                Qt.AlignCenter | Qt.TextWordWrap,
                tr("img_empty"),
            )


class ImagesTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._temp = tempfile.TemporaryDirectory(prefix="DocToolkitImg_")
        self._counter = 0
        self._job = None
        self._thread = None
        self._queue = []
        self._current = None

        add_btn = QPushButton(tr("img_add"))
        add_btn.clicked.connect(self.choose_files)

        self.result_list = ImageResultList()
        self.result_list.files_dropped.connect(self.add_files)
        self.result_list.itemChanged.connect(self.update_counts)
        self.result_list.model().rowsInserted.connect(self.update_counts)
        self.result_list.model().rowsRemoved.connect(self.update_counts)

        all_btn = QPushButton(tr("select_all"))
        all_btn.clicked.connect(lambda: self.set_all_checked(True))
        none_btn = QPushButton(tr("select_none"))
        none_btn.clicked.connect(lambda: self.set_all_checked(False))
        clear_btn = QPushButton(tr("img_clear"))
        clear_btn.clicked.connect(self.clear_list)

        self.count_label = QLabel()
        self.save_btn = QPushButton(tr("img_save"))
        self.save_btn.clicked.connect(self.save_selected)

        self.progress_label = QLabel()
        self.progress_bar = QProgressBar()
        self.cancel_btn = QPushButton(tr("cancel"))
        self.cancel_btn.clicked.connect(self.cancel_job)

        row_top = QHBoxLayout()
        row_top.addWidget(add_btn)
        row_top.addStretch(1)
        row_check = QHBoxLayout()
        row_check.addWidget(all_btn)
        row_check.addWidget(none_btn)
        row_check.addWidget(clear_btn)
        row_progress = QHBoxLayout()
        row_progress.addWidget(self.progress_bar, 1)
        row_progress.addWidget(self.cancel_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(row_top)
        layout.addWidget(self.result_list, 1)
        layout.addLayout(row_check)
        layout.addWidget(self.count_label)
        layout.addWidget(self.save_btn)
        layout.addWidget(self.progress_label)
        layout.addLayout(row_progress)

        self.set_busy(False)
        self.update_counts()

    def status(self, message: str) -> None:
        window = self.window()
        if isinstance(window, QMainWindow):
            window.statusBar().showMessage(message, 10000)

    def is_busy(self) -> bool:
        return self._job is not None

    def set_busy(self, busy: bool) -> None:
        for widget in (self.progress_label, self.progress_bar, self.cancel_btn):
            widget.setVisible(busy)
        self.update_counts()

    def choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("img_add_dialog"), "", tr("filter_pdf_docx")
        )
        if files:
            self.add_files(files)

    def add_files(self, paths) -> None:
        for raw in paths:
            path = str(Path(raw).resolve())
            self._queue.append((path, None, MODE_EMBEDDED))
        self.run_next()

    def run_next(self) -> None:
        if self.is_busy() or not self._queue:
            return
        path, password, mode = self._current = self._queue.pop(0)
        self._counter += 1
        out_dir = str(Path(self._temp.name) / f"src{self._counter}")
        job = Job(extract_job, path, out_dir, password, mode)
        job.progress.connect(self.on_progress)
        job.finished.connect(self.on_done)
        job.failed.connect(self.on_failed)
        self._job = job
        self._thread = start_job(self, job)
        self.set_busy(True)

    def job_ended(self) -> None:
        self._job = None
        self._thread = None
        self.set_busy(False)
        self.run_next()

    def on_progress(self, done: int, total: int, text: str) -> None:
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)
        self.progress_label.setText(text)

    def on_done(self, payload) -> None:
        images, skipped_small, _rendered = payload
        path, password, mode = self._current
        name = Path(path).name
        for image in images:
            item = QListWidgetItem(load_thumbnail(image.path), image.label)
            item.setData(PATH_ROLE, image.path)
            item.setData(LABEL_ROLE, image.label)
            item.setToolTip(image.label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.result_list.addItem(item)
        note = tr("tiny_skipped", count=skipped_small) if skipped_small else ""
        if images:
            self.status(tr("found_images", count=len(images), name=name, note=note))
        self.job_ended()
        if not images and mode == MODE_EMBEDDED and path.lower().endswith(".pdf"):
            answer = QMessageBox.question(
                self, tr("no_images_title"),
                tr("no_images_pages", name=name),
            )
            if answer == QMessageBox.Yes:
                self._queue.insert(0, (path, password, MODE_PAGES))
                self.run_next()
        elif not images:
            self.status(tr("no_images_in", name=name))

    def on_failed(self, exc) -> None:
        path, _password, mode = self._current
        name = Path(path).name
        self.job_ended()
        if isinstance(exc, PdfPasswordRequired):
            password, ok = QInputDialog.getText(
                self, tr("password_needed"), tr("password_prompt", name=name),
                QLineEdit.Password,
            )
            if ok and password:
                self._queue.insert(0, (path, password, mode))
                self.run_next()
            return
        QMessageBox.warning(self, tr("could_not_read"), tr("could_not_read_msg", name=name, error=exc))

    def set_all_checked(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        for i in range(self.result_list.count()):
            self.result_list.item(i).setCheckState(state)

    def clear_list(self) -> None:
        self.result_list.clear()

    def checked_items(self):
        items = []
        for i in range(self.result_list.count()):
            item = self.result_list.item(i)
            if item.checkState() == Qt.Checked:
                items.append((item.data(LABEL_ROLE), item.data(PATH_ROLE)))
        return items

    def update_counts(self, *_) -> None:
        total = self.result_list.count()
        selected = len(self.checked_items())
        self.count_label.setText(tr("images_selected", selected=selected, total=total))
        self.save_btn.setEnabled(selected > 0 and not self.is_busy())

    def save_selected(self) -> None:
        items = self.checked_items()
        if not items:
            return
        folder = QFileDialog.getExistingDirectory(self, tr("choose_folder"), str(Path.home()))
        if not folder:
            return
        out = Path(folder)
        saved = 0
        errors = []
        for label, src in items:
            target = self._unique_path(out / self._safe_name(label))
            try:
                shutil.copy2(src, target)
                saved += 1
            except OSError as exc:
                errors.append(f"{label}: {exc}")
        if errors:
            QMessageBox.warning(
                self, tr("save_problems_title"),
                tr("save_problems", saved=saved, problems="\n".join(errors[:8])),
            )
        else:
            self.status(tr("saved_to", saved=saved, folder=folder))

    @staticmethod
    def _safe_name(label: str) -> str:
        bad = '<>:"/\\|?*'
        name = "".join("_" if c in bad else c for c in label)
        return name or "image.png"

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        stem, suffix, index = path.stem, path.suffix, 2
        while True:
            candidate = path.with_name(f"{stem} ({index}){suffix}")
            if not candidate.exists():
                return candidate
            index += 1

    def cancel_job(self) -> None:
        self._queue.clear()
        if self._job:
            self._job.cancel()
            self.progress_label.setText(tr("stopping"))

    def shutdown(self) -> bool:
        self._queue.clear()
        stopped = stop_job(self._job, self._thread)
        shutil.rmtree(self._temp.name, ignore_errors=True)
        return stopped
