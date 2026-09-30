"""Help > About: app info and developer contact."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from app import DEVELOPER_EMAIL, __version__
from app.i18n import tr


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("about_title"))
        self.setMinimumWidth(460)

        title = QLabel("DocToolkit")
        font = QFont(title.font())
        font.setPointSize(font.pointSize() + 8)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignCenter)

        version = QLabel(tr("about_version", version=__version__))
        version.setAlignment(Qt.AlignCenter)

        desc = QLabel(tr("about_desc"))
        desc.setWordWrap(True)

        contact = QLabel(
            f"<b>{tr('developed_by')}</b><br>"
            f'{tr("email_label")} <a href="mailto:{DEVELOPER_EMAIL}">{DEVELOPER_EMAIL}</a>'
        )
        contact.setAlignment(Qt.AlignCenter)
        contact.setTextFormat(Qt.RichText)
        contact.setOpenExternalLinks(True)
        contact.setTextInteractionFlags(Qt.TextBrowserInteraction)

        credits = QLabel(tr("about_credits"))
        credits.setWordWrap(True)
        credits.setStyleSheet("color: palette(placeholder-text);")

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText(tr("close"))
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(version)
        layout.addWidget(desc)
        layout.addWidget(contact)
        layout.addWidget(credits)
        layout.addWidget(buttons)
