"""ImageDedup — entry point."""

import multiprocessing
import sys

from PyQt6.QtCore import QLibraryInfo, QTranslator
from PyQt6.QtWidgets import QApplication

from .config import load_config
from .gui.theme import apply_theme
from .logging_setup import setup_logging
from .gui.main_window import MainWindow


def main():
    multiprocessing.freeze_support()
    config = load_config()
    setup_logging(config.log_level)

    app = QApplication(sys.argv)
    app.setApplicationName("ImageDedup")
    app.setApplicationDisplayName("ImageDedup — 图片查重工具")

    translator = QTranslator()
    translations_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load("qtbase_zh_CN", translations_path):
        app.installTranslator(translator)

    apply_theme(app, config.theme)

    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
