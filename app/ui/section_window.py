"""A window that shows one metadata section as a Tag / Value table.

Edits are kept in the Metadata tab's list of pending changes as soon as a
value is typed (press Enter or Tab, or click elsewhere). Nothing is written to
the file until the user clicks Save changes on the Metadata tab.
"""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.metadata import Entry, Section, check_value
from app.i18n import tr

ENTRY_ROLE = Qt.UserRole


def is_dark(widget: QWidget) -> bool:
    return widget.palette().window().color().lightness() < 128


def status_colors(widget: QWidget) -> dict[str, QColor]:
    """Colours that read well on both light and dark Windows themes."""
    if is_dark(widget):
        return {"changed": QColor("#ffb74d"), "error": QColor("#ff8a80"),
                "changed_bg": QColor(255, 183, 77, 55), "error_bg": QColor(255, 138, 128, 70)}
    return {"changed": QColor("#9a5b00"), "error": QColor("#c62828"),
            "changed_bg": QColor(255, 193, 7, 70), "error_bg": QColor(229, 57, 53, 55)}


class SectionWindow(QDialog):
    edited = Signal(str)  # section id

    def __init__(self, section: Section, changes: dict[str, str], file_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
        self.setModal(False)
        self.resize(820, 600)
        self._filling = False
        self._file_name = file_name
        self._colors = status_colors(self)

        self.title_label = QLabel()
        font = self.title_label.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        self.title_label.setFont(font)
        self.desc_label = QLabel()
        self.desc_label.setWordWrap(True)
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setOpenExternalLinks(True)
        self.message_label.setFrameShape(QLabel.StyledPanel)
        self.message_label.setMargin(8)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(tr("win_filter"))
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([tr("col_tag"), tr("col_value")])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 300)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.AnyKeyPressed)
        self.table.setWordWrap(True)
        self.table.itemChanged.connect(self._on_item_changed)

        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: palette(placeholder-text);")

        self.revert_btn = QPushButton(tr("win_revert"))
        self.revert_btn.clicked.connect(self.revert)
        close_btn = QPushButton(tr("close"))
        close_btn.setDefault(False)
        close_btn.setAutoDefault(False)
        close_btn.clicked.connect(self.close)
        self.revert_btn.setAutoDefault(False)
        buttons = QHBoxLayout()
        buttons.addWidget(self.revert_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addWidget(self.desc_label)
        layout.addWidget(self.message_label)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.hint_label)
        layout.addLayout(buttons)

        self.set_section(section, changes, file_name)

    # --- filling ------------------------------------------------------------
    def set_section(self, section: Section, changes: dict[str, str], file_name: str | None = None) -> None:
        """Show a section. Also used to refresh the window after a save."""
        self._section = section
        self._changes = changes
        if file_name:
            self._file_name = file_name
        self.setWindowTitle(tr("win_title", section=section.title, name=self._file_name))
        self.title_label.setText(section.title)
        self.desc_label.setText(section.description)
        self.message_label.setTextFormat(Qt.RichText if section.message_is_rich else Qt.PlainText)
        self.message_label.setText(section.message)
        self.message_label.setVisible(bool(section.message))

        editable = [e for e in section.entries if e.editable and not section.read_only]
        hints = [tr("win_hint")] if editable else []
        if any(e.kind == "date" for e in editable):
            hints.append(tr("win_date_hint"))
        if any(e.kind == "list" for e in editable):
            hints.append(tr("win_list_hint"))
        self.hint_label.setText("\n".join(hints))
        self.hint_label.setVisible(bool(hints))
        self.revert_btn.setVisible(bool(editable))
        self.filter_edit.setVisible(len(section.entries) > 8)

        self._filling = True
        self.table.setRowCount(0)
        self.table.setRowCount(len(section.entries))
        c = self.palette().placeholderText().color()
        grey = f"rgba({c.red()},{c.green()},{c.blue()},{max(c.alpha(), 140)})"
        for row, entry in enumerate(section.entries):
            can_edit = entry.editable and not section.read_only
            key_line = entry.key if entry.key != entry.tag else ""
            if not can_edit and not section.read_only:  # a read-only section says so once, at the top
                key_line = f"{key_line} ({tr('win_read_only')})" if key_line else tr("win_read_only")
            tag_label = QLabel(
                f"<b>{html.escape(entry.tag)}</b>"
                + (f"<br><span style='color:{grey}'>{html.escape(key_line)}</span>" if key_line else "")
            )
            tag_label.setTextFormat(Qt.RichText)
            tag_label.setContentsMargins(6, 4, 6, 4)
            tag_label.setToolTip(entry.note)
            tag_item = QTableWidgetItem()  # empty: the label above draws the tag
            tag_item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 0, tag_item)
            self.table.setCellWidget(row, 0, tag_label)

            value = self._changes.get(entry.key, entry.value)
            item = QTableWidgetItem(value)
            item.setData(ENTRY_ROLE, row)
            if can_edit:
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
            else:
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                item.setForeground(self.palette().placeholderText())
            self.table.setItem(row, 1, item)
            self._style(item, entry)
        self._filling = False
        self.table.resizeRowsToContents()
        self._apply_filter(self.filter_edit.text())

    def _style(self, item: QTableWidgetItem, entry: Entry) -> None:
        changed = entry.key in self._changes
        error = check_value(entry, item.text()) if changed else None
        tips = []
        if error:
            item.setBackground(QBrush(self._colors["error_bg"]))
            tips.append(error)
        elif changed:
            item.setBackground(QBrush(self._colors["changed_bg"]))
        else:
            item.setBackground(QBrush())
        if entry.note:
            tips.append(entry.note)
        if entry.raw:
            tips.append(tr("win_stored_as", raw=entry.raw))
        item.setToolTip("\n\n".join(tips))

    # --- editing -------------------------------------------------------------
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling or item.column() != 1:
            return
        entry = self._section.entries[item.data(ENTRY_ROLE)]
        if item.text() == entry.value:
            self._changes.pop(entry.key, None)
        else:
            self._changes[entry.key] = item.text()
        self._filling = True
        self._style(item, entry)
        self._filling = False
        self.table.resizeRowToContents(item.row())
        self.edited.emit(self._section.id)

    def commit_edit(self) -> None:
        """Finish a value that is still being typed (as if Enter was pressed)."""
        self.table.setCurrentItem(None)

    def revert(self) -> None:
        self.commit_edit()
        self._changes.clear()
        self.set_section(self._section, self._changes)
        self.edited.emit(self._section.id)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row, entry in enumerate(self._section.entries):
            value = self.table.item(row, 1).text() if self.table.item(row, 1) else ""
            haystack = f"{entry.tag} {entry.key} {value}".lower()
            self.table.setRowHidden(row, bool(needle) and needle not in haystack)

    def done(self, result: int) -> None:
        # Called for Close, the window's X button and Esc: keep what was typed.
        self.commit_edit()
        super().done(result)

    def keyPressEvent(self, event) -> None:
        # Esc closes the window (edits are already kept); Enter never does.
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            return
        super().keyPressEvent(event)
