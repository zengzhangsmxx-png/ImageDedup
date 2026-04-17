"""Lightweight borderless image viewer with single-image forensic tabs."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..engine.forensics import ForensicAnalyzer
from ..engine.hasher import DuplicateGroup
from .widgets import ImageViewer


class ImageViewerDialog(QDialog):
    """macOS Preview-like borderless overlay viewer."""

    def __init__(self, file_path: str, group: DuplicateGroup, parent=None):
        super().__init__(parent)
        self._file_path = file_path
        self._group = group
        self._loaded_tabs: set[int] = set()
        self._analyzer = ForensicAnalyzer()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        screen = parent.screen() if parent else QApplication.primaryScreen()
        geo = screen.availableGeometry()
        self.setGeometry(geo)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._overlay = _OverlayWidget(self)
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setContentsMargins(40, 30, 40, 30)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        content = QWidget()
        max_w = int(geo.width() * 0.82)
        max_h = int(geo.height() * 0.88)
        content.setMaximumSize(max_w, max_h)
        content.setStyleSheet(
            "background: rgba(28, 28, 30, 245); border-radius: 14px;"
        )
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 12)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            "QTabWidget::pane { border: none; background: transparent; }"
            "QTabBar::tab { color: #ccc; padding: 6px 14px; }"
            "QTabBar::tab:selected { color: #fff; border-bottom: 2px solid #4CAF50; }"
        )

        # Tab 0: image preview
        img_tab = QWidget()
        img_layout = QVBoxLayout(img_tab)
        img_layout.setContentsMargins(0, 0, 0, 0)
        viewer = ImageViewer()
        viewer.setStyleSheet("background: transparent; border: none;")
        viewer.set_image_path(file_path)
        img_layout.addWidget(viewer, 1)
        info = QLabel(file_path)
        info.setStyleSheet("color: rgba(255,255,255,140); font-size: 11px;")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setWordWrap(True)
        img_layout.addWidget(info)
        self._tabs.addTab(img_tab, "图片预览")

        # Tab 1: ELA
        self._tab_ela = QWidget()
        QVBoxLayout(self._tab_ela)
        self._tabs.addTab(self._tab_ela, "ELA 错误级别")

        # Tab 2: Noise
        self._tab_noise = QWidget()
        QVBoxLayout(self._tab_noise)
        self._tabs.addTab(self._tab_noise, "噪声分析")

        # Tab 3: Lighting
        self._tab_lighting = QWidget()
        QVBoxLayout(self._tab_lighting)
        self._tabs.addTab(self._tab_lighting, "光照与边缘")

        self._tabs.currentChanged.connect(self._on_tab_changed)
        content_layout.addWidget(self._tabs, 1)

        hint = QLabel("按 Esc 或点击外部区域关闭")
        hint.setStyleSheet("color: rgba(255,255,255,80); font-size: 11px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(hint)

        overlay_layout.addWidget(content)
        layout.addWidget(self._overlay)

        self._content_widget = content

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        content_geo = self._content_widget.geometry()
        mapped = self._overlay.mapFrom(self, event.pos())
        if not content_geo.contains(mapped):
            self.close()
        else:
            super().mousePressEvent(event)

    def _on_tab_changed(self, index: int):
        if index == 0 or index in self._loaded_tabs:
            return
        self._loaded_tabs.add(index)

        if index == 1:
            self._load_ela()
        elif index == 2:
            self._load_noise()
        elif index == 3:
            self._load_lighting()

    def _clear_layout(self, widget: QWidget):
        layout = widget.layout()
        while layout.count():
            child = layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

    def _make_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: rgba(255,255,255,180); font-size: 12px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return lbl

    def _load_ela(self):
        self._clear_layout(self._tab_ela)
        layout = self._tab_ela.layout()
        ela = self._analyzer.error_level_analysis(self._file_path)
        if ela is not None:
            v = ImageViewer()
            v.setStyleSheet("background: transparent; border: none;")
            v.set_image_array(ela)
            layout.addWidget(v, 1)
            layout.addWidget(self._make_label("亮区域表示可能被编辑过的区域"))
        else:
            layout.addWidget(self._make_label("无法执行 ELA 分析"))

    def _load_noise(self):
        self._clear_layout(self._tab_noise)
        layout = self._tab_noise.layout()
        result = self._analyzer.single_noise_analysis(self._file_path)
        if result:
            v = ImageViewer()
            v.setStyleSheet("background: transparent; border: none;")
            v.set_image_array(result.noise_image)
            layout.addWidget(v, 1)
            layout.addWidget(self._make_label(f"噪声水平: {result.noise_level}"))
        else:
            layout.addWidget(self._make_label("无法执行噪声分析"))

    def _load_lighting(self):
        self._clear_layout(self._tab_lighting)
        layout = self._tab_lighting.layout()
        result = self._analyzer.single_lighting_analysis(self._file_path)
        if result:
            v = ImageViewer()
            v.setStyleSheet("background: transparent; border: none;")
            v.set_image_array(result.edges)
            layout.addWidget(v, 1)
            layout.addWidget(self._make_label("Canny 边缘检测结果"))
        else:
            layout.addWidget(self._make_label("无法执行光照分析"))


class _OverlayWidget(QWidget):
    """Dark semi-transparent background."""

    def __init__(self, parent=None):
        super().__init__(parent)

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QColor
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 180))
        painter.end()
