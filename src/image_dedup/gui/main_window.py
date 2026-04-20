"""Main application window — source selection, controls, scan worker."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig
from ..engine.cache import HashCache
from ..engine.errors import ScanErrors
from ..engine.feature import FeatureMatcher
from ..engine.hasher import DuplicateGroup, HashEngine
from ..engine.scanner import Scanner
from ..logging_setup import get_logger
from .forensic_dialog import ForensicDialog
from .image_viewer_dialog import ImageViewerDialog
from .results_view import ResultsView
from .tray import SystemTrayManager
from .widgets import DropTreeWidget, ThresholdSlider

logger = get_logger("main_window")


@dataclass
class ScanOptions:
    exact_match: bool = True
    perceptual: bool = True
    feature_match: bool = False
    perceptual_threshold: int = 10
    video_dedup: bool = False
    semantic: bool = False
    cross_doc: bool = False


class ScanWorker(QObject):
    """Runs the full scan pipeline in a background thread."""

    progress = pyqtSignal(str, int, int)  # stage, current, total
    finished = pyqtSignal(list, object, object, object)  # list[DuplicateGroup], Scanner, ScanErrors, delta_info
    error = pyqtSignal(str)

    def __init__(self, sources: list[str], options: ScanOptions, config: AppConfig | None = None):
        super().__init__()
        self._sources = sources
        self._options = options
        self._config = config or AppConfig()

    def run(self):
        try:
            scanner = Scanner()
            cache = HashCache()
            scan_errors = ScanErrors()

            # Start scan session
            scan_id = cache.start_scan(self._sources)

            self.progress.emit("扫描文件...", 0, 0)
            files = scanner.scan(self._sources, errors=scan_errors)
            if not files:
                scanner.cleanup()
                cache.finish_scan(scan_id, 0, 0)
                self.finished.emit([], scanner, scan_errors, None)
                return

            # Record files in scan session
            cache.record_scan_files_batch(scan_id, [(str(f.path), f.file_size, f.path.stat().st_mtime) for f in files])

            # Compute delta against last scan
            last_scan = cache.get_last_scan(self._sources)
            delta_info = None
            if last_scan:
                new, modified, deleted = cache.get_scan_delta(
                    last_scan["scan_id"],
                    [(str(f.path), f.file_size, f.path.stat().st_mtime) for f in files],
                )
                delta_info = {"new": len(new), "modified": len(modified), "deleted": len(deleted)}
                self.progress.emit(
                    f"增量扫描: {len(new)} 新增, {len(modified)} 修改, {len(deleted)} 删除",
                    0, 0,
                )

            # Cross-doc: flatten all files into global pool
            if self._options.cross_doc:
                for f in files:
                    f.source_group = None

            # Partition by source_group: None = global pool, else per-document
            global_files: list = []
            doc_groups: dict[str, list] = {}
            for f in files:
                if f.source_group is None:
                    global_files.append(f)
                else:
                    doc_groups.setdefault(f.source_group, []).append(f)

            all_groups: list[DuplicateGroup] = []
            gid_offset = 0

            # Process global pool
            if global_files:
                groups = self._run_dedup(global_files, cache, gid_offset, scan_errors)
                all_groups.extend(groups)
                gid_offset = max((g.group_id for g in all_groups), default=0)

            # Process each document independently
            for doc_path, doc_files in doc_groups.items():
                if len(doc_files) < 2:
                    continue
                groups = self._run_dedup(doc_files, cache, gid_offset, scan_errors)
                all_groups.extend(groups)
                gid_offset = max((g.group_id for g in all_groups), default=0)

            # --- Video dedup ---
            if self._options.video_dedup:
                self.progress.emit("视频查重...", 0, 0)
                try:
                    from ..engine.video import VideoProcessor, VIDEO_EXTENSIONS

                    processor = VideoProcessor(
                        interval=self._config.video_keyframe_interval,
                        config=self._config,
                    )

                    # Collect video files from sources
                    video_paths: list[str] = []
                    for src in self._sources:
                        p = Path(src)
                        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
                            video_paths.append(str(p))
                        elif p.is_dir():
                            for ext in VIDEO_EXTENSIONS:
                                video_paths.extend(str(vf) for vf in p.rglob(f"*{ext}"))

                    if len(video_paths) >= 2:
                        video_hashes = []
                        for idx, vp in enumerate(video_paths):
                            self.progress.emit("提取视频关键帧...", idx + 1, len(video_paths))
                            vh = processor.compute_video_hashes(vp)
                            if vh is not None:
                                video_hashes.append(vh)

                        if len(video_hashes) >= 2:
                            self.progress.emit("比对视频...", 0, 0)
                            video_groups = processor.find_similar_videos(
                                video_hashes,
                                threshold=self._config.video_phash_threshold,
                            )
                            offset = max((g.group_id for g in all_groups), default=0)
                            for g in video_groups:
                                g.group_id += offset
                            all_groups.extend(video_groups)
                except Exception as e:
                    logger.warning(f"视频查重失败: {e}")

            # --- AI semantic similarity ---
            if self._options.semantic:
                self.progress.emit("AI 语义分析...", 0, 0)
                try:
                    from ..engine.semantic import SemanticEngine

                    engine = SemanticEngine(
                        model_name=self._config.semantic_model,
                        device="cuda" if self._config.gpu_acceleration else "cpu",
                    )

                    image_paths = [str(f.path) for f in files]
                    embeddings = engine.compute_embeddings_batch(
                        image_paths,
                        progress_callback=lambda cur, tot: self.progress.emit("AI 语义嵌入...", cur, tot),
                    )

                    if len(embeddings) >= 2:
                        self.progress.emit("语义相似度比对...", 0, 0)
                        semantic_groups = engine.find_semantic_duplicates(
                            embeddings,
                            threshold=self._config.semantic_threshold,
                        )
                        offset = max((g.group_id for g in all_groups), default=0)
                        for g in semantic_groups:
                            g.group_id += offset
                        all_groups.extend(semantic_groups)
                except Exception as e:
                    logger.warning(f"AI 语义分析失败: {e}")

            total_files = sum(len(g.files) for g in all_groups)
            cache.finish_scan(scan_id, total_files, len(all_groups))

            # Don't cleanup — MainWindow holds scanner alive until next scan / close
            self.finished.emit(all_groups, scanner, scan_errors, delta_info)
        except Exception as e:
            logger.exception("Scan failed")
            self.error.emit(str(e))

    def _run_dedup(self, files, cache, gid_offset, scan_errors=None) -> list[DuplicateGroup]:
        hasher = HashEngine(cache, max_workers=self._config.max_workers, config=self._config)
        hashes = hasher.compute_hashes(
            files,
            progress_callback=lambda cur, tot: self.progress.emit("计算哈希...", cur, tot),
            errors=scan_errors,
        )

        groups: list[DuplicateGroup] = []

        if self._options.exact_match:
            self.progress.emit("精准匹配...", 0, 0)
            exact = hasher.find_exact_duplicates(hashes)
            for g in exact:
                g.group_id += gid_offset
            groups.extend(exact)

        if self._options.perceptual:
            self.progress.emit("感知哈希比较...", 0, 0)
            perceptual = hasher.find_perceptual_duplicates(
                hashes, threshold=self._options.perceptual_threshold,
            )
            offset = max((g.group_id for g in groups), default=gid_offset)
            for g in perceptual:
                g.group_id += offset
            groups.extend(perceptual)

        if self._options.feature_match:
            self.progress.emit("ORB 特征匹配...", 0, 0)
            matcher = FeatureMatcher(
                n_features=self._config.orb_n_features,
                ratio_threshold=self._config.orb_ratio_threshold,
                max_dim=self._config.feature_max_dim,
            )
            feature_groups = matcher.compare_candidates(
                hashes,
                min_score=self._config.feature_min_score,
                progress_callback=lambda cur, tot: self.progress.emit("ORB 特征匹配...", cur, tot),
            )
            offset = max((g.group_id for g in groups), default=gid_offset)
            for g in feature_groups:
                g.group_id += offset
            groups.extend(feature_groups)

        return groups


def _format_eta(seconds: float) -> str:
    """Format seconds into Chinese time string like '1分23秒' or '45秒'."""
    seconds = max(0, int(seconds))
    if seconds >= 60:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}分{secs}秒"
    return f"{seconds}秒"


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig | None = None):
        super().__init__()
        self._config = config or AppConfig()
        self.setWindowTitle("ImageDedup — 图片查重工具")
        self.resize(1200, 800)

        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self._groups: list[DuplicateGroup] = []
        self._scanner: Scanner | None = None  # Keep scanner alive for temp files
        self._scan_start_time: float | None = None

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

        # System tray
        self._tray_manager = SystemTrayManager(self, self._config)
        self._tray_manager.setup_tray()

        if self._config.file_watcher_enabled and self._config.file_watcher_paths:
            self._tray_manager.setup_file_watcher(self._config.file_watcher_paths)

        if self._config.scheduled_scan_enabled and self._config.scheduled_scan_paths:
            self._tray_manager.setup_scheduled_scan(
                self._config.scheduled_scan_interval_min,
                self._config.scheduled_scan_paths,
            )

        self._tray_manager.scan_requested.connect(self._on_tray_scan_requested)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Source list
        layout.addWidget(QLabel("图片来源:"))
        self._source_list = DropTreeWidget()
        self._source_list.setMinimumWidth(250)
        layout.addWidget(self._source_list, 1)
        # Load previously extracted archives on startup
        self._source_list.load_existing_extracted()

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
        self._chk_video = QCheckBox("视频查重")
        self._chk_semantic = QCheckBox("AI 语义相似度")
        self._chk_cross_doc = QCheckBox("跨文档查重")
        method_layout.addWidget(self._chk_exact)
        method_layout.addWidget(self._chk_perceptual)
        method_layout.addWidget(self._chk_feature)
        method_layout.addWidget(self._chk_video)
        method_layout.addWidget(self._chk_semantic)
        method_layout.addWidget(self._chk_cross_doc)

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

        # Report dropdown button
        self._btn_report = QPushButton("导出报告 ▾")
        self._btn_report.setEnabled(False)
        report_menu = QMenu(self._btn_report)
        report_menu.addAction("导出 HTML 报告", self._on_generate_html_report)
        report_menu.addAction("导出 Excel 报告", self._on_generate_excel_report)
        report_menu.addAction("导出 PDF 报告", self._on_generate_pdf_report)
        self._btn_report.setMenu(report_menu)
        layout.addWidget(self._btn_report)

        self._btn_settings = QPushButton("设置")
        self._btn_settings.clicked.connect(self._on_settings)
        layout.addWidget(self._btn_settings)

        return panel

    def _build_right_panel(self) -> QWidget:
        self._results_view = ResultsView()
        self._results_view.group_double_clicked.connect(self._on_group_double_clicked)
        self._results_view.file_double_clicked.connect(self._on_file_double_clicked)
        return self._results_view

    # --- Source management ---

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if path:
            self._source_list.add_folder(Path(path))

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片文件", "",
            "图片文件 (*.jpg *.jpeg *.png *.gif *.bmp *.webp *.tiff *.tif);;"
            "文档文件 (*.xlsx *.xls *.pdf);;所有文件 (*)",
        )
        for p in paths:
            self._source_list.add_file(Path(p))

    def _add_archive(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择压缩包", "",
            "压缩包 (*.zip *.rar *.7z *.tar *.gz *.bz2 *.tgz);;所有文件 (*)",
        )
        if path:
            self._source_list.add_archive(Path(path))

    def _remove_source(self):
        for item in self._source_list.selectedItems():
            parent = item.parent()
            if parent:
                parent.removeChild(item)
            else:
                idx = self._source_list.indexOfTopLevelItem(item)
                if idx >= 0:
                    self._source_list.takeTopLevelItem(idx)

    # --- Scan ---

    def _on_scan(self):
        sources = self._source_list.get_checked_paths()
        if not sources:
            QMessageBox.warning(self, "提示", "请先添加图片来源")
            return

        options = ScanOptions(
            exact_match=self._chk_exact.isChecked(),
            perceptual=self._chk_perceptual.isChecked(),
            feature_match=self._chk_feature.isChecked(),
            perceptual_threshold=self._threshold_slider.value(),
            video_dedup=self._chk_video.isChecked(),
            semantic=self._chk_semantic.isChecked(),
            cross_doc=self._chk_cross_doc.isChecked(),
        )

        self._scan_start_time = time.monotonic()
        self._set_scanning(True)
        self._results_view.clear()

        self._thread = QThread()
        self._worker = ScanWorker(sources, options, self._config)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_scan_finished)
        self._worker.error.connect(self._on_scan_error)
        self._worker.finished.connect(lambda *_: self._thread.quit())
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _on_tray_scan_requested(self, paths: list[str]):
        """Handle scan request from system tray."""
        if paths:
            for p in paths:
                pp = Path(p)
                if pp.is_dir():
                    self._source_list.add_folder(pp)
                elif pp.is_file():
                    self._source_list.add_file(pp)
        self._on_scan()

    def _set_scanning(self, scanning: bool):
        self._btn_scan.setEnabled(not scanning)
        self._btn_report.setEnabled(not scanning and bool(self._groups))
        self._progress_bar.setVisible(scanning)
        if scanning:
            self._progress_bar.setRange(0, 0)

    def _on_progress(self, stage: str, current: int, total: int):
        if total > 0:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValue(current)

            pct = int(current * 100 / total) if total else 0
            msg = f"{stage} {current}/{total} ({pct}%)"

            # ETA calculation
            if current > 0 and self._scan_start_time is not None:
                elapsed = time.monotonic() - self._scan_start_time
                remaining = (elapsed / current) * (total - current)
                msg += f" — 预计剩余 {_format_eta(remaining)}"

            self._status.showMessage(msg)
        else:
            self._progress_bar.setRange(0, 0)
            self._status.showMessage(stage)

    def _on_scan_finished(self, groups: list[DuplicateGroup], scanner: Scanner, scan_errors: ScanErrors, delta_info):
        # Clean up previous scanner's temp files, keep new one alive
        if self._scanner is not None:
            self._scanner.cleanup()
        self._scanner = scanner

        self._groups = groups
        self._scan_start_time = None
        self._set_scanning(False)
        self._results_view.set_results(groups)
        self._btn_report.setEnabled(bool(groups))

        total_files = sum(len(g.files) for g in groups)
        msg = f"扫描完成 — 发现 {len(groups)} 组重复，涉及 {total_files} 个文件"
        if delta_info:
            msg += f" (新增 {delta_info['new']}, 修改 {delta_info['modified']}, 删除 {delta_info['deleted']})"
        self._status.showMessage(msg)

        if scan_errors and scan_errors.count > 0:
            QMessageBox.warning(
                self, "扫描警告",
                f"扫描完成，但有 {scan_errors.count} 个文件处理失败。\n详情请查看日志文件。",
            )

        if not groups:
            QMessageBox.information(self, "结果", "未发现重复图片")

    def _on_scan_error(self, msg: str):
        self._scan_start_time = None
        self._set_scanning(False)
        QMessageBox.critical(self, "扫描出错", msg)
        self._status.showMessage("扫描出错")

    # --- Forensic dialog ---

    def _on_settings(self):
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self._config, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._config = dlg.config
            self._threshold_slider.setValue(self._config.perceptual_threshold)

    def _on_group_double_clicked(self, group: DuplicateGroup):
        dlg = ForensicDialog(group, self, config=self._config)
        dlg.exec()

    def _on_file_double_clicked(self, file_path: str, group: DuplicateGroup):
        dlg = ImageViewerDialog(file_path, group, self, config=self._config)
        dlg.exec()

    def closeEvent(self, event):
        if self._config.minimize_to_tray:
            event.ignore()
            self.hide()
            return
        if self._scanner is not None:
            self._scanner.cleanup()
            self._scanner = None
        super().closeEvent(event)

    # --- Reports ---

    def _on_generate_html_report(self):
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
            import webbrowser
            webbrowser.open(f"file://{out}")
        except Exception as e:
            QMessageBox.critical(self, "生成报告失败", str(e))

    def _on_generate_excel_report(self):
        if not self._groups:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 Excel 报告", "dedup_report.xlsx",
            "Excel 文件 (*.xlsx);;所有文件 (*)",
        )
        if not path:
            return

        from ..report.excel_report import ExcelReportGenerator

        try:
            gen = ExcelReportGenerator()
            out = gen.generate(self._groups, path)
            QMessageBox.information(self, "报告已生成", f"报告已保存到:\n{out}")
            self._status.showMessage(f"报告已保存: {out}")
        except Exception as e:
            QMessageBox.critical(self, "生成报告失败", str(e))

    def _on_generate_pdf_report(self):
        if not self._groups:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 PDF 报告", "dedup_report.pdf",
            "PDF 文件 (*.pdf);;所有文件 (*)",
        )
        if not path:
            return

        from ..report.pdf_report import PDFReportGenerator

        try:
            gen = PDFReportGenerator()
            out = gen.generate(self._groups, path)
            QMessageBox.information(self, "报告已生成", f"报告已保存到:\n{out}")
            self._status.showMessage(f"报告已保存: {out}")
        except Exception as e:
            QMessageBox.critical(self, "生成报告失败", str(e))
