"""Custom widgets — ImageViewer, ThresholdSlider, DropTreeWidget."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import cv2
import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSlider,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from ..logging_setup import get_logger

logger = get_logger("widgets")


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


ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".tgz", ".tar.gz", ".tar.bz2"}
ACCEPTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".tgz",
    ".xlsx", ".xls", ".pdf",
}


def _is_archive(p: Path) -> bool:
    name = p.name.lower()
    if name.endswith(".tar.gz") or name.endswith(".tar.bz2"):
        return True
    return p.suffix.lower() in {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".tgz"}


def _extract_archive(archive_path: Path, dest_dir: Path):
    """Extract archive to dest_dir. Supports ZIP, RAR, 7z, tar/gz/bz2."""
    suffix = archive_path.suffix.lower()
    name = archive_path.name.lower()

    if suffix == ".zip":
        import zipfile
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest_dir)
    elif suffix == ".rar":
        import rarfile
        with rarfile.RarFile(str(archive_path), "r") as rf:
            rf.extractall(str(dest_dir))
    elif suffix == ".7z":
        import py7zr
        with py7zr.SevenZipFile(str(archive_path), "r") as sz:
            sz.extractall(str(dest_dir))
    elif suffix in (".tar", ".tgz") or name.endswith(".tar.gz") or name.endswith(".tar.bz2"):
        import tarfile
        with tarfile.open(str(archive_path), "r:*") as tf:
            tf.extractall(dest_dir, filter="data")
    elif suffix == ".gz":
        import gzip
        out_path = dest_dir / archive_path.stem
        with gzip.open(archive_path, "rb") as f_in, open(out_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    elif suffix == ".bz2":
        import bz2
        out_path = dest_dir / archive_path.stem
        with bz2.open(archive_path, "rb") as f_in, open(out_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)


def _get_extract_base() -> Path:
    """Get the extraction base directory, compatible with PyInstaller."""
    # Use current working directory for user-visible extraction
    # In PyInstaller, sys.executable points to the .exe, use its parent directory
    import sys
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle
        base = Path(sys.executable).parent / "ImageDedup"
    else:
        # Running as script
        base = Path.cwd() / "ImageDedup"
    base.mkdir(parents=True, exist_ok=True)
    return base

_EXTRACT_BASE = _get_extract_base()

_LEVEL_LABELS = {0: "1级目录", 1: "2级目录", 2: "3级目录"}


def _recursive_extract(archive_path: Path, dest_dir: Path):
    """Extract archive, then recursively extract any nested archives inside."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        _extract_archive(archive_path, dest_dir)
    except Exception as e:
        logger.warning("Extract failed %s: %s", archive_path, e)
        return

    for f in list(dest_dir.rglob("*")):
        if f.is_file() and _is_archive(f):
            nested_dest = f.parent / f.stem
            _recursive_extract(f, nested_dest)
            try:
                f.unlink()
            except OSError:
                pass


class DropTreeWidget(QTreeWidget):
    """Tree widget for source management with drag-drop, auto-expand folders and auto-extract archives."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["来源", "类型", "数量"])
        self.setColumnCount(3)
        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.setAcceptDrops(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DropOnly)
        self.setRootIsDecorated(True)
        self.setAlternatingRowColors(True)
        self._extracted_dirs: list[Path] = []

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
            if p.is_dir():
                self.add_folder(p)
            elif p.is_file() and p.suffix.lower() in ACCEPTED_EXTENSIONS:
                if _is_archive(p):
                    self.add_archive(p)
                else:
                    self.add_file(p)
        event.acceptProposedAction()

    def add_folder(self, folder: Path):
        """Add a folder, expanding its sub-folders as child nodes."""
        item = QTreeWidgetItem([folder.name, "文件夹", ""])
        item.setToolTip(0, str(folder))
        item.setData(0, Qt.ItemDataRole.UserRole, str(folder))
        item.setCheckState(0, Qt.CheckState.Checked)

        sub_dirs = sorted([d for d in folder.iterdir() if d.is_dir()])
        img_count = sum(1 for f in folder.iterdir()
                        if f.is_file() and f.suffix.lower() in {
                            ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"})

        if sub_dirs:
            for sd in sub_dirs:
                self._add_subfolder(item, sd)
        item.setText(2, f"{img_count} 张" if img_count else "")
        self.addTopLevelItem(item)
        item.setExpanded(True)

    def _add_subfolder(self, parent_item: QTreeWidgetItem, folder: Path):
        img_count = sum(1 for f in folder.rglob("*")
                        if f.is_file() and f.suffix.lower() in {
                            ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"})
        child = QTreeWidgetItem([folder.name, "子文件夹", f"{img_count} 张" if img_count else ""])
        child.setToolTip(0, str(folder))
        child.setData(0, Qt.ItemDataRole.UserRole, str(folder))
        child.setCheckState(0, Qt.CheckState.Checked)

        sub_dirs = sorted([d for d in folder.iterdir() if d.is_dir()])
        for sd in sub_dirs:
            self._add_subfolder(child, sd)

        parent_item.addChild(child)

    def add_archive(self, archive_path: Path):
        """Extract archive to app cache directory, preserving folder hierarchy with level labels."""
        _EXTRACT_BASE.mkdir(parents=True, exist_ok=True)
        dest_dir = _EXTRACT_BASE / archive_path.stem
        # Avoid collision if same name already extracted
        if dest_dir.exists():
            idx = 1
            while (dest_dir.parent / f"{archive_path.stem}_{idx}").exists():
                idx += 1
            dest_dir = dest_dir.parent / f"{archive_path.stem}_{idx}"

        _recursive_extract(archive_path, dest_dir)
        self._extracted_dirs.append(dest_dir)

        img_count = self._count_images(dest_dir)
        item = QTreeWidgetItem([archive_path.name, "压缩包", f"{img_count} 张" if img_count else ""])
        item.setToolTip(0, str(dest_dir))
        item.setData(0, Qt.ItemDataRole.UserRole, str(dest_dir))
        item.setCheckState(0, Qt.CheckState.Checked)

        self._add_archive_children(item, dest_dir, level=0)

        self.addTopLevelItem(item)
        item.setExpanded(True)

    def add_file(self, file_path: Path):
        """Add a single file (image, xlsx, pdf)."""
        item = QTreeWidgetItem([file_path.name, "文件", "1"])
        item.setToolTip(0, str(file_path))
        item.setData(0, Qt.ItemDataRole.UserRole, str(file_path))
        item.setCheckState(0, Qt.CheckState.Checked)
        self.addTopLevelItem(item)

    def _count_images(self, folder: Path) -> int:
        return sum(1 for f in folder.rglob("*")
                   if f.is_file() and f.suffix.lower() in {
                       ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"})

    def get_checked_paths(self) -> list[str]:
        """Return all checked source paths (for scanning)."""
        paths = []
        self._collect_checked(None, paths)
        return paths

    def _collect_checked(self, parent_item, paths: list[str]):
        if parent_item is None:
            for i in range(self.topLevelItemCount()):
                item = self.topLevelItem(i)
                self._collect_item(item, paths)
        else:
            for i in range(parent_item.childCount()):
                item = parent_item.child(i)
                self._collect_item(item, paths)

    def _collect_item(self, item: QTreeWidgetItem, paths: list[str]):
        if item.checkState(0) == Qt.CheckState.Checked:
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if path:
                # All checked → just return this path (Scanner rglobs subdirs)
                all_children_checked = True
                for i in range(item.childCount()):
                    if item.child(i).checkState(0) != Qt.CheckState.Checked:
                        all_children_checked = False
                        break
                if item.childCount() == 0 or all_children_checked:
                    paths.append(path)
                else:
                    # Mixed state among children — recurse
                    self._collect_checked(item, paths)
        elif item.checkState(0) == Qt.CheckState.PartiallyChecked:
            self._collect_checked(item, paths)

    @property
    def extracted_dirs(self) -> list[Path]:
        return self._extracted_dirs

    def _add_archive_children(self, parent_item: QTreeWidgetItem, folder: Path, level: int):
        """Recursively add sub-folders with level labels (1级/2级/3级目录)."""
        _IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
        sub_dirs = sorted([d for d in folder.iterdir() if d.is_dir()])
        loose_imgs = [f for f in folder.iterdir()
                      if f.is_file() and f.suffix.lower() in _IMG_EXTS]

        for sd in sub_dirs:
            img_count = self._count_images(sd)
            level_label = _LEVEL_LABELS.get(level, f"{level + 1}级目录")
            child = QTreeWidgetItem([sd.name, level_label, f"{img_count} 张" if img_count else ""])
            child.setToolTip(0, str(sd))
            child.setData(0, Qt.ItemDataRole.UserRole, str(sd))
            child.setCheckState(0, Qt.CheckState.Checked)
            parent_item.addChild(child)
            self._add_archive_children(child, sd, level + 1)
            if child.childCount() > 0:
                child.setExpanded(True)

        # Show loose image files as individual leaf nodes
        for img in sorted(loose_imgs):
            leaf = QTreeWidgetItem([img.name, "图片", ""])
            leaf.setToolTip(0, str(img))
            leaf.setData(0, Qt.ItemDataRole.UserRole, str(img))
            leaf.setCheckState(0, Qt.CheckState.Checked)
            parent_item.addChild(leaf)

    def cleanup_extracted(self):
        """No-op — extracted directories are permanently kept for the user."""
        pass

    def load_existing_extracted(self):
        """On startup, load any previously extracted archive directories into the tree."""
        if not _EXTRACT_BASE.exists():
            return
        for d in sorted(_EXTRACT_BASE.iterdir()):
            if not d.is_dir():
                continue
            img_count = self._count_images(d)
            item = QTreeWidgetItem([d.name, "已解压", f"{img_count} 张" if img_count else ""])
            item.setToolTip(0, str(d))
            item.setData(0, Qt.ItemDataRole.UserRole, str(d))
            item.setCheckState(0, Qt.CheckState.Checked)
            self._add_archive_children(item, d, level=0)
            self.addTopLevelItem(item)
            item.setExpanded(True)
