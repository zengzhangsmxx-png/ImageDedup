#!/usr/bin/env python3
"""Comprehensive test suite for ImageDedup archive scan tab features."""

import multiprocessing
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

if __name__ == "__main__":
    multiprocessing.freeze_support()

    from PIL import Image
    from PyQt6.QtCore import QLibraryInfo, QTranslator
    from PyQt6.QtWidgets import QApplication, QMainWindow

    app = QApplication(sys.argv)

    from image_dedup.config import AppConfig, load_config
    from image_dedup.engine.archive_scanner import ArchiveScanner
    from image_dedup.engine.hasher import DuplicateGroup, ImageHashes
    from image_dedup.gui.archive_scan_tab import ArchiveScanTab, ArchiveScanWorker, _human_size
    from image_dedup.gui.main_window import MainWindow
    from image_dedup.gui.tray import SystemTrayManager
    from image_dedup.gui.widgets import DropTreeWidget

    total = 0
    passed = 0
    failed = 0
    errors = []

    def run(name, fn):
        global total, passed, failed
        total += 1
        try:
            fn()
            passed += 1
            print(f"  \u2713 [{total:02d}] {name}")
        except Exception as e:
            failed += 1
            errors.append((name, str(e)))
            print(f"  \u2717 [{total:02d}] {name}: {e}")

    def make_temp_images(count=2, color="red"):
        d = tempfile.mkdtemp()
        img = Image.new("RGB", (50, 50), color)
        for i in range(count):
            img.save(os.path.join(d, f"img{i}.png"))
        return d

    def make_zip(count=2):
        d = make_temp_images(count)
        zp = os.path.join(d, "test.zip")
        with zipfile.ZipFile(zp, "w") as zf:
            for i in range(count):
                zf.write(os.path.join(d, f"img{i}.png"), f"img{i}.png")
        return d, zp

    def fake_hashes(paths):
        return [
            ImageHashes(
                file_path=p, md5=f"m{i}", sha256=f"s{i}", phash=f"p{i}",
                dhash=f"d{i}", ahash=f"a{i}", phash_top=f"t{i}",
                file_size=(i + 1) * 100, width=(i + 1) * 10, height=(i + 1) * 10,
                computed_at=time.time(),
            )
            for i, p in enumerate(paths)
        ]

    # ================================================================
    print("=" * 60)
    print("  ImageDedup Test Suite — 50 tests")
    print("=" * 60)

    # 1
    run("All imports", lambda: None)

    # 2
    def t_translator():
        tr = QTranslator()
        tp = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        assert tr.load("qtbase_zh_CN", tp)
        assert app.installTranslator(tr)
    run("QTranslator Chinese", t_translator)

    # 3
    def t_scan_dir():
        d = make_temp_images(3)
        g, t, h = ArchiveScanner().scan_archive(d, keep_temp=True)
        assert t >= 2 and h is None
        shutil.rmtree(d)
    run("Scan directory keep_temp", t_scan_dir)

    # 4
    def t_scan_dir_no_keep():
        d = make_temp_images(2)
        g, t = ArchiveScanner().scan_archive(d, keep_temp=False)
        assert t >= 2
        shutil.rmtree(d)
    run("Scan directory no keep", t_scan_dir_no_keep)

    # 5
    def t_scan_zip_keep():
        d, zp = make_zip(2)
        g, t, h = ArchiveScanner().scan_archive(zp, keep_temp=True)
        assert t == 2 and h is not None
        for grp in g:
            for f in grp.files:
                assert Path(f.file_path).exists()
        h.cleanup()
        shutil.rmtree(d)
    run("Scan ZIP keep_temp", t_scan_zip_keep)

    # 6
    def t_scan_zip_no_keep():
        d, zp = make_zip(2)
        g, t = ArchiveScanner().scan_archive(zp, keep_temp=False)
        assert t == 2
        shutil.rmtree(d)
    run("Scan ZIP no keep", t_scan_zip_no_keep)

    # 7
    def t_scan_missing():
        g, t, h = ArchiveScanner().scan_archive("/tmp/_no_.zip", keep_temp=True)
        assert t == 0 and h is None
    run("Scan missing file", t_scan_missing)

    # 8
    def t_scan_missing_doc():
        g, t, h = ArchiveScanner().scan_archive("/tmp/_no_.xlsx", keep_temp=True)
        assert t == 0 and h is None
    run("Scan missing xlsx", t_scan_missing_doc)

    # 9
    def t_scan_missing_pdf():
        g, t, h = ArchiveScanner().scan_archive("/tmp/_no_.pdf", keep_temp=True)
        assert t == 0 and h is None
    run("Scan missing pdf", t_scan_missing_pdf)

    # 10
    def t_scan_empty_dir():
        d = tempfile.mkdtemp()
        g, t, h = ArchiveScanner().scan_archive(d, keep_temp=True)
        assert t == 0
        shutil.rmtree(d)
    run("Scan empty directory", t_scan_empty_dir)

    # 11
    def t_today_recursive():
        d = tempfile.mkdtemp()
        Path(d, "a.zip").touch()
        Path(d, "a.xlsx").touch()
        Path(d, "a.txt").touch()
        sub = Path(d, "sub"); sub.mkdir()
        Path(sub, "b.rar").touch()
        sub2 = Path(sub, "sub2"); sub2.mkdir()
        Path(sub2, "c.7z").touch()
        Path(sub2, "c.jpg").touch()
        r = ArchiveScanner().get_today_new_archives(Path(d))
        names = {x.name for x in r}
        assert "a.zip" in names and "a.xlsx" in names
        assert "b.rar" in names and "c.7z" in names
        assert "a.txt" not in names and "c.jpg" not in names
        shutil.rmtree(d)
    run("Today archives recursive", t_today_recursive)

    # 12
    def t_today_empty():
        d = tempfile.mkdtemp()
        assert len(ArchiveScanner().get_today_new_archives(Path(d))) == 0
        shutil.rmtree(d)
    run("Today archives empty", t_today_empty)

    # 13
    def t_today_nonexist():
        assert len(ArchiveScanner().get_today_new_archives(Path("/tmp/_no_dir_"))) == 0
    run("Today archives nonexistent", t_today_nonexist)

    # 14
    def t_tab_add_queue():
        tab = ArchiveScanTab()
        tab._add_queue_item("/tmp/a.zip")
        tab._add_queue_item("/tmp/b.zip")
        assert tab._queue_tree.topLevelItemCount() == 2
        assert tab._queue_contains("/tmp/a.zip")
        assert not tab._queue_contains("/tmp/c.zip")
    run("Tab add queue items", t_tab_add_queue)

    # 15
    def t_tab_remove_queue():
        tab = ArchiveScanTab()
        tab._add_queue_item("/tmp/a.zip")
        tab._add_queue_item("/tmp/b.zip")
        tab._remove_from_queue("/tmp/a.zip")
        assert tab._queue_tree.topLevelItemCount() == 1
        assert not tab._queue_contains("/tmp/a.zip")
    run("Tab remove queue item", t_tab_remove_queue)

    # 16
    def t_tab_get_paths():
        tab = ArchiveScanTab()
        tab._add_queue_item("/tmp/a.zip")
        tab._add_queue_item("/tmp/b.zip")
        assert len(tab._get_queue_paths()) == 2
    run("Tab get queue paths", t_tab_get_paths)

    # 17
    def t_tab_populate():
        tab = ArchiveScanTab()
        hs = fake_hashes(["/tmp/x.png", "/tmp/y.png"])
        g = DuplicateGroup(group_id=1, detection_method="exact", similarity_score=1.0, files=hs)
        tab._populate_results([g])
        assert tab._result_tree.topLevelItemCount() == 1
        assert tab._result_tree.topLevelItem(0).childCount() == 2
    run("Tab populate results", t_tab_populate)

    # 18
    def t_tab_delete_file():
        tab = ArchiveScanTab()
        d = tempfile.mkdtemp()
        fps = [os.path.join(d, f"{i}.png") for i in range(3)]
        for f in fps:
            Path(f).write_bytes(b"x")
        hs = fake_hashes(fps)
        g = DuplicateGroup(group_id=1, detection_method="exact", similarity_score=1.0, files=hs)
        tab._results["/tmp/t.zip"] = ([g], 3)
        tab._current_archive = "/tmp/t.zip"
        tab._populate_results([g])
        Path(fps[0]).unlink()
        groups, tf = tab._results["/tmp/t.zip"]
        for gg in groups:
            gg.files = [f for f in gg.files if f.file_path != fps[0]]
        groups = [gg for gg in groups if len(gg.files) >= 2]
        tab._results["/tmp/t.zip"] = (groups, tf - 1)
        tab._populate_results(groups)
        assert tab._result_tree.topLevelItem(0).childCount() == 2
        shutil.rmtree(d)
    run("Tab delete single file", t_tab_delete_file)

    # 19
    def t_tab_cleanup_temps():
        tab = ArchiveScanTab()
        tab._temp_handles = {"/a": tempfile.TemporaryDirectory(), "/b": tempfile.TemporaryDirectory()}
        tab.stop_and_cleanup()
        assert len(tab._temp_handles) == 0
    run("Tab cleanup all temps", t_tab_cleanup_temps)

    # 20
    def t_tab_cleanup_single():
        tab = ArchiveScanTab()
        tab._temp_handles = {"/a": tempfile.TemporaryDirectory(), "/b": tempfile.TemporaryDirectory()}
        tab._cleanup_temp("/a")
        assert len(tab._temp_handles) == 1
        tab._cleanup_all_temps()
        assert len(tab._temp_handles) == 0
    run("Tab cleanup single temp", t_tab_cleanup_single)

    # 21
    def t_tray_create():
        w = QMainWindow()
        t = SystemTrayManager(w)
        assert t._tray is not None
        t.cleanup()
    run("Tray create", t_tray_create)

    # 22
    def t_tray_cleanup():
        w = QMainWindow()
        t = SystemTrayManager(w)
        t.cleanup()
        assert t._tray is None and t._watcher is None and t._scan_timer is None
    run("Tray cleanup", t_tray_cleanup)

    # 23
    def t_tray_double():
        w = QMainWindow()
        t = SystemTrayManager(w)
        t.cleanup()
        t.cleanup()
    run("Tray double cleanup", t_tray_double)

    # 24
    def t_drop_init():
        tree = DropTreeWidget()
        assert hasattr(tree, "_active_workers") and len(tree._active_workers) == 0
    run("DropTreeWidget init", t_drop_init)

    # 25
    def t_drop_cleanup():
        tree = DropTreeWidget()
        tree.cleanup_workers()
        assert len(tree._active_workers) == 0
    run("DropTreeWidget cleanup", t_drop_cleanup)

    # 26
    def t_mw_create():
        w = MainWindow(load_config())
        w.close()
    run("MainWindow create/close", t_mw_create)

    # 27
    def t_mw_show_close():
        w = MainWindow(load_config())
        w.show()
        w.close()
    run("MainWindow show/close", t_mw_show_close)

    # 28
    def t_dedup_empty():
        g, t = ArchiveScanner()._scan_dedup([], AppConfig(), "empty")
        assert t == 0 and len(g) == 0
    run("_scan_dedup empty", t_dedup_empty)

    # 29
    def t_high_sim_zero():
        assert not ArchiveScanTab()._check_high_similarity([], 0)
    run("check_high_similarity zero", t_high_sim_zero)

    # 30
    def t_pick_best():
        tab = ArchiveScanTab()
        hs = fake_hashes(["/tmp/a.png", "/tmp/b.png"])
        g = DuplicateGroup(group_id=1, detection_method="exact", similarity_score=1.0, files=hs)
        assert tab._pick_best(g).file_path == "/tmp/b.png"
    run("pick_best", t_pick_best)

    # 31
    def t_human_size():
        assert "B" in _human_size(100)
        assert "KB" in _human_size(2048)
        assert "MB" in _human_size(2 * 1024 * 1024)
    run("_human_size", t_human_size)

    # 32-36: stress tab
    for i in range(5):
        def t(idx=i):
            tab = ArchiveScanTab()
            tab._add_queue_item(f"/tmp/s{idx}.zip")
            assert tab._queue_tree.topLevelItemCount() == 1
            tab.stop_and_cleanup()
        run(f"Stress tab #{i+1}", t)

    # 37-41: stress tray
    for i in range(5):
        def t(idx=i):
            w = QMainWindow()
            tr = SystemTrayManager(w)
            tr.cleanup()
        run(f"Stress tray #{i+1}", t)

    # 42-46: stress MainWindow
    for i in range(5):
        def t(idx=i):
            w = MainWindow(load_config())
            w.show()
            w.close()
        run(f"Stress MainWindow #{i+1}", t)

    # 47-50: stress scan
    for i in range(4):
        def t(idx=i):
            d, zp = make_zip(2)
            g, total, h = ArchiveScanner().scan_archive(zp, keep_temp=True)
            assert total == 2
            if h:
                h.cleanup()
            shutil.rmtree(d)
        run(f"Stress scan ZIP #{i+1}", t)

    # ================================================================
    print("\n" + "=" * 60)
    print(f"  Total: {total}  |  Passed: {passed}  |  Failed: {failed}")
    print("=" * 60)
    if errors:
        print("\nFailed tests:")
        for name, msg in errors:
            print(f"  - {name}: {msg}")

    app.quit()
    sys.exit(0 if failed == 0 else 1)
