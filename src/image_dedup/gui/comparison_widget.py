"""Comparison and zoom widgets for image analysis."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..logging_setup import get_logger

logger = get_logger("comparison_widget")


def numpy_to_qpixmap(arr: np.ndarray) -> QPixmap:
    """Convert a numpy array (BGR or grayscale) to QPixmap."""
    try:
        if arr is None or arr.size == 0:
            return QPixmap()
        if arr.ndim == 2:
            h, w = arr.shape
            if h <= 0 or w <= 0:
                return QPixmap()
            arr = np.ascontiguousarray(arr)
            qimg = QImage(arr.data, w, h, w, QImage.Format.Format_Grayscale8)
        else:
            if len(arr.shape) < 3 or arr.shape[2] not in (3, 4):
                return QPixmap()
            if arr.shape[2] == 3:
                rgb = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
            else:
                rgb = arr
            h, w, ch = rgb.shape
            if h <= 0 or w <= 0:
                return QPixmap()
            rgb = np.ascontiguousarray(rgb)
            bytes_per_line = ch * w
            qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        return QPixmap.fromImage(qimg.copy())
    except Exception as e:
        logger.debug("numpy_to_qpixmap 转换失败: %s", e)
        return QPixmap()


class ZoomPanViewer(QGraphicsView):
    """Zoomable and pannable image viewer using QGraphicsView."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setBackgroundBrush(Qt.GlobalColor.darkGray)
        self.setStyleSheet("background: #2c2c2e; border: none;")
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._scale_factor = 1.15

    def set_image_path(self, path: str | Path):
        """Load and display an image from file path."""
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            logger.warning(f"无法加载图片: {path}")
            return
        self._set_pixmap(pixmap)

    def set_image_array(self, arr: np.ndarray):
        """Load and display an image from numpy array."""
        pixmap = numpy_to_qpixmap(arr)
        self._set_pixmap(pixmap)

    def _set_pixmap(self, pixmap: QPixmap):
        """Internal method to set pixmap in scene."""
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(pixmap.rect())
        self.fit_view()

    def wheelEvent(self, event):
        """Handle mouse wheel zoom."""
        if self._pixmap_item is None:
            return

        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def zoom_in(self):
        """Zoom in by scale factor."""
        self.scale(self._scale_factor, self._scale_factor)

    def zoom_out(self):
        """Zoom out by scale factor."""
        self.scale(1.0 / self._scale_factor, 1.0 / self._scale_factor)

    def fit_view(self):
        """Fit the entire image in the view."""
        if self._pixmap_item is not None:
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


class ComparisonSlider(QWidget):
    """Side-by-side image comparison with draggable vertical divider."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)

        self._pixmap_a: QPixmap | None = None
        self._pixmap_b: QPixmap | None = None
        self._split_ratio = 0.5
        self._dragging = False
        self._divider_width = 4

    def set_images(self, path_a: str | Path, path_b: str | Path):
        """Load two images for comparison."""
        self._pixmap_a = QPixmap(str(path_a))
        self._pixmap_b = QPixmap(str(path_b))

        if self._pixmap_a.isNull():
            logger.warning(f"无法加载图片A: {path_a}")
        if self._pixmap_b.isNull():
            logger.warning(f"无法加载图片B: {path_b}")

        self.update()

    def set_split_position(self, ratio: float):
        """Set divider position (0.0 = left, 1.0 = right)."""
        self._split_ratio = max(0.0, min(1.0, ratio))
        self.update()

    def paintEvent(self, event):
        """Draw the two images with divider."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)

        if self._pixmap_a is None or self._pixmap_b is None:
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "未加载图片")
            return

        w = self.width()
        h = self.height()
        divider_x = int(w * self._split_ratio)

        # Scale images to fit widget height
        scaled_a = self._pixmap_a.scaledToHeight(h, Qt.TransformationMode.SmoothTransformation)
        scaled_b = self._pixmap_b.scaledToHeight(h, Qt.TransformationMode.SmoothTransformation)

        # Draw left image (clipped to divider)
        painter.setClipRect(0, 0, divider_x, h)
        painter.drawPixmap(0, 0, scaled_a)

        # Draw right image (clipped from divider)
        painter.setClipRect(divider_x, 0, w - divider_x, h)
        painter.drawPixmap(w - scaled_b.width(), 0, scaled_b)

        # Draw divider handle
        painter.setClipping(False)
        painter.fillRect(
            divider_x - self._divider_width // 2,
            0,
            self._divider_width,
            h,
            Qt.GlobalColor.green
        )

    def mousePressEvent(self, event):
        """Start dragging divider."""
        if event.button() == Qt.MouseButton.LeftButton:
            divider_x = int(self.width() * self._split_ratio)
            if abs(event.pos().x() - divider_x) <= 10:
                self._dragging = True
                self.setCursor(Qt.CursorShape.SizeHorCursor)

    def mouseMoveEvent(self, event):
        """Update divider position while dragging."""
        divider_x = int(self.width() * self._split_ratio)

        if self._dragging:
            self._split_ratio = event.pos().x() / self.width()
            self._split_ratio = max(0.0, min(1.0, self._split_ratio))
            self.update()
        elif abs(event.pos().x() - divider_x) <= 10:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        """Stop dragging divider."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)


class ExtractionProgressDialog(QDialog):
    """Modal dialog showing archive extraction progress."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("解压进度")
        self.setModal(True)
        self.setMinimumWidth(400)
        self._cancelled = False

        layout = QVBoxLayout(self)

        self._archive_label = QLabel("正在解压...")
        layout.addWidget(self._archive_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(0)  # Indeterminate mode
        layout.addWidget(self._progress_bar)

        self._count_label = QLabel("已解压 0 个文件")
        layout.addWidget(self._count_label)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self._on_cancel)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def set_archive_name(self, name: str):
        """Set the archive name being extracted."""
        self._archive_label.setText(f"正在解压: {name}")

    def update_progress(self, current: int, total: int | None = None):
        """Update progress bar and count label."""
        self._count_label.setText(f"已解压 {current} 个文件")

        if total is not None and total > 0:
            self._progress_bar.setMaximum(total)
            self._progress_bar.setValue(current)
        else:
            # Keep indeterminate mode
            self._progress_bar.setMaximum(0)

    def is_cancelled(self) -> bool:
        """Check if user cancelled the operation."""
        return self._cancelled

    def _on_cancel(self):
        """Handle cancel button click."""
        self._cancelled = True
        self.reject()
