"""Startup screen: app name, version and developer credit."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QFrame, QLabel, QPushButton, QVBoxLayout

from app import DEVELOPER_EMAIL, __version__


class StartupDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DocToolkit")
        self.setMinimumWidth(420)

        title = QLabel("DocToolkit")
        font = QFont(title.font())
        font.setPointSize(font.pointSize() + 10)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignCenter)

        version = QLabel(f"v{__version__}")
        version.setAlignment(Qt.AlignCenter)

        tagline = QLabel("Offline tools for PDF and Word files")
        tagline.setAlignment(Qt.AlignCenter)

        start = QPushButton("Start")
        start.setMinimumHeight(40)
        f = QFont(start.font())
        f.setPointSize(f.pointSize() + 2)
        start.setFont(f)
        start.setDefault(True)
        start.clicked.connect(self.accept)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)

        credit = QLabel(
            "Developed by Tariq Alanazi<br>"
            f'Email: <a href="mailto:{DEVELOPER_EMAIL}">{DEVELOPER_EMAIL}</a>'
        )
        credit.setAlignment(Qt.AlignCenter)
        credit.setTextFormat(Qt.RichText)
        credit.setOpenExternalLinks(True)
        credit.setTextInteractionFlags(Qt.TextBrowserInteraction)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(version)
        layout.addWidget(tagline)
        layout.addSpacing(6)
        layout.addWidget(start)
        layout.addSpacing(6)
        layout.addWidget(line)
        layout.addWidget(credit)
