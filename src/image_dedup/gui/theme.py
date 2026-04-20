"""Dark/Light theme management for PyQt6."""

from __future__ import annotations

from PyQt6.QtWidgets import QApplication

LIGHT_STYLESHEET = """
QMainWindow, QDialog, QWidget {
    background-color: #f5f7fa;
    color: #333333;
    font-family: -apple-system, "Microsoft YaHei", sans-serif;
}
QGroupBox {
    font-weight: bold;
    border: 1px solid #ddd;
    border-radius: 6px;
    margin-top: 8px;
    padding-top: 16px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
}
QPushButton {
    background-color: #ffffff;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    padding: 6px 14px;
    min-height: 24px;
}
QPushButton:hover { background-color: #e8f5e9; border-color: #4CAF50; }
QPushButton:pressed { background-color: #c8e6c9; }
QPushButton:disabled { background-color: #f0f0f0; color: #aaa; }
QTreeWidget {
    background-color: #ffffff;
    border: 1px solid #ddd;
    border-radius: 4px;
    alternate-background-color: #f9f9f9;
}
QTreeWidget::item:selected { background-color: #e3f2fd; color: #333; }
QTreeWidget::item:hover { background-color: #f1f8e9; }
QHeaderView::section {
    background-color: #fafafa;
    border: none;
    border-bottom: 1px solid #ddd;
    padding: 6px;
    font-weight: bold;
}
QProgressBar {
    border: 1px solid #ddd;
    border-radius: 4px;
    text-align: center;
    background-color: #f0f0f0;
}
QProgressBar::chunk { background-color: #4CAF50; border-radius: 3px; }
QStatusBar { background-color: #fafafa; border-top: 1px solid #eee; }
QLineEdit, QSpinBox, QComboBox {
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    padding: 4px 8px;
    background-color: #ffffff;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #4CAF50; }
QSlider::groove:horizontal {
    height: 6px;
    background: #ddd;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #4CAF50;
    width: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QTabWidget::pane { border: 1px solid #ddd; border-radius: 4px; }
QTabBar::tab {
    background: #f0f0f0;
    border: 1px solid #ddd;
    padding: 6px 16px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
QTabBar::tab:selected { background: #ffffff; border-bottom-color: #ffffff; }
QMenu {
    background-color: #ffffff;
    border: 1px solid #ddd;
    border-radius: 4px;
}
QMenu::item:selected { background-color: #e8f5e9; }
QCheckBox::indicator { width: 16px; height: 16px; }
QScrollBar:vertical {
    width: 10px;
    background: transparent;
}
QScrollBar::handle:vertical {
    background: #ccc;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #aaa; }
"""

DARK_STYLESHEET = """
QMainWindow, QDialog, QWidget {
    background-color: #1c1c1e;
    color: #e0e0e0;
    font-family: -apple-system, "Microsoft YaHei", sans-serif;
}
QGroupBox {
    font-weight: bold;
    border: 1px solid #3a3a3c;
    border-radius: 6px;
    margin-top: 8px;
    padding-top: 16px;
    color: #e0e0e0;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
}
QPushButton {
    background-color: #2c2c2e;
    border: 1px solid #3a3a3c;
    border-radius: 4px;
    padding: 6px 14px;
    min-height: 24px;
    color: #e0e0e0;
}
QPushButton:hover { background-color: #1b5e20; border-color: #4CAF50; }
QPushButton:pressed { background-color: #2e7d32; }
QPushButton:disabled { background-color: #2c2c2e; color: #666; }
QTreeWidget {
    background-color: #2c2c2e;
    border: 1px solid #3a3a3c;
    border-radius: 4px;
    alternate-background-color: #252527;
    color: #e0e0e0;
}
QTreeWidget::item:selected { background-color: #1b5e20; color: #fff; }
QTreeWidget::item:hover { background-color: #333335; }
QHeaderView::section {
    background-color: #2c2c2e;
    border: none;
    border-bottom: 1px solid #3a3a3c;
    padding: 6px;
    font-weight: bold;
    color: #e0e0e0;
}
QProgressBar {
    border: 1px solid #3a3a3c;
    border-radius: 4px;
    text-align: center;
    background-color: #2c2c2e;
    color: #e0e0e0;
}
QProgressBar::chunk { background-color: #4CAF50; border-radius: 3px; }
QStatusBar { background-color: #1c1c1e; border-top: 1px solid #3a3a3c; color: #aaa; }
QLineEdit, QSpinBox, QComboBox {
    border: 1px solid #3a3a3c;
    border-radius: 4px;
    padding: 4px 8px;
    background-color: #2c2c2e;
    color: #e0e0e0;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #4CAF50; }
QComboBox QAbstractItemView {
    background-color: #2c2c2e;
    color: #e0e0e0;
    selection-background-color: #1b5e20;
}
QSlider::groove:horizontal {
    height: 6px;
    background: #3a3a3c;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #4CAF50;
    width: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QTabWidget::pane { border: 1px solid #3a3a3c; border-radius: 4px; }
QTabBar::tab {
    background: #2c2c2e;
    border: 1px solid #3a3a3c;
    padding: 6px 16px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    color: #e0e0e0;
}
QTabBar::tab:selected { background: #1c1c1e; border-bottom-color: #1c1c1e; }
QMenu {
    background-color: #2c2c2e;
    border: 1px solid #3a3a3c;
    border-radius: 4px;
    color: #e0e0e0;
}
QMenu::item:selected { background-color: #1b5e20; }
QCheckBox { color: #e0e0e0; }
QCheckBox::indicator { width: 16px; height: 16px; }
QLabel { color: #e0e0e0; }
QScrollBar:vertical {
    width: 10px;
    background: transparent;
}
QScrollBar::handle:vertical {
    background: #555;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #777; }
QMessageBox { background-color: #1c1c1e; }
QSplitter::handle { background-color: #3a3a3c; }
"""


def apply_theme(app: QApplication, theme: str) -> None:
    if theme == "dark":
        app.setStyleSheet(DARK_STYLESHEET)
    else:
        app.setStyleSheet(LIGHT_STYLESHEET)
