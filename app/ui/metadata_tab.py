from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from app.core import metadata as M
from app.i18n import tr
from app.ui.section_window import SectionWindow, status_colors


class DropArea(QWidget):
    file_dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".pdf", ".docx")):
                self.file_dropped.emit(path)
                break
        event.acceptProposedAction()


class MetadataTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._meta: M.FileMetadata | None = None
        self._changes: dict[str, dict[str, str]] = {}
        self._windows: dict[str, SectionWindow] = {}
        self._status_labels: dict[str, QLabel] = {}
        self._count_labels: dict[str, QLabel] = {}
        self._colors = status_colors(self)

        root = DropArea()
        root.file_dropped.connect(self.open_path)
        outer = QVBoxLayout(self)
        outer.addWidget(root)
        layout = QVBoxLayout(root)

        open_btn = QPushButton(tr("meta_open"))
        open_btn.clicked.connect(self.choose_file)
        self.file_label = QLabel(tr("meta_none"))
        self.file_label.setWordWrap(True)
        top = QHBoxLayout()
        top.addWidget(open_btn)
        top.addWidget(self.file_label, 1)
        layout.addLayout(top)

        self.sections_box = QGroupBox(tr("meta_sections"))
        box_layout = QVBoxLayout(self.sections_box)
        self.hint_label = QLabel(tr("meta_hint"))
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: palette(placeholder-text);")
        box_layout.addWidget(self.hint_label)
        self.rows = QGridLayout()
        self.rows.setColumnStretch(1, 1)
        self.rows.setHorizontalSpacing(16)
        self.rows.setVerticalSpacing(10)
        box_layout.addLayout(self.rows)
        self.empty_label = QLabel(tr("meta_empty"))
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: palette(placeholder-text); padding: 24px;")
        box_layout.addWidget(self.empty_label)
        self.sync_box = QCheckBox(tr("meta_sync"))
        self.sync_box.setToolTip(tr("meta_sync_tip"))
        self.sync_box.setChecked(True)
        box_layout.addWidget(self.sync_box)
        layout.addWidget(self.sections_box)

        self.save_box = QGroupBox(tr("meta_saving"))
        save_layout = QVBoxLayout(self.save_box)
        self.copy_radio = QRadioButton(tr("meta_copy"))
        self.overwrite_radio = QRadioButton(tr("meta_overwrite"))
        self.copy_radio.setChecked(True)
        save_layout.addWidget(self.copy_radio)
        save_layout.addWidget(self.overwrite_radio)
        self.file_dates = QCheckBox(tr("meta_file_dates"))
        self.file_dates.setToolTip(tr("meta_file_dates_tip"))
        self.file_dates.setChecked(True)
        save_layout.addWidget(self.file_dates)
        layout.addWidget(self.save_box)
        layout.addStretch(1)

        self.clear_btn = QPushButton(tr("meta_clear"))
        self.clear_btn.clicked.connect(self.clear_all)
        self.unsaved_label = QLabel(tr("meta_unsaved"))
        self.unsaved_label.setStyleSheet(f"color: {self._colors['changed'].name()}; font-weight: bold;")
        self.discard_btn = QPushButton(tr("meta_discard"))
        self.discard_btn.clicked.connect(self.discard_changes)
        self.save_btn = QPushButton(tr("meta_save"))
        self.save_btn.clicked.connect(self.save_changes)
        actions = QHBoxLayout()
        actions.addWidget(self.clear_btn)
        actions.addStretch(1)
        actions.addWidget(self.unsaved_label)
        actions.addWidget(self.discard_btn)
        actions.addWidget(self.save_btn)
        layout.addLayout(actions)

        self._build_rows()
        self._update_state()

    def status(self, message: str) -> None:
        window = self.window()
        if isinstance(window, QMainWindow):
            window.statusBar().showMessage(message, 10000)

    def _overwrite(self) -> bool:
        return self.overwrite_radio.isChecked()

    def _pending(self) -> dict[str, dict[str, str]]:
        return {sid: dict(edits) for sid, edits in self._changes.items() if edits}

    def has_unsaved_changes(self) -> bool:
        self._commit_windows()
        return bool(self._pending())

    def confirm_discard(self, quitting: bool = False) -> bool:
        if not self.has_unsaved_changes():
            return True
        if quitting:
            title, text = tr("quit_unsaved_title"), tr("quit_unsaved")
        else:
            title = tr("meta_discard_title")
            text = tr("meta_discard_msg", name=Path(self._meta.path).name)
        answer = QMessageBox.question(self, title, text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def _build_rows(self) -> None:
        while self.rows.count():
            widget = self.rows.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        self._status_labels.clear()
        self._count_labels.clear()
        sections = self._meta.sections if self._meta else []
        self.empty_label.setVisible(not sections)
        self.hint_label.setVisible(bool(sections))
        self.sync_box.setVisible(bool(self._meta) and self._meta.kind == "pdf")
        for row, section in enumerate(sections):
            title = QLabel(section.title)
            bold = QFont(title.font())
            bold.setBold(True)
            title.setFont(bold)
            desc = QLabel(section.description)
            desc.setStyleSheet("color: palette(placeholder-text);")
            count = QLabel()
            count.setStyleSheet("color: palette(placeholder-text);")
            state = QLabel()
            button = QPushButton(tr("meta_open_section"))
            button.clicked.connect(lambda _=False, sid=section.id: self.open_section(sid))
            self.rows.addWidget(title, row, 0)
            self.rows.addWidget(desc, row, 1)
            self.rows.addWidget(count, row, 2, Qt.AlignRight)
            self.rows.addWidget(state, row, 3)
            self.rows.addWidget(button, row, 4)
            self._count_labels[section.id] = count
            self._status_labels[section.id] = state
            self._update_row(section.id)

    def _update_row(self, section_id: str) -> None:
        section = self._meta.section(section_id) if self._meta else None
        if section is None or section_id not in self._status_labels:
            return
        count = self._count_labels[section_id]
        count.setText(tr("meta_lazy") if section.lazy and not section.loaded
                      else tr("meta_tags", count=len(section.entries)))
        edits = self._changes.get(section_id, {})
        errors = sum(1 for key, text in edits.items()
                     if (e := section.entry(key)) is not None and M.check_value(e, text))
        state = self._status_labels[section_id]
        if errors:
            state.setText(tr("meta_needs_fixing", count=errors))
            state.setStyleSheet(f"color: {self._colors['error'].name()}; font-weight: bold;")
        elif edits:
            state.setText(tr("meta_modified", count=len(edits)))
            state.setStyleSheet(f"color: {self._colors['changed'].name()}; font-weight: bold;")
        else:
            state.setText("")

    def _on_section_edited(self, section_id: str) -> None:
        self._update_row(section_id)
        self._update_state()

    def _update_state(self) -> None:
        loaded = self._meta is not None
        dirty = bool(self._pending())
        self.save_box.setEnabled(loaded)
        self.clear_btn.setEnabled(loaded)
        self.save_btn.setEnabled(dirty)
        self.discard_btn.setEnabled(dirty)
        self.unsaved_label.setVisible(dirty)

    def open_section(self, section_id: str) -> None:
        if self._meta is None:
            return
        window = self._windows.get(section_id)
        if window is not None:
            window.showNormal()
            window.raise_()
            window.activateWindow()
            return
        section = self._meta.section(section_id)
        self._ensure_loaded(section)
        window = SectionWindow(section, self._changes.setdefault(section_id, {}),
                               Path(self._meta.path).name, self)
        window.edited.connect(self._on_section_edited)
        window.finished.connect(lambda _r, sid=section_id: self._forget_window(sid))
        self._windows[section_id] = window
        window.show()

    def _ensure_loaded(self, section: M.Section) -> None:
        if section.lazy and not section.loaded:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                M.fill_exiftool(section, self._meta.path)
            finally:
                QApplication.restoreOverrideCursor()
            self._update_row(section.id)

    def _forget_window(self, section_id: str) -> None:
        window = self._windows.pop(section_id, None)
        if window is not None:
            window.deleteLater()
        self._update_row(section_id)
        self._update_state()

    def _commit_windows(self) -> None:
        for window in list(self._windows.values()):
            window.commit_edit()

    def _close_windows(self) -> None:
        for window in list(self._windows.values()):
            window.close()
        self._windows.clear()

    def _refresh_windows(self) -> None:
        name = Path(self._meta.path).name
        for section_id, window in list(self._windows.items()):
            section = self._meta.section(section_id)
            if section is None:
                window.close()
                continue
            self._ensure_loaded(section)
            window.set_section(section, self._changes.setdefault(section_id, {}), name)

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("meta_open_dialog"), "", tr("filter_pdf_docx"))
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> None:
        if Path(path).suffix.lower() not in (".pdf", ".docx"):
            QMessageBox.warning(self, tr("unsupported_title"), tr("unsupported"))
            return
        if not self.confirm_discard():
            return
        meta = self._read(path)
        if meta is None:
            return
        self._close_windows()
        self._show(meta)
        self.status(tr("opened", name=Path(path).name))

    def _read(self, path: str, password: str | None = None) -> M.FileMetadata | None:
        name = Path(path).name
        while True:
            try:
                return M.load(path, password)
            except M.PdfPasswordRequired:
                password, ok = QInputDialog.getText(
                    self, tr("password_needed"), tr("password_prompt", name=name), QLineEdit.Password)
                if not ok:
                    return None
            except Exception as exc:
                QMessageBox.warning(self, tr("could_not_read"),
                                    tr("could_not_read_msg", name=name, error=M.friendly_error(exc)))
                return None

    def _show(self, meta: M.FileMetadata) -> None:
        self._meta = meta
        self._changes = {}
        self.file_label.setText(f"{Path(meta.path).name}  ({meta.kind.upper()})")
        self._build_rows()
        self._update_state()

    def save_changes(self) -> None:
        if self._meta is None:
            return
        self._commit_windows()
        changes = self._pending()
        if not changes:
            QMessageBox.information(self, tr("nothing_changed_title"), tr("nothing_changed"))
            return
        problems = M.find_problems(self._meta, changes)
        if problems:
            QMessageBox.warning(self, tr("meta_fix_title"), tr("meta_fix_msg", problems="\n".join(problems)))
            return
        try:
            out = M.save(self._meta, changes, self._overwrite(), sync=self.sync_box.isChecked())
        except Exception as exc:
            QMessageBox.warning(self, tr("could_not_save"), tr("could_not_save_msg", error=M.friendly_error(exc)))
            return
        self._after_write(out, cleared=False)

    def discard_changes(self) -> None:
        self._commit_windows()
        self._changes = {}
        self._refresh_windows()
        for section_id in self._status_labels:
            self._update_row(section_id)
        self._update_state()

    def clear_all(self) -> None:
        if self._meta is None:
            return
        unsaved = tr("clear_unsaved") if self.has_unsaved_changes() else ""
        mode = tr("clear_mode_overwrite") if self._overwrite() else tr("clear_mode_copy")
        answer = QMessageBox.question(self, tr("clear_confirm_title"),
                                      tr("clear_confirm", mode=mode, unsaved=unsaved))
        if answer != QMessageBox.Yes:
            return
        try:
            out = M.clear(self._meta, self._overwrite())
        except Exception as exc:
            QMessageBox.warning(self, tr("could_not_clear"),
                                tr("could_not_read_msg", name=Path(self._meta.path).name,
                                   error=M.friendly_error(exc)))
            return
        self._after_write(out, cleared=True)

    def _after_write(self, out_path: str, cleared: bool) -> None:
        password = self._meta.password
        new_meta = self._read(out_path, password)
        if not cleared and new_meta is not None:
            self._apply_file_dates(out_path, new_meta)
        verb = tr("cleared_meta") if cleared else tr("saved_changes")
        self.status(tr("status_saved", action=verb, name=Path(out_path).name))
        note = "" if self._overwrite() else "\n\n" + tr("copy_note")
        QMessageBox.information(self, tr("done_title"), tr("done_msg", action=verb, path=out_path, note=note))
        if new_meta is None:
            self._close_windows()
            self._meta, self._changes = None, {}
            self.file_label.setText(tr("meta_none"))
            self._build_rows()
            self._update_state()
            return
        self._show(new_meta)
        self._refresh_windows()

    def _apply_file_dates(self, out_path: str, meta: M.FileMetadata) -> None:
        if not self.file_dates.isChecked():
            return
        created, modified = M.document_dates(meta)
        if created is None and modified is None:
            return
        try:
            applied_created = M.set_file_times(out_path, created, modified)
        except OSError as exc:
            QMessageBox.warning(self, tr("could_not_save"), tr("file_dates_failed", error=exc))
            return
        if created is not None and not applied_created:
            self.status(tr("file_dates_partial"))
