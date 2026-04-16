"""Main application window — source selection, controls, scan worker."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..engine.cache import HashCache
from ..engine.feature import FeatureMatcher
from ..engine.hasher import DuplicateGroup, HashEngine
from ..engine.scanner import Scanner
from .forensic_dialog import ForensicDialog
from .results_view import ResultsView
from .widgets import ThresholdSlider


@dataclass
class ScanOptions:
    exact_match: bool = True
    perceptual: bool = True
    feature_match: bool = False
    perceptual_threshold: int = 10


class ScanWorker(QObject):
    """Runs the full scan pipeline in a background thread."""

    progress = pyqtSignal(str, int, int)  # stage, current, total
    finished = pyqtSignal(list)  # list[DuplicateGroup]
    error = pyqtSignal(str)

    def __init__(self, sources: list[str], options: ScanOptions):
        super().__init__()
        self._sources = sources
        self._options = options

    def run(self):
        try:
            scanner = Scanner()
            cache = HashCache()

            self.progress.emit("扫描文件...", 0, 0)
            files = scanner.scan(self._sources)
            if not files:
                self.finished.emit([])
                return

            self.progress.emit("计算哈希...", 0, len(files))
            hasher = HashEngine(cache)
            hashes = hasher.compute_hashes(
                files,
                progress_callback=lambda cur, tot: self.progress.emit("计算哈希...", cur, tot),
            )

            all_groups: list[DuplicateGroup] = []

            if self._options.exact_match:
                self.progress.emit("精准匹配...", 0, 0)
                exact = hasher.find_exact_duplicates(hashes)
                all_groups.extend(exact)

            if self._options.perceptual:
                self.progress.emit("感知哈希比较...", 0, 0)
                perceptual = hasher.find_perceptual_duplicates(
                    hashes, threshold=self._options.perceptual_threshold,
                )
                # Re-number group IDs to avoid collision
                offset = max((g.group_id for g in all_groups), default=0)
                for g in perceptual:
                    g.group_id += offset
                all_groups.extend(perceptual)

            if self._options.feature_match:
                self.progress.emit("ORB 特征匹配...", 0, 0)
                matcher = FeatureMatcher()
                feature_groups = matcher.compare_candidates(
                    hashes,
                    min_score=0.15,
                    progress_callback=lambda cur, tot: self.progress.emit("ORB 特征匹配...", cur, tot),
                )
                offset = max((g.group_id for g in all_groups), default=0)
                for g in feature_groups:
                    g.group_id += offset
                all_groups.extend(feature_groups)

            scanner.cleanup()
            self.finished.emit(all_groups)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ImageDedup — 图片查重工具")
        self.resize(1200, 800)

        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self._groups: list[DuplicateGroup] = []

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        main_layout.addWidget(splitter, 1)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        main_layout.addWidget(self._progress_bar)

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("就绪")

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Source list
        layout.addWidget(QLabel("图片来源:"))
        self._source_list = QListWidget()
        self._source_list.setMinimumWidth(250)
        layout.addWidget(self._source_list, 1)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_folder = QPushButton("添加文件夹")
        btn_files = QPushButton("添加文件")
        btn_archive = QPushButton("添加压缩包")
        btn_remove = QPushButton("移除")
        btn_folder.clicked.connect(self._add_folder)
        btn_files.clicked.connect(self._add_files)
        btn_archive.clicked.connect(self._add_archive)
        btn_remove.clicked.connect(self._remove_source)
        btn_layout.addWidget(btn_folder)
        btn_layout.addWidget(btn_files)
        btn_layout.addWidget(btn_archive)
        btn_layout.addWidget(btn_remove)
        layout.addLayout(btn_layout)

        # Detection methods
        method_group = QGroupBox("检测方法")
        method_layout = QVBoxLayout(method_group)
        self._chk_exact = QCheckBox("精准匹配 (MD5/SHA256)")
        self._chk_exact.setChecked(True)
        self._chk_perceptual = QCheckBox("感知哈希 (pHash)")
        self._chk_perceptual.setChecked(True)
        self._chk_feature = QCheckBox("特征匹配 (ORB)")
        method_layout.addWidget(self._chk_exact)
        method_layout.addWidget(self._chk_perceptual)
        method_layout.addWidget(self._chk_feature)

        self._threshold_slider = ThresholdSlider()
        method_layout.addWidget(self._threshold_slider)
        layout.addWidget(method_group)

        # Action buttons
        self._btn_scan = QPushButton("开始扫描")
        self._btn_scan.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-weight: bold; "
            "padding: 8px; border-radius: 4px; } "
            "QPushButton:hover { background-color: #45a049; } "
            "QPushButton:disabled { background-color: #ccc; }"
        )
        self._btn_scan.clicked.connect(self._on_scan)
        layout.addWidget(self._btn_scan)

        self._btn_report = QPushButton("生成 HTML 报告")
        self._btn_report.setEnabled(False)
        self._btn_report.clicked.connect(self._on_generate_report)
        layout.addWidget(self._btn_report)

        return panel

    def _build_right_panel(self) -> QWidget:
        self._results_view = ResultsView()
        self._results_view.group_double_clicked.connect(self._on_group_double_clicked)
        return self._results_view

    # --- Source management ---

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if path:
            self._source_list.addItem(path)

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片文件", "",
            "图片文件 (*.jpg *.jpeg *.png *.gif *.bmp *.webp *.tiff *.tif);;所有文件 (*)",
        )
        for p in paths:
            self._source_list.addItem(p)

    def _add_archive(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择压缩包", "",
            "ZIP 压缩包 (*.zip);;所有文件 (*)",
        )
        if path:
            self._source_list.addItem(path)

    def _remove_source(self):
        for item in self._source_list.selectedItems():
            self._source_list.takeItem(self._source_list.row(item))

    # --- Scan ---

    def _on_scan(self):
        sources = [self._source_list.item(i).text() for i in range(self._source_list.count())]
        if not sources:
            QMessageBox.warning(self, "提示", "请先添加图片来源")
            return

        options = ScanOptions(
            exact_match=self._chk_exact.isChecked(),
            perceptual=self._chk_perceptual.isChecked(),
            feature_match=self._chk_feature.isChecked(),
            perceptual_threshold=self._threshold_slider.value(),
        )

        self._set_scanning(True)
        self._results_view.clear()

        self._thread = QThread()
        self._worker = ScanWorker(sources, options)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_scan_finished)
        self._worker.error.connect(self._on_scan_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _set_scanning(self, scanning: bool):
        self._btn_scan.setEnabled(not scanning)
        self._btn_report.setEnabled(not scanning and bool(self._groups))
        self._progress_bar.setVisible(scanning)
        if scanning:
            self._progress_bar.setRange(0, 0)

    def _on_progress(self, stage: str, current: int, total: int):
        self._status.showMessage(f"{stage} {current}/{total}" if total else stage)
        if total > 0:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValue(current)
        else:
            self._progress_bar.setRange(0, 0)

    def _on_scan_finished(self, groups: list[DuplicateGroup]):
        self._groups = groups
        self._set_scanning(False)
        self._results_view.set_results(groups)
        self._btn_report.setEnabled(bool(groups))

        total_files = sum(len(g.files) for g in groups)
        self._status.showMessage(f"扫描完成 — 发现 {len(groups)} 组重复，涉及 {total_files} 个文件")

        if not groups:
            QMessageBox.information(self, "结果", "未发现重复图片")

    def _on_scan_error(self, msg: str):
        self._set_scanning(False)
        QMessageBox.critical(self, "扫描出错", msg)
        self._status.showMessage("扫描出错")

    # --- Forensic dialog ---

    def _on_group_double_clicked(self, group: DuplicateGroup):
        dlg = ForensicDialog(group, self)
        dlg.exec()

    # --- Report ---

    def _on_generate_report(self):
        if not self._groups:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 HTML 报告", "dedup_report.html",
            "HTML 文件 (*.html);;所有文件 (*)",
        )
        if not path:
            return

        from ..report.html_report import ReportGenerator

        try:
            gen = ReportGenerator()
            out = gen.generate(self._groups, path)
            QMessageBox.information(self, "报告已生成", f"报告已保存到:\n{out}")
            self._status.showMessage(f"报告已保存: {out}")
            # Open in browser
            import webbrowser
            webbrowser.open(f"file://{out}")
        except Exception as e:
            QMessageBox.critical(self, "生成报告失败", str(e))
