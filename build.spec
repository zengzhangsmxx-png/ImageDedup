# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for ImageDedup."""

import os
import sys
from pathlib import Path

block_cipher = None

# Locate the source and template directories
src_dir = os.path.join("src", "image_dedup")
templates_dir = os.path.join(src_dir, "report", "templates")

a = Analysis(
    ["run.py"],
    pathex=["src"],
    binaries=[],
    datas=[
        (templates_dir, os.path.join("image_dedup", "report", "templates")),
    ],
    hiddenimports=[
        "image_dedup",
        "image_dedup.engine",
        "image_dedup.engine.cache",
        "image_dedup.engine.scanner",
        "image_dedup.engine.hasher",
        "image_dedup.engine.feature",
        "image_dedup.engine.forensics",
        "image_dedup.gui",
        "image_dedup.gui.main_window",
        "image_dedup.gui.results_view",
        "image_dedup.gui.forensic_dialog",
        "image_dedup.gui.widgets",
        "image_dedup.gui.image_viewer_dialog",
        "image_dedup.report",
        "image_dedup.report.html_report",
        "PIL",
        "PIL.Image",
        "PIL.ExifTags",
        "imagehash",
        "cv2",
        "scipy.ndimage",
        "numpy",
        "jinja2",
        "openpyxl",
        "fitz",
        "pymupdf",
        "rarfile",
        "py7zr",
        "PyQt6",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.sip",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ImageDedup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window — pure GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
