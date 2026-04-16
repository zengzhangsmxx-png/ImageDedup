"""Results view — tree widget showing duplicate groups."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QHeaderView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

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
        if group and isinstance(group, DuplicateGroup) and len(group.files) >= 2:
            self.group_double_clicked.emit(group)

    @property
    def groups(self) -> list[DuplicateGroup]:
        return self._groups
