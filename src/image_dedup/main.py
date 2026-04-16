"""ImageDedup — entry point."""

import multiprocessing
import sys

from PyQt6.QtWidgets import QApplication

from .gui.main_window import MainWindow


def main():
    multiprocessing.freeze_support()  # Required for PyInstaller on Windows
    app = QApplication(sys.argv)
    app.setApplicationName("ImageDedup")
    app.setApplicationDisplayName("ImageDedup — 图片查重工具")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
