"""A simple crop dialog: show an image, drag a rectangle, return the crop.

Everything stays on the user's machine. Used before OCR to cut a screenshot
down to the part that matters, which is what makes small text readable.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QImage, QImageReader, QPainter, QPen, QPixmap

from app.i18n import tr
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class CropCanvas(QWidget):
    """Displays the image (fit to view) and lets the user drag a selection box."""

    def __init__(self, image: QImage) -> None:
        super().__init__()
        self._image = image
        self._start: QPoint | None = None
        self._rect = QRect()
        self._scaled = QPixmap()
        self._offset = QPoint(0, 0)
        self._scale = 1.0
        self.setMinimumSize(320, 240)
        self.setCursor(Qt.CrossCursor)

    def _rebuild(self) -> None:
        area = self.size()
        pm = QPixmap.fromImage(self._image)
        self._scaled = pm.scaled(area, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._scale = self._scaled.width() / self._image.width() if self._image.width() else 1.0
        self._offset = QPoint(
            (area.width() - self._scaled.width()) // 2,
            (area.height() - self._scaled.height()) // 2,
        )

    def resizeEvent(self, event):
        self._rebuild()
        self._rect = QRect()  # a resize clears the selection
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        if self._scaled.isNull():
            self._rebuild()
        painter.drawPixmap(self._offset, self._scaled)
        if not self._rect.isNull():
            # outline the selection
            painter.setBrush(Qt.NoBrush)
            pen = QPen(Qt.red, 2)
            painter.setPen(pen)
            painter.drawRect(self._rect)

    def _image_bounds(self) -> QRect:
        return QRect(self._offset, self._scaled.size())

    def mousePressEvent(self, event):
        if self._image_bounds().contains(event.pos()):
            self._start = event.pos()
            self._rect = QRect(self._start, self._start)
            self.update()

    def mouseMoveEvent(self, event):
        if self._start is not None:
            pos = event.pos()
            bounds = self._image_bounds()
            pos.setX(max(bounds.left(), min(pos.x(), bounds.right())))
            pos.setY(max(bounds.top(), min(pos.y(), bounds.bottom())))
            self._rect = QRect(self._start, pos).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        self._start = None

    def crop_rect(self) -> QRect | None:
        """The selection in original-image pixels, or None if nothing usable is selected."""
        if self._rect.isNull() or self._rect.width() < 5 or self._rect.height() < 5:
            return None
        x = round((self._rect.left() - self._offset.x()) / self._scale)
        y = round((self._rect.top() - self._offset.y()) / self._scale)
        w = round(self._rect.width() / self._scale)
        h = round(self._rect.height() / self._scale)
        rect = QRect(x, y, w, h).intersected(self._image.rect())
        return rect if rect.width() >= 5 and rect.height() >= 5 else None


class CropDialog(QDialog):
    def __init__(self, image_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("crop_title"))
        self.resize(900, 640)
        self._result: QImage | None = None

        # Phone photos store "rotate 90°" as a setting; apply it so the picture
        # is upright here and the cropped part is sent to OCR the right way up.
        reader = QImageReader(image_path)
        reader.setAutoTransform(True)
        self._image = reader.read()
        self.canvas = CropCanvas(self._image)

        hint = QLabel(tr("crop_hint"))
        hint.setWordWrap(True)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self.canvas)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("crop_use"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("cancel"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(area, 1)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        rect = self.canvas.crop_rect()
        if rect is not None:
            self._result = self._image.copy(rect)
        self.accept()

    def cropped_image(self) -> QImage | None:
        """The cropped region, or None if the user selected nothing (use the whole image)."""
        return self._result
