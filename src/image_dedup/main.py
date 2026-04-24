"""ImageDedup — entry point."""

import gc
import logging
import multiprocessing
import os
import signal
import sys
import threading
import traceback

from PyQt6.QtCore import QLibraryInfo, QTimer, QTranslator
from PyQt6.QtWidgets import QApplication, QMessageBox

from .config import load_config
from .gui.theme import apply_theme
from .logging_setup import setup_logging
from .gui.main_window import MainWindow

_logger = logging.getLogger("image_dedup.main")

# ---------------------------------------------------------------------------
# 全局异常处理 — 覆盖所有线程和场景
# ---------------------------------------------------------------------------

def _safe_log_and_stderr(msg: str):
    """安全地同时写入日志和 stderr，任一失败不影响另一个。"""
    try:
        _logger.critical(msg)
    except Exception:
        pass
    try:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def _global_exception_handler(exc_type, exc_value, exc_tb):
    """全局未捕获异常处理器（主线程），防止程序直接崩溃闪退。"""
    # KeyboardInterrupt 正常退出
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    # MemoryError 特殊处理：释放内存，不弹对话框（可能分配失败）
    if issubclass(exc_type, MemoryError):
        gc.collect()
        _safe_log_and_stderr("CRITICAL MemoryError: 内存不足，已尝试释放内存")
        return

    # 记录到日志和 stderr
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _safe_log_and_stderr(f"未捕获异常:\n{tb_text}")

    # 尝试弹出错误对话框（仅在主线程且 QApplication 存在时）
    try:
        if threading.current_thread() is threading.main_thread():
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
        pass  # 对话框失败不影响程序继续


def _threading_exception_handler(args):
    """Python threading 模块的异常处理器（捕获非 QThread 的线程异常）。"""
    if args.exc_type is SystemExit:
        return

    if issubclass(args.exc_type, MemoryError):
        gc.collect()
        _safe_log_and_stderr(
            f"CRITICAL MemoryError in thread '{args.thread.name if args.thread else 'unknown'}'"
        )
        return

    tb_text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    _safe_log_and_stderr(
        f"线程 '{args.thread.name if args.thread else 'unknown'}' 未捕获异常:\n{tb_text}"
    )


def _install_signal_handlers():
    """安装信号处理器，捕获 SIGSEGV/SIGABRT 等 C 级崩溃信号。"""
    def _signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        _safe_log_and_stderr(
            f"FATAL SIGNAL {sig_name} (signum={signum}) received.\n"
            f"这通常由 C 扩展（OpenCV/PIL）处理损坏图片导致。\n"
            f"Stack:\n{''.join(traceback.format_stack(frame))}"
        )
        # 不调用 sys.exit()，让 OS 处理
        os._exit(128 + signum)

    # 仅在主线程安装
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGSEGV, signal.SIGABRT):
            try:
                signal.signal(sig, _signal_handler)
            except (OSError, ValueError):
                pass  # 某些平台不支持


def main():
    multiprocessing.freeze_support()

    # 尽早安装异常处理器
    sys.excepthook = _global_exception_handler
    threading.excepthook = _threading_exception_handler
    _install_signal_handlers()

    config = load_config()
    setup_logging(config.log_level)

    _logger.info("ImageDedup 启动，全局异常处理器已安装")

    app = QApplication(sys.argv)
    app.setApplicationName("ImageDedup")
    app.setApplicationDisplayName("ImageDedup — 图片查重工具")

    translator = QTranslator()
    translations_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load("qtbase_zh_CN", translations_path):
        app.installTranslator(translator)

    apply_theme(app, config.theme)

    # 安装定时器将 Python 异常从事件循环中抛出（PyQt6 默认会吞掉异常）
    # 每 100ms 触发一次，让 Python 有机会处理挂起的异常
    _exception_timer = QTimer()
    _exception_timer.timeout.connect(lambda: None)
    _exception_timer.start(100)

    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
