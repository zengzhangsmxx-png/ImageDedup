"""Forensic detail dialog — 5 analysis tabs with lazy loading."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..engine.forensics import ForensicAnalyzer
from ..engine.hasher import DuplicateGroup
from .widgets import ImageViewer


class ForensicDialog(QDialog):
    """Forensic analysis dialog with 5 tabs."""

    def __init__(self, group: DuplicateGroup, parent=None, config=None):
        super().__init__(parent)
        self._group = group
        self._analyzer = ForensicAnalyzer(config)
        self._loaded_tabs: set[int] = set()

        self.setWindowTitle(f"取证分析 — 重复组 #{group.group_id}")
        self.resize(1100, 750)

        layout = QVBoxLayout(self)

        # File selectors
        sel_layout = QHBoxLayout()
        sel_layout.addWidget(QLabel("图片 A:"))
        self._combo_a = QComboBox()
        self._combo_a.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sel_layout.addWidget(self._combo_a, 1)
        sel_layout.addWidget(QLabel("图片 B:"))
        self._combo_b = QComboBox()
        self._combo_b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sel_layout.addWidget(self._combo_b, 1)
        layout.addLayout(sel_layout)

        for f in group.files:
            label = f"{f.file_path.split('/')[-1]}  ({f.file_path})"
            self._combo_a.addItem(label, f.file_path)
            self._combo_b.addItem(label, f.file_path)
        if len(group.files) >= 2:
            self._combo_b.setCurrentIndex(1)

        # Side-by-side image preview
        preview_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._viewer_a = ImageViewer()
        self._viewer_b = ImageViewer()
        preview_splitter.addWidget(self._viewer_a)
        preview_splitter.addWidget(self._viewer_b)
        preview_splitter.setMaximumHeight(280)
        layout.addWidget(preview_splitter)

        # Tab widget
        self._tabs = QTabWidget()
        self._tab_metadata = QWidget()
        self._tab_pixel = QWidget()
        self._tab_ela = QWidget()
        self._tab_noise = QWidget()
        self._tab_lighting = QWidget()

        self._tabs.addTab(self._tab_metadata, "元数据对比")
        self._tabs.addTab(self._tab_pixel, "像素级差异")
        self._tabs.addTab(self._tab_ela, "ELA 错误级别")
        self._tabs.addTab(self._tab_noise, "噪声分析")
        self._tabs.addTab(self._tab_lighting, "光照与透视")

        # Init empty layouts for each tab
        for tab in (self._tab_metadata, self._tab_pixel, self._tab_ela,
                     self._tab_noise, self._tab_lighting):
            QVBoxLayout(tab)

        layout.addWidget(self._tabs, 1)

        # Connections
        self._combo_a.currentIndexChanged.connect(self._on_selection_changed)
        self._combo_b.currentIndexChanged.connect(self._on_selection_changed)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # Initial load
        self._update_previews()
        self._on_tab_changed(0)

    def _path_a(self) -> str:
        return self._combo_a.currentData()

    def _path_b(self) -> str:
        return self._combo_b.currentData()

    def _on_selection_changed(self):
        self._loaded_tabs.clear()
        self._update_previews()
        self._on_tab_changed(self._tabs.currentIndex())

    def _update_previews(self):
        self._viewer_a.set_image_path(self._path_a())
        self._viewer_b.set_image_path(self._path_b())

    def _on_tab_changed(self, index: int):
        if index in self._loaded_tabs:
            return
        self._loaded_tabs.add(index)
        pa, pb = self._path_a(), self._path_b()
        if index == 0:
            self._load_metadata(pa, pb)
        elif index == 1:
            self._load_pixel_diff(pa, pb)
        elif index == 2:
            self._load_ela(pa, pb)
        elif index == 3:
            self._load_noise(pa, pb)
        elif index == 4:
            self._load_lighting(pa, pb)

    def _clear_layout(self, widget: QWidget):
        layout = widget.layout()
        while layout.count():
            child = layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

    # --- Tab loaders ---

    def _load_metadata(self, pa: str, pb: str):
        self._clear_layout(self._tab_metadata)
        layout = self._tab_metadata.layout()
        result = self._analyzer.compare_metadata(pa, pb)

        table = QTableWidget()
        all_keys = sorted(set(result.file_a_meta.keys()) | set(result.file_b_meta.keys()))
        table.setRowCount(len(all_keys))
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["字段", "图片 A", "图片 B"])
        table.horizontalHeader().setStretchLastSection(True)

        for row, key in enumerate(all_keys):
            va = result.file_a_meta.get(key, "(缺失)")
            vb = result.file_b_meta.get(key, "(缺失)")
            table.setItem(row, 0, QTableWidgetItem(key))
            table.setItem(row, 1, QTableWidgetItem(va))
            item_b = QTableWidgetItem(vb)
            if va != vb:
                item_b.setBackground(Qt.GlobalColor.yellow)
            table.setItem(row, 2, item_b)

        table.resizeColumnsToContents()
        layout.addWidget(table)

        if result.differences:
            diff_label = QLabel(f"差异项: {len(result.differences)}")
            diff_label.setFont(QFont("", -1, QFont.Weight.Bold))
            layout.addWidget(diff_label)
        else:
            layout.addWidget(QLabel("元数据完全一致"))

    def _load_pixel_diff(self, pa: str, pb: str):
        self._clear_layout(self._tab_pixel)
        layout = self._tab_pixel.layout()
        result = self._analyzer.pixel_diff(pa, pb)
        if result is None:
            layout.addWidget(QLabel("无法计算像素差异"))
            return

        viewer = ImageViewer()
        viewer.set_image_array(result.diff_image)
        layout.addWidget(viewer, 1)

        info = QLabel(
            f"平均差异: {result.mean_diff}  |  最大差异: {result.max_diff}  |  "
            f"差异像素占比: {result.diff_percentage}%"
        )
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)

    def _load_ela(self, pa: str, pb: str):
        self._clear_layout(self._tab_ela)
        layout = self._tab_ela.layout()
        result = self._analyzer.ela_compare(pa, pb)
        if result is None:
            layout.addWidget(QLabel("无法执行 ELA 分析"))
            return

        splitter = QSplitter(Qt.Orientation.Horizontal)
        va = ImageViewer()
        va.set_image_array(result.ela_image_a)
        vb = ImageViewer()
        vb.set_image_array(result.ela_image_b)
        splitter.addWidget(va)
        splitter.addWidget(vb)
        layout.addWidget(splitter, 1)

        info = QLabel(f"JPEG 重压缩质量: {result.quality_used}  |  亮区域表示可能被编辑过的区域")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)

    def _load_noise(self, pa: str, pb: str):
        self._clear_layout(self._tab_noise)
        layout = self._tab_noise.layout()
        result = self._analyzer.noise_analysis(pa, pb)
        if result is None:
            layout.addWidget(QLabel("无法执行噪声分析"))
            return

        splitter = QSplitter(Qt.Orientation.Horizontal)
        va = ImageViewer()
        va.set_image_array(result.noise_image_a)
        vb = ImageViewer()
        vb.set_image_array(result.noise_image_b)
        splitter.addWidget(va)
        splitter.addWidget(vb)
        layout.addWidget(splitter, 1)

        info = QLabel(
            f"噪声水平 A: {result.noise_level_a}  |  噪声水平 B: {result.noise_level_b}  |  "
            f"差异越大越可能来自不同设备或经过处理"
        )
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)

    def _load_lighting(self, pa: str, pb: str):
        self._clear_layout(self._tab_lighting)
        layout = self._tab_lighting.layout()
        result = self._analyzer.lighting_analysis(pa, pb)
        if result is None:
            layout.addWidget(QLabel("无法执行光照分析"))
            return

        splitter = QSplitter(Qt.Orientation.Horizontal)
        va = ImageViewer()
        va.set_image_array(result.edges_a)
        vb = ImageViewer()
        vb.set_image_array(result.edges_b)
        splitter.addWidget(va)
        splitter.addWidget(vb)
        layout.addWidget(splitter, 1)

        info = QLabel(
            f"直方图相关性: {result.histogram_correlation}  |  "
            f"1.0 = 完全一致, 0.0 = 完全不同  |  边缘检测 (Canny)"
        )
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)
