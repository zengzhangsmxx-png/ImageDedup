"""Custom widgets — ImageViewer, ThresholdSlider, DropListWidget."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QSlider, QWidget


def numpy_to_qpixmap(arr: np.ndarray) -> QPixmap:
    """Convert a numpy array (BGR or grayscale) to QPixmap."""
    if arr.ndim == 2:
        h, w = arr.shape
        qimg = QImage(arr.data, w, h, w, QImage.Format.Format_Grayscale8)
    else:
        if arr.shape[2] == 3:
            rgb = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
        else:
            rgb = arr
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


class ImageViewer(QLabel):
    """Scalable image display widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(200, 200)
        self.setStyleSheet("background: #f0f0f0; border: 1px solid #ccc; border-radius: 4px;")
        self._pixmap: QPixmap | None = None

    def set_image_path(self, path: str):
        pm = QPixmap(path)
        if pm.isNull():
            self.setText("无法加载图片")
            self._pixmap = None
            return
        self._pixmap = pm
        self._fit()

    def set_image_array(self, arr: np.ndarray):
        self._pixmap = numpy_to_qpixmap(arr)
        self._fit()

    def _fit(self):
        if self._pixmap:
            scaled = self._pixmap.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()


class ThresholdSlider(QWidget):
    """QSlider + value label for perceptual hash threshold."""

    value_changed = pyqtSignal(int)

    def __init__(self, label: str = "感知哈希阈值", min_val: int = 0,
                 max_val: int = 20, default: int = 10, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel(label)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(min_val, max_val)
        self._slider.setValue(default)
        self._value_label = QLabel(str(default))
        self._value_label.setFixedWidth(30)
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self._label)
        layout.addWidget(self._slider, 1)
        layout.addWidget(self._value_label)

        self._slider.valueChanged.connect(self._on_change)

    def _on_change(self, val: int):
        self._value_label.setText(str(val))
        self.value_changed.emit(val)

    def value(self) -> int:
        return self._slider.value()


class DropListWidget(QListWidget):
    """QListWidget that accepts file/folder drag-and-drop."""

    ACCEPTED_EXTENSIONS = {
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif",
        ".zip", ".xlsx", ".xls", ".pdf",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            p = Path(local)
            if p.is_dir() or (p.is_file() and p.suffix.lower() in self.ACCEPTED_EXTENSIONS):
                self.addItem(local)
        event.acceptProposedAction()
