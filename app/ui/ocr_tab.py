from __future__ import annotations

import re
import shutil
import tempfile
import unicodedata
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImageReader, QPainter, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
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
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core import ocr
from app.core.pdf_images import PdfPasswordRequired, extract_images, render_pages
from app.i18n import tr
from app.ui.crop_dialog import CropDialog
from app.ui.worker import Job, start_job, stop_job

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}
PDF_EXTENSION = ".pdf"
THUMB_SIZE = QSize(120, 80)
PATH_ROLE = Qt.UserRole
LABEL_ROLE = Qt.UserRole + 1
CROP_ROLE = Qt.UserRole + 2


def natural_key(path: Path):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(path))]


def load_thumbnail(path: str) -> QIcon:
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():
        reader.setScaledSize(size.scaled(THUMB_SIZE, Qt.KeepAspectRatio))
    image = reader.read()
    return QIcon(QPixmap.fromImage(image)) if not image.isNull() else QIcon()


def starts_right_to_left(text: str) -> bool:
    for ch in text:
        direction = unicodedata.bidirectional(ch)
        if direction in ("R", "AL"):
            return True
        if direction == "L":
            return False
    return False


class ImageListWidget(QListWidget):
    pdfs_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setIconSize(THUMB_SIZE)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DropOnly)
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
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        pdfs = [p for p in paths if p.lower().endswith(PDF_EXTENSION)]
        self.add_image_paths([p for p in paths if p not in pdfs])
        if pdfs:
            self.pdfs_dropped.emit(pdfs)
        event.acceptProposedAction()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selectedItems():
            for item in self.selectedItems():
                self.takeItem(self.row(item))
            event.accept()
            return
        super().keyPressEvent(event)

    def existing_paths(self) -> set:
        return {self.item(i).data(PATH_ROLE) for i in range(self.count())}

    def add_entry(self, label: str, path: str) -> bool:
        if path in self.existing_paths():
            return False
        item = QListWidgetItem(load_thumbnail(path), label)
        item.setData(PATH_ROLE, path)
        item.setData(LABEL_ROLE, label)
        item.setToolTip(label)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        self.addItem(item)
        return True

    def add_image_paths(self, paths) -> int:
        added = 0
        for raw in paths:
            p = Path(raw)
            candidates = sorted(p.rglob("*"), key=natural_key) if p.is_dir() else [p]
            for f in candidates:
                if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
                    added += self.add_entry(f.name, str(f.resolve()))
        return added

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count() == 0:
            painter = QPainter(self.viewport())
            painter.setPen(self.palette().placeholderText().color())
            painter.drawText(
                self.viewport().rect(),
                Qt.AlignCenter | Qt.TextWordWrap,
                tr("ocr_empty"),
            )


def pdf_job(job: Job, pdf_path: str, out_dir: str, password: str | None, mode: str):
    name = Path(pdf_path).name
    action = extract_images if mode == "images" else render_pages

    def progress(page: int, total: int) -> None:
        job.progress.emit(page, total, tr("reading_pdf_page", name=name, page=page, total=total))

    result = action(pdf_path, out_dir, password=password, progress=progress, cancelled=job.is_cancelled)
    return result, job.is_cancelled()


def ocr_job(job: Job, items, lang_code: str, auto_enhance: bool):
    done = 0
    for index, (label, path, cropped) in enumerate(items):
        if job.is_cancelled():
            break
        job.progress.emit(index, len(items), tr("reading_image", index=index + 1, total=len(items), name=label))
        try:
            text = ocr.ocr_image(path, lang_code, auto_enhance)
        except Exception as exc:
            text = f"[Could not read this image: {exc}]"
        job.item_done.emit((label, text, cropped))
        done += 1
    return done, len(items)


class OcrTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._temp = tempfile.TemporaryDirectory(prefix="DocToolkit_")
        self._pdf_counter = 0
        self._crop_counter = 0
        self._job: Job | None = None
        self._thread = None
        self._pdf_queue: list[tuple[str, str | None, str]] = []
        self._current_pdf: tuple[str, str | None, str] | None = None
        self._added_pdfs: set[str] = set()

        self.image_list = ImageListWidget()
        self.image_list.pdfs_dropped.connect(self.add_pdfs)
        self.image_list.itemChanged.connect(self.update_counts)
        self.image_list.model().rowsInserted.connect(self.update_counts)
        self.image_list.model().rowsRemoved.connect(self.update_counts)

        add_images_btn = QPushButton(tr("ocr_add_images"))
        add_images_btn.clicked.connect(self.choose_images)
        add_pdf_btn = QPushButton(tr("ocr_add_pdf"))
        add_pdf_btn.clicked.connect(self.choose_pdfs)
        remove_btn = QPushButton(tr("ocr_remove"))
        remove_btn.clicked.connect(self.remove_selected)
        self.crop_btn = QPushButton(tr("ocr_crop"))
        self.crop_btn.setToolTip(tr("ocr_crop_tip"))
        self.crop_btn.clicked.connect(self.crop_selected)
        self.uncrop_btn = QPushButton(tr("ocr_uncrop"))
        self.uncrop_btn.setToolTip(tr("ocr_uncrop_tip"))
        self.uncrop_btn.clicked.connect(self.uncrop_selected)
        all_btn = QPushButton(tr("select_all"))
        all_btn.clicked.connect(self.check_all)
        none_btn = QPushButton(tr("select_none"))
        none_btn.clicked.connect(self.check_none)

        self.language = QComboBox()
        self.language.addItem(tr("lang_english"), "eng")
        self.language.addItem(tr("lang_arabic"), "ara")
        self.lang_hint = QLabel(tr("ocr_lang_hint"))
        self.lang_hint.setWordWrap(True)
        self.lang_hint.setStyleSheet("color: palette(placeholder-text);")
        self.auto_enhance = QCheckBox(tr("ocr_enhance"))
        self.auto_enhance.setChecked(True)
        self.auto_enhance.setToolTip(tr("ocr_enhance_tip"))

        self.count_label = QLabel()
        self.extract_btn = QPushButton(tr("ocr_extract"))
        self.extract_btn.clicked.connect(self.extract_selected)

        self.progress_label = QLabel()
        self.progress_bar = QProgressBar()
        self.cancel_btn = QPushButton(tr("cancel"))
        self.cancel_btn.clicked.connect(self.cancel_job)

        row_add = QHBoxLayout()
        row_add.addWidget(add_images_btn)
        row_add.addWidget(add_pdf_btn)
        row_add.addWidget(self.crop_btn)
        row_add.addWidget(self.uncrop_btn)
        row_add.addWidget(remove_btn)
        row_check = QHBoxLayout()
        row_check.addWidget(all_btn)
        row_check.addWidget(none_btn)
        row_options = QHBoxLayout()
        row_options.addWidget(QLabel(tr("ocr_lang_label")))
        row_options.addWidget(self.language, 1)
        row_options.addWidget(self.auto_enhance)
        row_progress = QHBoxLayout()
        row_progress.addWidget(self.progress_bar, 1)
        row_progress.addWidget(self.cancel_btn)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(row_add)
        left_layout.addWidget(self.image_list, 1)
        left_layout.addLayout(row_check)
        left_layout.addLayout(row_options)
        left_layout.addWidget(self.lang_hint)
        left_layout.addWidget(self.count_label)
        left_layout.addWidget(self.extract_btn)
        left_layout.addWidget(self.progress_label)
        left_layout.addLayout(row_progress)

        self.output = QTextEdit()
        self.output.setAcceptRichText(False)
        self.output.setPlaceholderText(tr("ocr_placeholder"))
        self.output.textChanged.connect(self.update_output_buttons)
        self.copy_btn = QPushButton(tr("ocr_copy"))
        self.copy_btn.clicked.connect(self.copy_all)
        self.save_btn = QPushButton(tr("ocr_save"))
        self.save_btn.clicked.connect(self.save_txt)
        self.clear_btn = QPushButton(tr("ocr_clear"))
        self.clear_btn.clicked.connect(self.output.clear)
        row_out = QHBoxLayout()
        row_out.addStretch(1)
        row_out.addWidget(self.copy_btn)
        row_out.addWidget(self.save_btn)
        row_out.addWidget(self.clear_btn)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.output, 1)
        right_layout.addLayout(row_out)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([420, 700])
        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

        self.set_busy(False)
        self.update_counts()
        self.update_output_buttons()

    def status(self, message: str) -> None:
        window = self.window()
        if isinstance(window, QMainWindow):
            window.statusBar().showMessage(message, 10000)

    def set_busy(self, busy: bool) -> None:
        for widget in (self.progress_label, self.progress_bar, self.cancel_btn):
            widget.setVisible(busy)
        self.language.setEnabled(not busy)
        self.auto_enhance.setEnabled(not busy)
        self.clear_btn.setEnabled(not busy and bool(self.output.toPlainText()))
        self.update_counts()

    def is_busy(self) -> bool:
        return self._job is not None

    def run_job(self, job: Job) -> None:
        self._job = job
        job.progress.connect(self.on_progress)
        self._thread = start_job(self, job)
        self.set_busy(True)

    def job_ended(self) -> None:
        self._job = None
        self._thread = None
        self.set_busy(False)
        self.run_next_pdf()

    def on_progress(self, done: int, total: int, text: str) -> None:
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)
        self.progress_label.setText(text)

    def cancel_job(self) -> None:
        self._pdf_queue.clear()
        if self._job:
            self._job.cancel()
            self.progress_label.setText(tr("stopping"))

    def choose_images(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(IMAGE_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(self, tr("ocr_add_images_dialog"), "", tr("filter_images", patterns=patterns))
        if files:
            added = self.image_list.add_image_paths(sorted(files, key=lambda f: natural_key(Path(f))))
            self.status(tr("added_images", count=added))

    def choose_pdfs(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, tr("ocr_add_pdf_dialog"), "", tr("filter_pdf"))
        if files:
            self.add_pdfs(files)

    def add_pdfs(self, paths: list) -> None:
        for raw in paths:
            path = str(Path(raw).resolve())
            if path in self._added_pdfs or any(q[0] == path for q in self._pdf_queue):
                self.status(tr("already_in_list", name=Path(path).name))
                continue
            self._pdf_queue.append((path, None, "images"))
        self.run_next_pdf()

    def run_next_pdf(self) -> None:
        if self.is_busy() or not self._pdf_queue:
            return
        path, password, mode = self._current_pdf = self._pdf_queue.pop(0)
        self._pdf_counter += 1
        out_dir = str(Path(self._temp.name) / f"pdf{self._pdf_counter}")
        job = Job(pdf_job, path, out_dir, password, mode)
        job.finished.connect(self.on_pdf_done)
        job.failed.connect(self.on_pdf_failed)
        self.run_job(job)

    def on_pdf_done(self, payload) -> None:
        result, was_cancelled = payload
        path, password, mode = self._current_pdf
        name = Path(path).name
        for image in result.images:
            self.image_list.add_entry(image.label, image.path)
        if result.images:
            self._added_pdfs.add(path)
            note = tr("tiny_skipped", count=result.skipped_small) if result.skipped_small else ""
            self.status(tr("added_from_pdf", count=len(result.images), name=name, note=note))
        self.job_ended()
        if not result.images and not was_cancelled and mode == "images":
            answer = QMessageBox.question(
                self,
                tr("no_images_title"),
                tr("no_images_textpdf", name=name),
            )
            if answer == QMessageBox.Yes:
                self._pdf_queue.insert(0, (path, password, "pages"))
                self.run_next_pdf()

    def on_pdf_failed(self, exc) -> None:
        path, _password, mode = self._current_pdf
        name = Path(path).name
        self.job_ended()
        if isinstance(exc, PdfPasswordRequired):
            password, ok = QInputDialog.getText(
                self, tr("password_needed"), tr("password_prompt", name=name),
                QLineEdit.Password,
            )
            if ok and password:
                self._pdf_queue.insert(0, (path, password, mode))
                self.run_next_pdf()
            return
        QMessageBox.warning(self, tr("could_not_open_pdf"), tr("could_not_read_msg", name=name, error=exc))

    def remove_selected(self) -> None:
        for item in self.image_list.selectedItems():
            self.image_list.takeItem(self.image_list.row(item))

    def crop_selected(self) -> None:
        items = self.image_list.selectedItems()
        if not items:
            QMessageBox.information(self, tr("nothing_highlighted"), tr("click_image_first"))
            return
        item = items[0]
        source = item.data(CROP_ROLE) or item.data(PATH_ROLE)
        dialog = CropDialog(source, self)
        if dialog.exec() != QDialog.Accepted:
            return
        cropped = dialog.cropped_image()
        if cropped is None:
            item.setData(CROP_ROLE, None)
            self._reset_thumb(item, item.data(PATH_ROLE))
            self._mark_cropped(item, False)
            self.status(tr("using_whole"))
            return
        self._crop_counter += 1
        out = str(Path(self._temp.name) / f"crop{self._crop_counter}.png")
        cropped.save(out, "PNG")
        item.setData(CROP_ROLE, out)
        self._reset_thumb(item, out)
        self._mark_cropped(item, True)
        self.status(tr("cropped_name", name=item.data(LABEL_ROLE)))

    def uncrop_selected(self) -> None:
        restored = 0
        for item in self.image_list.selectedItems():
            if item.data(CROP_ROLE):
                item.setData(CROP_ROLE, None)
                self._reset_thumb(item, item.data(PATH_ROLE))
                self._mark_cropped(item, False)
                restored += 1
        if restored:
            self.status(tr("uncropped", count=restored))
        else:
            QMessageBox.information(self, tr("nothing_to_uncrop"), tr("highlight_cropped"))

    def _mark_cropped(self, item, cropped: bool) -> None:
        base = item.data(LABEL_ROLE)
        item.setText(f"\u2702 {base}" if cropped else base)

    def _reset_thumb(self, item, path: str) -> None:
        item.setIcon(load_thumbnail(path))

    def set_all_checked(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        for i in range(self.image_list.count()):
            self.image_list.item(i).setCheckState(state)

    def check_all(self) -> None:
        self.set_all_checked(True)

    def check_none(self) -> None:
        self.set_all_checked(False)

    def checked_items(self) -> list[tuple[str, str]]:
        items = []
        for i in range(self.image_list.count()):
            item = self.image_list.item(i)
            if item.checkState() == Qt.Checked:
                crop = item.data(CROP_ROLE)
                path = crop or item.data(PATH_ROLE)
                items.append((item.data(LABEL_ROLE), path, bool(crop)))
        return items

    def update_counts(self, *_) -> None:
        total = self.image_list.count()
        selected = len(self.checked_items())
        self.count_label.setText(tr("images_selected", selected=selected, total=total))
        self.extract_btn.setEnabled(selected > 0 and not self.is_busy())

    def extract_selected(self) -> None:
        if self.is_busy():
            return
        if not ocr.setup_tesseract():
            QMessageBox.critical(
                self, tr("tess_not_found_title"), tr("tess_not_found"),
            )
            return
        lang_code = self.language.currentData()
        try:
            missing = ocr.missing_languages(lang_code)
        except Exception as exc:
            QMessageBox.critical(self, tr("tess_error_title"), tr("tess_error", error=exc))
            return
        if missing:
            QMessageBox.critical(
                self, tr("lang_missing_title"), tr("lang_missing", langs=", ".join(missing)),
            )
            return
        job = Job(ocr_job, self.checked_items(), lang_code, self.auto_enhance.isChecked())
        job.item_done.connect(self.on_ocr_item)
        job.finished.connect(self.on_ocr_done)
        job.failed.connect(self.on_ocr_failed)
        self.run_job(job)

    def on_ocr_item(self, payload) -> None:
        label, text, cropped = payload
        if cropped:
            label = f"{label} (cropped to a selected part of the image before extracting)"
        doc = self.output.document()
        first_new_block = max(doc.blockCount() - 1, 0)
        prefix = "\n" if doc.toPlainText().strip() else ""
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(prefix + ocr.format_block(label, text))
        block = doc.findBlockByNumber(first_new_block)
        while block.isValid():
            fmt = block.blockFormat()
            fmt.setLayoutDirection(Qt.RightToLeft if starts_right_to_left(block.text()) else Qt.LeftToRight)
            QTextCursor(block).setBlockFormat(fmt)
            block = block.next()
        self.output.moveCursor(QTextCursor.End)

    def on_ocr_done(self, payload) -> None:
        done, total = payload
        self.job_ended()
        if done < total:
            self.status(tr("ocr_stopped", done=done, total=total))
        else:
            self.status(tr("ocr_done", count=done))

    def on_ocr_failed(self, exc) -> None:
        self.job_ended()
        QMessageBox.warning(self, tr("extraction_failed"), str(exc))

    def update_output_buttons(self) -> None:
        has_text = bool(self.output.toPlainText().strip())
        self.copy_btn.setEnabled(has_text)
        self.save_btn.setEnabled(has_text)
        self.clear_btn.setEnabled(has_text and not self.is_busy())

    def copy_all(self) -> None:
        QApplication.clipboard().setText(self.output.toPlainText())
        self.status(tr("copied"))

    def save_txt(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("ocr_save_dialog"), str(Path.home() / "extracted_text.txt"), tr("filter_txt")
        )
        if not path:
            return
        text = self.output.toPlainText().rstrip("\n") + "\n"
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, tr("could_not_save"), tr("could_not_save_msg", error=exc))
            return
        self.status(tr("saved_file", path=path))

    def shutdown(self) -> bool:
        self._pdf_queue.clear()
        stopped = stop_job(self._job, self._thread)
        shutil.rmtree(self._temp.name, ignore_errors=True)
        return stopped
