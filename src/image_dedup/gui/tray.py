"""System tray manager with file watching and scheduled scanning."""

from __future__ import annotations

from PyQt6.QtCore import QFileSystemWatcher, QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from ..logging_setup import get_logger

logger = get_logger("tray")


def _create_placeholder_icon() -> QIcon:
    """Create a simple green square as placeholder app icon."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor("#4CAF50"))
    return QIcon(pixmap)


class SystemTrayManager(QObject):
    """Manages system tray icon, file watching, and scheduled scans."""

    scan_requested = pyqtSignal(list)
    file_changed = pyqtSignal(str)

    def __init__(self, main_window, config=None):
        super().__init__(main_window)
        self._main_window = main_window
        self._config = config

        self._tray: QSystemTrayIcon | None = None
        self._watcher: QFileSystemWatcher | None = None
        self._scan_timer: QTimer | None = None
        self._scan_paths: list[str] = []

        self.setup_tray()

    def setup_tray(self):
        """Create system tray icon and context menu."""
        self._tray = QSystemTrayIcon(_create_placeholder_icon(), self)

        menu = QMenu()

        show_action = QAction("显示主窗口", menu)
        show_action.triggered.connect(self._show_main_window)
        menu.addAction(show_action)

        scan_action = QAction("开始扫描", menu)
        scan_action.triggered.connect(self._trigger_scan)
        menu.addAction(scan_action)

        menu.addSeparator()

        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self._quit_app)
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        logger.info("系统托盘已初始化")

    def setup_file_watcher(self, paths: list[str]):
        """Watch directories for file changes."""
        if self._watcher is not None:
            # Remove old paths
            old_dirs = self._watcher.directories()
            if old_dirs:
                self._watcher.removePaths(old_dirs)
        else:
            self._watcher = QFileSystemWatcher(self)
            self._watcher.directoryChanged.connect(self._on_directory_changed)

        valid_paths = [p for p in paths if p]
        if valid_paths:
            self._watcher.addPaths(valid_paths)
            logger.info(f"文件监控已设置，监控 {len(valid_paths)} 个目录")

    def setup_scheduled_scan(self, interval_min: int, paths: list[str]):
        """Set up periodic scanning with QTimer."""
        self._scan_paths = list(paths)

        if self._scan_timer is not None:
            self._scan_timer.stop()
        else:
            self._scan_timer = QTimer(self)
            self._scan_timer.timeout.connect(self._on_scheduled_scan)

        interval_ms = interval_min * 60 * 1000
        self._scan_timer.start(interval_ms)
        logger.info(f"定时扫描已设置，间隔 {interval_min} 分钟")

    def show_notification(self, title: str, message: str):
        """Show a system tray notification."""
        if self._tray is not None:
            self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 5000)

    def _show_main_window(self):
        """Show and raise the main window."""
        self._main_window.show()
        self._main_window.raise_()
        self._main_window.activateWindow()

    def _trigger_scan(self):
        """Emit scan_requested with configured paths."""
        self.scan_requested.emit(self._scan_paths)

    def _quit_app(self):
        """Quit the application."""
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        """Handle tray icon double-click to show window."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_main_window()

    def _on_directory_changed(self, path: str):
        """Handle directory change from file watcher."""
        logger.info(f"检测到目录变化: {path}")
        self.file_changed.emit(path)

    def _on_scheduled_scan(self):
        """Handle scheduled scan timer tick."""
        if self._scan_paths:
            logger.info("定时扫描触发")
            self.scan_requested.emit(self._scan_paths)
