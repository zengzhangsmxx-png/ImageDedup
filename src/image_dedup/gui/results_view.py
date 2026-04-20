"""Results view — tree widget showing duplicate groups."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..engine.hasher import DuplicateGroup

_METHOD_LABELS = {
    "exact": "精准匹配 (MD5)",
    "perceptual": "感知哈希",
    "feature": "特征匹配 (ORB)",
    "video": "视频查重",
    "semantic": "AI 语义相似度",
}


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class BatchRenameDialog(QDialog):
    """批量重命名对话框：前缀 + 起始序号，实时预览。"""

    def __init__(self, extensions: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量重命名")
        self.setMinimumWidth(400)
        self._extensions = extensions

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._prefix = QLineEdit("img")
        self._prefix.textChanged.connect(self._update_preview)
        form.addRow("前缀:", self._prefix)

        self._start = QSpinBox()
        self._start.setRange(1, 999999)
        self._start.setValue(1)
        self._start.valueChanged.connect(self._update_preview)
        form.addRow("起始序号:", self._start)

        layout.addLayout(form)

        self._preview = QLabel()
        self._preview.setWordWrap(True)
        self._preview.setStyleSheet("color: #666; padding: 6px;")
        layout.addWidget(QLabel("预览:"))
        layout.addWidget(self._preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_preview()

    def _update_preview(self):
        prefix = self._prefix.text() or "img"
        start = self._start.value()
        samples = []
        for i, ext in enumerate(self._extensions[:5]):
            samples.append(f"{prefix}_{start + i:03d}{ext}")
        text = ", ".join(samples)
        if len(self._extensions) > 5:
            text += f", ... (共 {len(self._extensions)} 个)"
        self._preview.setText(text)

    @property
    def prefix(self) -> str:
        return self._prefix.text() or "img"

    @property
    def start_index(self) -> int:
        return self._start.value()


class ResultsView(QWidget):
    """Displays duplicate groups in a tree widget."""

    group_double_clicked = pyqtSignal(object)  # DuplicateGroup
    file_double_clicked = pyqtSignal(str, object)  # (file_path, DuplicateGroup)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Batch operations toolbar
        toolbar = QHBoxLayout()
        self._btn_select_dupes = QPushButton("选择所有副本")
        self._btn_select_dupes.setToolTip("每组保留最优文件，选中其余副本")
        self._btn_select_dupes.clicked.connect(self._select_all_duplicates)

        self._btn_batch_delete = QPushButton("批量删除选中")
        self._btn_batch_delete.setToolTip("删除所有选中的文件")
        self._btn_batch_delete.clicked.connect(self._batch_delete_selected)
        self._btn_batch_delete.setStyleSheet("color: #d32f2f;")

        self._btn_batch_move = QPushButton("批量移动")
        self._btn_batch_move.setToolTip("将选中的文件移动到指定目录")
        self._btn_batch_move.clicked.connect(self._batch_move_selected)

        self._btn_auto_best = QPushButton("自动保留最优")
        self._btn_auto_best.setToolTip("每组自动勾选副本，保留分辨率最高的文件")
        self._btn_auto_best.clicked.connect(self._auto_keep_best)

        self._btn_batch_rename = QPushButton("批量重命名")
        self._btn_batch_rename.setToolTip("批量重命名选中的文件")
        self._btn_batch_rename.clicked.connect(self._batch_rename_selected)

        self._btn_deselect = QPushButton("取消选择")
        self._btn_deselect.clicked.connect(lambda: self._tree.clearSelection())

        toolbar.addWidget(self._btn_select_dupes)
        toolbar.addWidget(self._btn_batch_delete)
        toolbar.addWidget(self._btn_batch_move)
        toolbar.addWidget(self._btn_auto_best)
        toolbar.addWidget(self._btn_batch_rename)
        toolbar.addWidget(self._btn_deselect)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Filter bar
        filter_layout = QHBoxLayout()
        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText("搜索文件名或路径...")
        self._filter_input.setClearButtonEnabled(True)
        self._filter_input.textChanged.connect(self._apply_filters)
        filter_layout.addWidget(self._filter_input, 1)

        filter_layout.addWidget(QLabel("方法:"))
        self._filter_method = QComboBox()
        self._filter_method.addItems(["全部", "精准匹配", "感知哈希", "特征匹配", "视频查重", "AI 语义相似度"])
        self._filter_method.currentIndexChanged.connect(self._apply_filters)
        filter_layout.addWidget(self._filter_method)

        filter_layout.addWidget(QLabel("相似度:"))
        self._filter_sim_min = QSpinBox()
        self._filter_sim_min.setRange(0, 100)
        self._filter_sim_min.setValue(0)
        self._filter_sim_min.setSuffix("%")
        self._filter_sim_min.valueChanged.connect(self._apply_filters)
        filter_layout.addWidget(self._filter_sim_min)
        filter_layout.addWidget(QLabel("-"))
        self._filter_sim_max = QSpinBox()
        self._filter_sim_max.setRange(0, 100)
        self._filter_sim_max.setValue(100)
        self._filter_sim_max.setSuffix("%")
        self._filter_sim_max.valueChanged.connect(self._apply_filters)
        filter_layout.addWidget(self._filter_sim_max)
        layout.addLayout(filter_layout)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["组/文件", "检测方法", "相似度", "大小", "尺寸"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setColumnCount(5)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)

        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.setSortingEnabled(True)
        layout.addWidget(self._tree)

        self._groups: list[DuplicateGroup] = []
        self._all_items: list[QTreeWidgetItem] = []  # Store all items for filtering

    def set_results(self, groups: list[DuplicateGroup]):
        self._groups = groups
        self._tree.setSortingEnabled(False)
        self._tree.clear()

        _SORT_ROLE = Qt.ItemDataRole.UserRole + 1

        for g in groups:
            method_label = _METHOD_LABELS.get(g.detection_method, g.detection_method)
            if hasattr(g, 'multi_account') and g.multi_account:
                method_label += " [一机多号截图]"
            sim_text = f"{g.similarity_score * 100:.1f}%"

            group_item = QTreeWidgetItem([
                f"重复组 #{g.group_id} ({len(g.files)} 个文件)",
                method_label,
                sim_text,
                "",
                "",
            ])
            group_item.setData(0, Qt.ItemDataRole.UserRole, g)
            group_item.setData(2, _SORT_ROLE, g.similarity_score)

            # Set icon thumbnail from first file
            if g.files:
                pm = QPixmap(g.files[0].file_path)
                if not pm.isNull():
                    icon = QIcon(pm.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
                    group_item.setIcon(0, icon)

            for f in g.files:
                name = Path(f.file_path).name
                child = QTreeWidgetItem([
                    name,
                    "",
                    "",
                    _human_size(f.file_size),
                    f"{f.width}x{f.height}",
                ])
                child.setToolTip(0, f.file_path)
                child.setData(0, Qt.ItemDataRole.UserRole, g)
                child.setData(3, _SORT_ROLE, f.file_size)

                # Thumbnail
                pm = QPixmap(f.file_path)
                if not pm.isNull():
                    icon = QIcon(pm.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
                    child.setIcon(0, icon)

                group_item.addChild(child)

            self._tree.addTopLevelItem(group_item)

        self._tree.setSortingEnabled(True)
        self._tree.expandAll()

    def clear(self):
        self._tree.clear()
        self._groups.clear()

    def _on_double_click(self, item: QTreeWidgetItem, column: int):
        group = item.data(0, Qt.ItemDataRole.UserRole)
        if not group or not isinstance(group, DuplicateGroup):
            return
        if item.parent() is None:
            if len(group.files) >= 2:
                self.group_double_clicked.emit(group)
        else:
            file_path = item.toolTip(0)
            if file_path:
                self.file_double_clicked.emit(file_path, group)

    def _on_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if item is None:
            return

        selected = self._tree.selectedItems()
        file_items = [i for i in selected if i.parent() is not None]

        menu = QMenu(self)

        if len(file_items) > 1:
            action_batch_delete = menu.addAction(f"删除选中的 {len(file_items)} 个文件")
            action_batch_remove = menu.addAction(f"从结果中移除选中的 {len(file_items)} 项")
            chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
            if chosen == action_batch_delete:
                self._batch_delete_selected()
            elif chosen == action_batch_remove:
                for fi in reversed(file_items):
                    self._sync_group_data(fi)
                    self._remove_item_from_tree(fi)
        elif item.parent() is not None:
            action_remove = menu.addAction("从结果中移除")
            action_delete = menu.addAction("删除文件（不可恢复）")
            chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
            if chosen == action_remove:
                self._sync_group_data(item)
                self._remove_item_from_tree(item)
            elif chosen == action_delete:
                self._delete_file_from_disk(item)

    def _sync_group_data(self, item: QTreeWidgetItem):
        file_path = item.toolTip(0)
        group = item.data(0, Qt.ItemDataRole.UserRole)
        if group and isinstance(group, DuplicateGroup):
            group.files = [f for f in group.files if f.file_path != file_path]
            if len(group.files) < 2:
                self._groups = [g for g in self._groups if g.group_id != group.group_id]

    def _remove_item_from_tree(self, item: QTreeWidgetItem):
        parent = item.parent()
        if parent is None:
            return
        parent.removeChild(item)
        if parent.childCount() < 2:
            index = self._tree.indexOfTopLevelItem(parent)
            if index >= 0:
                self._tree.takeTopLevelItem(index)

    def _delete_file_from_disk(self, item: QTreeWidgetItem):
        file_path = item.toolTip(0)
        if not file_path:
            return
        reply = QMessageBox.warning(
            self, "确认删除",
            f"确定要永久删除此文件吗？\n\n{file_path}\n\n此操作不可恢复！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(file_path)
                self._sync_group_data(item)
                self._remove_item_from_tree(item)
            except OSError as e:
                QMessageBox.critical(self, "删除失败", f"无法删除文件:\n{e}")

    @property
    def groups(self) -> list[DuplicateGroup]:
        return self._groups

    # --- Batch operations ---

    def _pick_best_in_group(self, group: DuplicateGroup):
        """Pick the best file to keep: highest resolution > largest file > newest mtime."""
        best = group.files[0]
        for f in group.files[1:]:
            f_pixels = (f.width or 0) * (f.height or 0)
            best_pixels = (best.width or 0) * (best.height or 0)
            if f_pixels > best_pixels:
                best = f
            elif f_pixels == best_pixels:
                if f.file_size > best.file_size:
                    best = f
                elif f.file_size == best.file_size:
                    try:
                        if Path(f.file_path).stat().st_mtime > Path(best.file_path).stat().st_mtime:
                            best = f
                    except OSError:
                        pass
        return best

    def _select_all_duplicates(self):
        """For each group, select all files except the best one."""
        self._tree.clearSelection()
        for i in range(self._tree.topLevelItemCount()):
            group_item = self._tree.topLevelItem(i)
            group = group_item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(group, DuplicateGroup) or len(group.files) < 2:
                continue
            best = self._pick_best_in_group(group)
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                file_path = child.toolTip(0)
                if file_path != best.file_path:
                    child.setSelected(True)

    def _batch_delete_selected(self):
        """Delete all selected file items from disk."""
        selected = self._tree.selectedItems()
        file_items = [item for item in selected if item.parent() is not None]
        if not file_items:
            QMessageBox.information(self, "提示", "请先选择要删除的文件")
            return

        paths = [item.toolTip(0) for item in file_items]
        preview = "\n".join(paths[:10])
        if len(paths) > 10:
            preview += f"\n... 等共 {len(paths)} 个文件"

        reply = QMessageBox.warning(
            self, "确认批量删除",
            f"确定要永久删除 {len(paths)} 个文件吗？\n\n{preview}\n\n此操作不可恢复！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        deleted = 0
        failed = []
        for item in reversed(file_items):
            file_path = item.toolTip(0)
            try:
                os.remove(file_path)
                self._sync_group_data(item)
                self._remove_item_from_tree(item)
                deleted += 1
            except OSError as e:
                failed.append(f"{Path(file_path).name}: {e}")

        msg = f"已删除 {deleted} 个文件"
        if failed:
            msg += f"\n\n{len(failed)} 个文件删除失败:\n" + "\n".join(failed[:5])
        QMessageBox.information(self, "批量删除完成", msg)

    def _batch_move_selected(self):
        """Move all selected file items to a chosen directory."""
        selected = self._tree.selectedItems()
        file_items = [item for item in selected if item.parent() is not None]
        if not file_items:
            QMessageBox.information(self, "提示", "请先选择要移动的文件")
            return

        dest_dir = QFileDialog.getExistingDirectory(self, "选择目标目录")
        if not dest_dir:
            return

        dest = Path(dest_dir)
        moved = 0
        failed = []
        for item in reversed(file_items):
            file_path = item.toolTip(0)
            src = Path(file_path)
            target = dest / src.name
            # Handle name collisions
            if target.exists():
                stem = src.stem
                suffix = src.suffix
                counter = 1
                while target.exists():
                    target = dest / f"{stem}_{counter}{suffix}"
                    counter += 1
            try:
                shutil.move(str(src), str(target))
                self._sync_group_data(item)
                self._remove_item_from_tree(item)
                moved += 1
            except OSError as e:
                failed.append(f"{src.name}: {e}")

        msg = f"已移动 {moved} 个文件到 {dest_dir}"
        if failed:
            msg += f"\n\n{len(failed)} 个文件移动失败:\n" + "\n".join(failed[:5])
        QMessageBox.information(self, "批量移动完成", msg)

    def _auto_keep_best(self):
        """For each group, check all duplicates and uncheck the best file via checkboxes."""
        marked = 0
        for i in range(self._tree.topLevelItemCount()):
            group_item = self._tree.topLevelItem(i)
            group = group_item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(group, DuplicateGroup) or len(group.files) < 2:
                continue
            best = self._pick_best_in_group(group)
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                file_path = child.toolTip(0)
                if file_path == best.file_path:
                    child.setCheckState(0, Qt.CheckState.Unchecked)
                else:
                    child.setCheckState(0, Qt.CheckState.Checked)
                    marked += 1

        QMessageBox.information(self, "自动保留最优", f"已标记 {marked} 个副本文件")

    def _batch_rename_selected(self):
        """Rename all selected file items using a prefix + sequential number."""
        selected = self._tree.selectedItems()
        file_items = [item for item in selected if item.parent() is not None]
        if not file_items:
            QMessageBox.information(self, "提示", "请先选择要重命名的文件")
            return

        extensions = [Path(item.toolTip(0)).suffix for item in file_items]
        dlg = BatchRenameDialog(extensions, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        prefix = dlg.prefix
        start = dlg.start_index
        renamed = 0
        failed = []
        for idx, item in enumerate(file_items):
            file_path = item.toolTip(0)
            src = Path(file_path)
            new_name = f"{prefix}_{start + idx:03d}{src.suffix}"
            target = src.parent / new_name
            # Handle collision with existing file
            if target.exists() and target != src:
                counter = 1
                stem = f"{prefix}_{start + idx:03d}"
                while target.exists() and target != src:
                    target = src.parent / f"{stem}_{counter}{src.suffix}"
                    counter += 1
            try:
                src.rename(target)
                item.setText(0, target.name)
                item.setToolTip(0, str(target))
                # Update the group data as well
                group = item.data(0, Qt.ItemDataRole.UserRole)
                if group and isinstance(group, DuplicateGroup):
                    for f in group.files:
                        if f.file_path == file_path:
                            f.file_path = str(target)
                            break
                renamed += 1
            except OSError as e:
                failed.append(f"{src.name}: {e}")

        msg = f"已重命名 {renamed} 个文件"
        if failed:
            msg += f"\n\n{len(failed)} 个文件重命名失败:\n" + "\n".join(failed[:5])
        QMessageBox.information(self, "批量重命名完成", msg)

    # --- Filtering ---

    _METHOD_FILTER_MAP = {
        0: None,        # 全部
        1: "exact",     # 精准匹配
        2: "perceptual",# 感知哈希
        3: "feature",   # 特征匹配
        4: "video",     # 视频查重
        5: "semantic",  # AI 语义相似度
    }

    def _apply_filters(self):
        search_text = self._filter_input.text().lower()
        method_idx = self._filter_method.currentIndex()
        method_key = self._METHOD_FILTER_MAP.get(method_idx)
        sim_min = self._filter_sim_min.value() / 100.0
        sim_max = self._filter_sim_max.value() / 100.0

        for i in range(self._tree.topLevelItemCount()):
            group_item = self._tree.topLevelItem(i)
            group = group_item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(group, DuplicateGroup):
                group_item.setHidden(False)
                continue

            # Method filter
            if method_key and group.detection_method != method_key:
                group_item.setHidden(True)
                continue

            # Similarity filter
            if group.similarity_score < sim_min or group.similarity_score > sim_max:
                group_item.setHidden(True)
                continue

            # Text search — match against child file names/paths
            if search_text:
                any_child_match = False
                for j in range(group_item.childCount()):
                    child = group_item.child(j)
                    name = child.text(0).lower()
                    path = child.toolTip(0).lower()
                    match = search_text in name or search_text in path
                    child.setHidden(not match)
                    if match:
                        any_child_match = True
                group_item.setHidden(not any_child_match)
            else:
                group_item.setHidden(False)
                for j in range(group_item.childCount()):
                    group_item.child(j).setHidden(False)
