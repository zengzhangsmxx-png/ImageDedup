"""Results view — tree widget showing duplicate groups."""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QHeaderView,
    QMenu,
    QMessageBox,
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
}


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class ResultsView(QWidget):
    """Displays duplicate groups in a tree widget."""

    group_double_clicked = pyqtSignal(object)  # DuplicateGroup
    file_double_clicked = pyqtSignal(str, object)  # (file_path, DuplicateGroup)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["组/文件", "检测方法", "相似度", "大小", "尺寸"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setColumnCount(5)

        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._tree)

        self._groups: list[DuplicateGroup] = []

    def set_results(self, groups: list[DuplicateGroup]):
        self._groups = groups
        self._tree.clear()

        for g in groups:
            method_label = _METHOD_LABELS.get(g.detection_method, g.detection_method)
            sim_text = f"{g.similarity_score * 100:.1f}%"

            group_item = QTreeWidgetItem([
                f"重复组 #{g.group_id} ({len(g.files)} 个文件)",
                method_label,
                sim_text,
                "",
                "",
            ])
            group_item.setData(0, Qt.ItemDataRole.UserRole, g)

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

                # Thumbnail
                pm = QPixmap(f.file_path)
                if not pm.isNull():
                    icon = QIcon(pm.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
                    child.setIcon(0, icon)

                group_item.addChild(child)

            self._tree.addTopLevelItem(group_item)

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
        if item is None or item.parent() is None:
            return

        menu = QMenu(self)
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
