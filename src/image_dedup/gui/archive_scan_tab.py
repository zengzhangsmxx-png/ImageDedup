"""压缩包扫描标签页 — 批量扫描压缩包内图片查重。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig
from ..engine.archive_scanner import ArchiveScanner
from ..engine.hasher import DuplicateGroup
from ..logging_setup import get_logger

logger = get_logger("archive_scan_tab")

_METHOD_LABELS = {
    "exact": "精准匹配 (MD5)",
    "perceptual": "感知哈希",
    "feature": "特征匹配 (ORB)",
}


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class ArchiveScanWorker(QObject):
    """在 QThread 中逐个扫描压缩包队列。"""

    progress = pyqtSignal(str, int, int)          # archive_path, current, total
    archive_finished = pyqtSignal(str, list, int, object)  # archive_path, groups, total_files, temp_handle
    all_finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, queue: list[str], config: AppConfig | None = None):
        super().__init__()
        self._queue = list(queue)
        self._config = config or AppConfig()
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        scanner = ArchiveScanner(self._config)
        total = len(self._queue)
        for idx, archive_path in enumerate(self._queue):
            if self._stopped:
                break
            try:
                self.progress.emit(archive_path, idx + 1, total)
                groups, total_files, temp_handle = scanner.scan_archive(archive_path, keep_temp=True)
                self.archive_finished.emit(archive_path, groups, total_files, temp_handle)
            except MemoryError:
                logger.error("内存不足，跳过压缩包: %s", archive_path)
                self.error.emit(f"{Path(archive_path).name}: 内存不足，文件过大无法处理")
                # 强制触发垃圾回收，尝试释放内存
                import gc
                gc.collect()
            except Exception as exc:
                logger.exception("扫描压缩包失败: %s", archive_path)
                self.error.emit(f"{Path(archive_path).name}: {exc}")
        if not self._stopped:
            self.all_finished.emit()


# ---------------------------------------------------------------------------
# Tab widget
# ---------------------------------------------------------------------------

class ArchiveScanTab(QWidget):
    """压缩包批量扫描标签页。"""

    group_double_clicked = pyqtSignal(object)       # DuplicateGroup
    file_double_clicked = pyqtSignal(str, object)   # file_path, DuplicateGroup

    def __init__(self, config: AppConfig | None = None, parent=None):
        super().__init__(parent)
        self._config = config or AppConfig()
        self._scanner = ArchiveScanner(self._config)
        self._worker: Optional[ArchiveScanWorker] = None
        self._thread: Optional[QThread] = None

        # archive_path -> (groups, total_files)
        self._results: dict[str, tuple[list[DuplicateGroup], int]] = {}
        self._temp_handles: dict[str, object] = {}  # archive_path -> TemporaryDirectory
        self._current_archive: Optional[str] = None

        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        # ---- left panel ----
        left = QWidget()
        left.setFixedWidth(350)
        left_layout = QVBoxLayout(left)

        # 扫描路径
        path_group = QGroupBox("扫描路径")
        path_layout = QVBoxLayout(path_group)

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("选择包含压缩包的文件夹...")
        path_row.addWidget(self._path_edit, 1)
        btn_browse = QPushButton("浏览")
        btn_browse.clicked.connect(self._on_browse)
        path_row.addWidget(btn_browse)
        path_layout.addLayout(path_row)

        self._btn_scan_today = QPushButton("扫描当日新增")
        self._btn_scan_today.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #43A047; }"
            "QPushButton:pressed { background-color: #388E3C; }"
        )
        self._btn_scan_today.clicked.connect(self._on_scan_today)
        path_layout.addWidget(self._btn_scan_today)

        self._btn_add_archive = QPushButton("添加压缩包")
        self._btn_add_archive.clicked.connect(self._on_add_archive)
        path_layout.addWidget(self._btn_add_archive)

        left_layout.addWidget(path_group)

        # 扫描队列
        queue_group = QGroupBox("扫描队列")
        queue_layout = QVBoxLayout(queue_group)

        self._queue_tree = QTreeWidget()
        self._queue_tree.setHeaderLabels(["文件名", "状态", "重复数"])
        self._queue_tree.setColumnCount(3)
        self._queue_tree.setAlternatingRowColors(True)
        self._queue_tree.setRootIsDecorated(False)
        self._queue_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._queue_tree.customContextMenuRequested.connect(self._on_queue_context_menu)
        header = self._queue_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._queue_tree.itemClicked.connect(self._on_queue_item_clicked)
        queue_layout.addWidget(self._queue_tree)

        btn_row = QHBoxLayout()
        self._btn_scan_all = QPushButton("全部扫描")
        self._btn_scan_all.clicked.connect(self._on_scan_all)
        btn_row.addWidget(self._btn_scan_all)
        self._btn_stop = QPushButton("停止扫描")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop_scan)
        btn_row.addWidget(self._btn_stop)
        queue_layout.addLayout(btn_row)

        left_layout.addWidget(queue_group, 1)
        splitter.addWidget(left)

        # ---- right panel ----
        right = QWidget()
        right_layout = QVBoxLayout(right)

        # toolbar
        toolbar = QHBoxLayout()
        self._btn_select_dupes = QPushButton("全选重复项")
        self._btn_select_dupes.clicked.connect(self._on_select_duplicates)
        toolbar.addWidget(self._btn_select_dupes)

        self._btn_delete = QPushButton("删除选中")
        self._btn_delete.setStyleSheet("color: #d32f2f;")
        self._btn_delete.clicked.connect(self._on_delete_selected)
        toolbar.addWidget(self._btn_delete)

        self._btn_save_as = QPushButton("另存为...")
        self._btn_save_as.clicked.connect(self._on_save_as)
        toolbar.addWidget(self._btn_save_as)

        self._btn_report = QPushButton("保存报告")
        report_menu = QMenu(self)
        report_menu.addAction("当前报告", self._on_save_report)
        report_menu.addAction("批量保存所有报告", self._on_save_all_reports)
        self._btn_report.setMenu(report_menu)
        toolbar.addWidget(self._btn_report)

        toolbar.addStretch()
        right_layout.addLayout(toolbar)

        # results tree
        self._result_tree = QTreeWidget()
        self._result_tree.setHeaderLabels(["组/文件", "相似度", "大小", "尺寸"])
        self._result_tree.setColumnCount(4)
        self._result_tree.setAlternatingRowColors(True)
        self._result_tree.setRootIsDecorated(True)
        self._result_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self._result_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._result_tree.customContextMenuRequested.connect(self._on_result_context_menu)
        rh = self._result_tree.header()
        rh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            rh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._result_tree.itemDoubleClicked.connect(self._on_result_double_click)
        right_layout.addWidget(self._result_tree, 1)

        # progress bar (hidden)
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        right_layout.addWidget(self._progress)

        # overall progress percentage
        self._overall_progress_label = QLabel("整体进度: 0%")
        self._overall_progress_label.setStyleSheet(
            "color: #4CAF50; font-weight: bold; padding: 4px; font-size: 14px;"
        )
        self._overall_progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._overall_progress_label.setVisible(False)
        right_layout.addWidget(self._overall_progress_label)

        # status label
        self._status = QLabel("就绪")
        self._status.setStyleSheet("color: #666; padding: 4px;")
        right_layout.addWidget(self._status)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

    # --------------------------------------------------------- left actions

    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            self._path_edit.setText(folder)

    def _on_scan_today(self):
        folder = self._path_edit.text().strip()
        if not folder or not Path(folder).is_dir():
            QMessageBox.warning(self, "提示", "请先选择一个有效的文件夹路径")
            return
        items = self._scanner.get_today_new_archives(folder)
        if not items:
            QMessageBox.information(self, "提示", "今日没有新增的文件或文件夹")
            return
        added = 0
        for item in items:
            item_str = str(item)
            if not self._queue_contains(item_str):
                self._add_queue_item(item_str)
                added += 1
        self._status.setText(f"已添加 {added} 个今日新增对象")

    def _on_add_archive(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择压缩包",
            self._path_edit.text() or "",
            "压缩包 (*.zip *.rar *.7z *.tar *.tar.gz *.tar.bz2 *.tgz *.gz *.bz2)",
        )
        for f in files:
            if not self._queue_contains(f):
                self._add_queue_item(f)

    def _add_queue_item(self, archive_path: str):
        item = QTreeWidgetItem([Path(archive_path).name, "待扫描", ""])
        item.setToolTip(0, archive_path)
        item.setData(0, Qt.ItemDataRole.UserRole, archive_path)
        self._queue_tree.addTopLevelItem(item)

    def _queue_contains(self, archive_path: str) -> bool:
        for i in range(self._queue_tree.topLevelItemCount()):
            if self._queue_tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == archive_path:
                return True
        return False

    def _get_queue_paths(self) -> list[str]:
        paths = []
        for i in range(self._queue_tree.topLevelItemCount()):
            item = self._queue_tree.topLevelItem(i)
            if item.text(1) == "待扫描":
                paths.append(item.data(0, Qt.ItemDataRole.UserRole))
        return paths

    # --------------------------------------------------------- queue context menu

    def _on_queue_context_menu(self, pos):
        item = self._queue_tree.itemAt(pos)
        if not item:
            return

        archive_path = item.data(0, Qt.ItemDataRole.UserRole)
        status = item.text(1)

        menu = QMenu(self)

        if status in ("完成", "完成 \u26a0") and archive_path in self._results:
            save_action = menu.addAction("保存报告")
            save_action.triggered.connect(lambda checked, p=archive_path: self._save_single_report(p))

            delete_action = menu.addAction("删除任务")
            delete_action.triggered.connect(lambda checked, p=archive_path: self._delete_queue_item(p))

        remove_action = menu.addAction("从队列移除")
        remove_action.triggered.connect(lambda checked, p=archive_path: self._remove_from_queue(p))

        menu.exec(self._queue_tree.viewport().mapToGlobal(pos))

    def _save_single_report(self, archive_path: str):
        if archive_path not in self._results:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "保存报告",
            str(Path(archive_path).stem + "_report.html"),
            "HTML 报告 (*.html)",
        )
        if dest:
            groups, total_files = self._results[archive_path]
            self._write_report(dest, archive_path, groups, total_files)
            self._status.setText(f"报告已保存: {dest}")

    def _delete_queue_item(self, archive_path: str):
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除任务 {Path(archive_path).name} 吗？\n扫描结果将被清除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if archive_path in self._results:
            del self._results[archive_path]

        self._cleanup_temp(archive_path)
        self._remove_from_queue(archive_path)

        if self._current_archive == archive_path:
            self._current_archive = None
            self._result_tree.clear()

        self._status.setText(f"已删除任务: {Path(archive_path).name}")

    def _remove_from_queue(self, archive_path: str):
        for i in range(self._queue_tree.topLevelItemCount()):
            item = self._queue_tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == archive_path:
                self._queue_tree.takeTopLevelItem(i)
                break

    # --------------------------------------------------------- scanning

    def _on_scan_all(self):
        queue = self._get_queue_paths()
        if not queue:
            QMessageBox.information(self, "提示", "扫描队列为空，请先添加压缩包")
            return

        self._btn_scan_all.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._progress.setVisible(True)
        self._progress.setRange(0, len(queue))
        self._progress.setValue(0)
        self._overall_progress_label.setVisible(True)
        self._overall_progress_label.setText("整体进度: 0%")

        self._thread = QThread()
        self._worker = ArchiveScanWorker(queue, self._config)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.archive_finished.connect(self._on_archive_scanned)
        self._worker.all_finished.connect(self._on_all_finished)
        self._worker.error.connect(self._on_worker_error)

        self._thread.start()

    def _on_stop_scan(self):
        if self._worker:
            self._worker.stop()
        self._cleanup_thread()
        self._status.setText("扫描已停止")

    def _cleanup_thread(self):
        self._btn_scan_all.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._progress.setVisible(False)
        self._overall_progress_label.setVisible(False)
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            if not self._thread.wait(5000):
                logger.warning("Archive scan thread did not quit in time, terminating")
                self._thread.terminate()
                self._thread.wait()
        self._thread = None
        self._worker = None

    def _on_worker_progress(self, archive_path: str, current: int, total: int):
        self._progress.setValue(current)
        pct = int((current / total) * 100) if total > 0 else 0
        self._overall_progress_label.setText(f"整体进度: {pct}%")
        self._status.setText(f"正在扫描 ({current}/{total}): {Path(archive_path).name}")
        # mark queue item
        for i in range(self._queue_tree.topLevelItemCount()):
            item = self._queue_tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == archive_path:
                item.setText(1, "扫描中...")
                break

    def _on_archive_scanned(self, archive_path: str, groups: list, total_files: int, temp_handle: object):
        self._results[archive_path] = (groups, total_files)
        if temp_handle is not None:
            self._temp_handles[archive_path] = temp_handle
        high = self._check_high_similarity(groups, total_files)

        # update queue item
        dup_count = sum(len(g.files) for g in groups)
        for i in range(self._queue_tree.topLevelItemCount()):
            item = self._queue_tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == archive_path:
                if high:
                    item.setText(1, "完成 \u26a0")
                    item.setForeground(1, Qt.GlobalColor.red)
                else:
                    item.setText(1, "完成")
                item.setText(2, str(dup_count) if dup_count else "0")
                break

        # auto-show if this is the selected item or first result
        if self._current_archive == archive_path or self._current_archive is None:
            self._current_archive = archive_path
            self._populate_results(groups)

    def _on_all_finished(self):
        self._cleanup_thread()
        total_archives = len(self._results)
        total_groups = sum(len(gs) for gs, _ in self._results.values())
        self._status.setText(f"扫描完成 — {total_archives} 个压缩包, {total_groups} 组重复")

    def _on_worker_error(self, msg: str):
        logger.error("扫描错误: %s", msg)
        self._status.setText(f"错误: {msg}")

    def stop_and_cleanup(self):
        """停止扫描并清理资源，由 MainWindow 关闭时调用。"""
        if self._worker:
            self._worker.stop()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            if not self._thread.wait(5000):
                logger.warning("Archive scan thread did not stop gracefully, terminating")
                self._thread.terminate()
                self._thread.wait()
        self._thread = None
        self._worker = None
        self._cleanup_all_temps()

    def _cleanup_temp(self, archive_path: str):
        """清理单个压缩包的临时目录。"""
        handle = self._temp_handles.pop(archive_path, None)
        if handle is not None:
            try:
                handle.cleanup()
            except Exception as e:
                logger.debug("临时目录清理失败: %s", e)

    def _cleanup_all_temps(self):
        """清理所有临时目录。"""
        for handle in self._temp_handles.values():
            try:
                handle.cleanup()
            except Exception as e:
                logger.debug("临时目录清理失败: %s", e)
        self._temp_handles.clear()

    # --------------------------------------------------------- results

    def _on_queue_item_clicked(self, item: QTreeWidgetItem, column: int):
        archive_path = item.data(0, Qt.ItemDataRole.UserRole)
        if archive_path and archive_path in self._results:
            self._current_archive = archive_path
            groups, _ = self._results[archive_path]
            self._populate_results(groups)

    def _populate_results(self, groups: list[DuplicateGroup]):
        self._result_tree.setSortingEnabled(False)
        self._result_tree.clear()

        _SORT_ROLE = Qt.ItemDataRole.UserRole + 1

        for g in groups:
            method_label = _METHOD_LABELS.get(g.detection_method, g.detection_method)
            if hasattr(g, "multi_account") and g.multi_account:
                method_label += " [一机多号截图]"
            sim_text = f"{g.similarity_score * 100:.1f}%"

            group_item = QTreeWidgetItem([
                f"重复组 #{g.group_id} ({len(g.files)} 个文件) — {method_label}",
                sim_text,
                "",
                "",
            ])
            group_item.setData(0, Qt.ItemDataRole.UserRole, g)
            group_item.setData(1, _SORT_ROLE, g.similarity_score)

            # thumbnail from first file
            if g.files:
                pm = QPixmap(g.files[0].file_path)
                if not pm.isNull():
                    icon = QIcon(pm.scaled(
                        48, 48,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
                    group_item.setIcon(0, icon)

            for f in g.files:
                name = Path(f.file_path).name
                child = QTreeWidgetItem([
                    name,
                    "",
                    _human_size(f.file_size),
                    f"{f.width}x{f.height}",
                ])
                child.setToolTip(0, f.file_path)
                child.setData(0, Qt.ItemDataRole.UserRole, g)
                child.setCheckState(0, Qt.CheckState.Unchecked)
                child.setData(2, _SORT_ROLE, f.file_size)

                pm = QPixmap(f.file_path)
                if not pm.isNull():
                    icon = QIcon(pm.scaled(
                        32, 32,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
                    child.setIcon(0, icon)

                group_item.addChild(child)

            self._result_tree.addTopLevelItem(group_item)

        self._result_tree.setSortingEnabled(True)
        self._result_tree.expandAll()

    def _on_result_double_click(self, item: QTreeWidgetItem, column: int):
        group = item.data(0, Qt.ItemDataRole.UserRole)
        if not group or not isinstance(group, DuplicateGroup):
            return
        if item.parent() is None:
            # group item → forensic dialog
            if len(group.files) >= 2:
                self.group_double_clicked.emit(group)
        else:
            # file item → image viewer
            file_path = item.toolTip(0)
            if file_path:
                self.file_double_clicked.emit(file_path, group)

    def _on_result_context_menu(self, pos):
        item = self._result_tree.itemAt(pos)
        if not item or item.parent() is None:
            return
        file_path = item.toolTip(0)
        if not file_path:
            return

        menu = QMenu(self)

        # 文件定位菜单项
        action_reveal = menu.addAction("在 Finder 中显示")
        action_open = menu.addAction("打开文件")
        action_copy_path = menu.addAction("复制文件路径")

        # 如果当前有压缩包上下文，添加定位压缩包选项
        if self._current_archive:
            action_reveal_archive = menu.addAction("打开压缩包所在文件夹")
        else:
            action_reveal_archive = None

        menu.addSeparator()
        action_delete = menu.addAction("删除此图片")

        chosen = menu.exec(self._result_tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        if chosen == action_reveal:
            self._reveal_in_finder(file_path)
        elif chosen == action_open:
            self._open_file(file_path)
        elif chosen == action_copy_path:
            self._copy_path_to_clipboard(file_path)
        elif action_reveal_archive and chosen == action_reveal_archive:
            self._reveal_in_finder(self._current_archive)
        elif chosen == action_delete:
            self._delete_single_file(file_path, item)

    def _delete_single_file(self, file_path: str, item: QTreeWidgetItem):
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除 {Path(file_path).name} 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            Path(file_path).unlink(missing_ok=True)
        except Exception as exc:
            QMessageBox.critical(self, "删除失败", f"无法删除文件:\n{exc}")
            return

        if not self._current_archive or self._current_archive not in self._results:
            return

        groups, total_files = self._results[self._current_archive]
        for g in groups:
            g.files = [f for f in g.files if f.file_path != file_path]
        groups = [g for g in groups if len(g.files) >= 2]
        self._results[self._current_archive] = (groups, max(0, total_files - 1))
        self._populate_results(groups)

        # update queue item duplicate count
        dup_count = sum(len(g.files) for g in groups)
        for i in range(self._queue_tree.topLevelItemCount()):
            qi = self._queue_tree.topLevelItem(i)
            if qi.data(0, Qt.ItemDataRole.UserRole) == self._current_archive:
                qi.setText(2, str(dup_count) if dup_count else "0")
                break

        self._status.setText(f"已删除: {Path(file_path).name}")

    # --- File location helpers ---

    @staticmethod
    def _reveal_in_finder(file_path: str):
        """在 Finder 中显示并选中文件。"""
        try:
            subprocess.Popen(["open", "-R", file_path])
        except Exception as e:
            QMessageBox.warning(None, "打开失败", f"无法在 Finder 中显示文件:\n{e}")

    @staticmethod
    def _open_file(file_path: str):
        """使用系统默认程序打开文件。"""
        try:
            subprocess.Popen(["open", file_path])
        except Exception as e:
            QMessageBox.warning(None, "打开失败", f"无法打开文件:\n{e}")

    @staticmethod
    def _copy_path_to_clipboard(file_path: str):
        """复制文件路径到剪贴板。"""
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(file_path)

    # --------------------------------------------------------- toolbar actions

    def _on_select_duplicates(self):
        """每组保留最优文件，勾选其余副本。"""
        marked = 0
        for i in range(self._result_tree.topLevelItemCount()):
            group_item = self._result_tree.topLevelItem(i)
            group = group_item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(group, DuplicateGroup) or len(group.files) < 2:
                continue
            best = self._pick_best(group)
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                if child.toolTip(0) == best.file_path:
                    child.setCheckState(0, Qt.CheckState.Unchecked)
                else:
                    child.setCheckState(0, Qt.CheckState.Checked)
                    marked += 1
        self._status.setText(f"已选中 {marked} 个副本文件")

    def _pick_best(self, group: DuplicateGroup):
        best = group.files[0]
        for f in group.files[1:]:
            f_px = (f.width or 0) * (f.height or 0)
            b_px = (best.width or 0) * (best.height or 0)
            if f_px > b_px:
                best = f
            elif f_px == b_px and f.file_size > best.file_size:
                best = f
        return best

    def _get_checked_files(self) -> list[str]:
        checked: list[str] = []
        for i in range(self._result_tree.topLevelItemCount()):
            group_item = self._result_tree.topLevelItem(i)
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    path = child.toolTip(0)
                    if path:
                        checked.append(path)
        return checked

    def _on_delete_selected(self):
        files = self._get_checked_files()
        if not files:
            QMessageBox.information(self, "提示", "请先勾选要删除的文件")
            return

        preview = "\n".join(Path(f).name for f in files[:10])
        if len(files) > 10:
            preview += f"\n... 等共 {len(files)} 个文件"

        reply = QMessageBox.warning(
            self, "确认删除",
            f"确定要从压缩包中移除 {len(files)} 个文件吗？\n\n{preview}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if not self._current_archive:
            return

        try:
            removed = self._scanner.remove_files_from_archive(self._current_archive, files)
            # refresh results
            if self._current_archive in self._results:
                groups, total_files = self._results[self._current_archive]
                # remove deleted files from groups
                for g in groups:
                    g.files = [f for f in g.files if f.file_path not in files]
                groups = [g for g in groups if len(g.files) >= 2]
                self._results[self._current_archive] = (groups, total_files - removed)
                self._populate_results(groups)
            self._status.setText(f"已从压缩包中移除 {removed} 个文件")
        except Exception as exc:
            QMessageBox.critical(self, "删除失败", f"操作失败:\n{exc}")

    def _on_save_as(self):
        if not self._current_archive:
            QMessageBox.information(self, "提示", "请先选择一个压缩包")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "另存为",
            str(Path(self._current_archive).with_suffix(".zip")),
            "ZIP 压缩包 (*.zip);;所有文件 (*)",
        )
        if not dest:
            return
        try:
            self._scanner.save_archive_as(self._current_archive, dest)
            self._status.setText(f"已保存到: {dest}")
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", f"操作失败:\n{exc}")

    # --------------------------------------------------------- reports

    def _on_save_report(self):
        if not self._current_archive or self._current_archive not in self._results:
            QMessageBox.information(self, "提示", "当前没有可保存的报告")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "保存报告",
            str(Path(self._current_archive).stem + "_report.html"),
            "HTML 报告 (*.html)",
        )
        if dest:
            groups, total_files = self._results[self._current_archive]
            self._write_report(dest, self._current_archive, groups, total_files)
            self._status.setText(f"报告已保存: {dest}")

    def _on_save_all_reports(self):
        if not self._results:
            QMessageBox.information(self, "提示", "没有可保存的报告")
            return
        folder = QFileDialog.getExistingDirectory(self, "选择报告保存目录")
        if not folder:
            return
        count = 0
        for archive_path, (groups, total_files) in self._results.items():
            name = Path(archive_path).stem + "_report.html"
            dest = str(Path(folder) / name)
            self._write_report(dest, archive_path, groups, total_files)
            count += 1
        self._status.setText(f"已保存 {count} 份报告到: {folder}")

    def _write_report(self, dest: str, archive_path: str, groups: list[DuplicateGroup], total_files: int):
        """生成 HTML 查重报告。"""
        high = self._check_high_similarity(groups, total_files)
        dup_count = sum(len(g.files) for g in groups)
        archive_name = Path(archive_path).name

        rows = []
        for g in groups:
            method = _METHOD_LABELS.get(g.detection_method, g.detection_method)
            sim = f"{g.similarity_score * 100:.1f}%"
            file_list = "<br>".join(
                f"&nbsp;&nbsp;• {Path(f.file_path).name} ({_human_size(f.file_size)}, {f.width}x{f.height})"
                for f in g.files
            )
            rows.append(
                f"<tr><td>#{g.group_id}</td><td>{method}</td>"
                f"<td>{sim}</td><td>{len(g.files)}</td><td>{file_list}</td></tr>"
            )

        warning = '<p style="color:red;font-weight:bold;">⚠ 高相似度警告：超过 5% 的文件相似度 ≥ 98%</p>' if high else ""

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>查重报告 — {archive_name}</title>
<style>
body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; margin: 20px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #f5f5f5; }}
tr:nth-child(even) {{ background: #fafafa; }}
</style></head><body>
<h1>查重报告</h1>
<p>压缩包: {archive_name}</p>
<p>文件总数: {total_files} | 重复组: {len(groups)} | 重复文件: {dup_count}</p>
{warning}
<table><tr><th>组</th><th>方法</th><th>相似度</th><th>文件数</th><th>文件列表</th></tr>
{"".join(rows)}
</table></body></html>"""

        Path(dest).write_text(html, encoding="utf-8")

    # --------------------------------------------------------- helpers

    def _check_high_similarity(self, groups: list[DuplicateGroup], total_files: int) -> bool:
        """如果超过 5% 的文件相似度 >= 98%，返回 True。"""
        if total_files == 0:
            return False
        high_sim_files = 0
        for g in groups:
            if g.similarity_score >= 0.98:
                high_sim_files += len(g.files)
        return (high_sim_files / total_files) > 0.05
