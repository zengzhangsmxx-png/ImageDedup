"""Top-level entry point for PyInstaller — uses absolute imports."""

import multiprocessing
import sys
import traceback

if __name__ == "__main__":
    multiprocessing.freeze_support()

    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox

        app = QApplication(sys.argv)
        app.setApplicationName("ImageDedup")
        app.setApplicationDisplayName("ImageDedup — 图片查重工具")

        from image_dedup.gui.main_window import MainWindow

        window = MainWindow()
        window.show()
        sys.exit(app.exec())

    except Exception:
        # Show error in a dialog so the user sees it (console=False hides stderr)
        err = traceback.format_exc()
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox

            if not QApplication.instance():
                _app = QApplication(sys.argv)
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("ImageDedup 启动失败")
            msg.setText("程序启动时发生错误:")
            msg.setDetailedText(err)
            msg.exec()
        except Exception:
            # Last resort: write to a log file next to the exe
            from pathlib import Path

            log_path = Path(sys.executable).parent / "crash.log"
            log_path.write_text(err, encoding="utf-8")
