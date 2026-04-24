"""ImageDedup — entry point."""

import logging
import multiprocessing
import sys
import traceback

from PyQt6.QtCore import QLibraryInfo, QTranslator
from PyQt6.QtWidgets import QApplication, QMessageBox

from .config import load_config
from .gui.theme import apply_theme
from .logging_setup import setup_logging
from .gui.main_window import MainWindow

_logger = logging.getLogger("image_dedup.main")


def _global_exception_handler(exc_type, exc_value, exc_tb):
    """全局未捕获异常处理器，防止程序直接崩溃闪退。"""
    # KeyboardInterrupt 正常退出
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    # 记录到日志
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _logger.critical("未捕获异常:\n%s", tb_text)

    # 尝试弹出错误对话框
    try:
        app = QApplication.instance()
        if app is not None:
            msg = (
                f"程序遇到了一个未预期的错误:\n\n"
                f"{exc_type.__name__}: {exc_value}\n\n"
                f"程序将尝试继续运行。如果问题持续出现，请重启程序。\n"
                f"详细信息已记录到日志文件。"
            )
            QMessageBox.critical(None, "ImageDedup — 错误", msg)
    except Exception:
        # 如果连对话框都弹不出来，至少 stderr 有输出
        sys.stderr.write(f"FATAL: {exc_type.__name__}: {exc_value}\n{tb_text}\n")


def main():
    multiprocessing.freeze_support()
    config = load_config()
    setup_logging(config.log_level)

    # 安装全局异常处理器
    sys.excepthook = _global_exception_handler

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
