"""压缩包内图片查重引擎 — 解压到临时目录，扫描并查找重复，自动清理。"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from ..config import AppConfig
from ..logging_setup import get_logger
from .cache import HashCache
from .hasher import DuplicateGroup, HashEngine
from .scanner import SUPPORTED_FORMATS, Scanner

logger = get_logger("archive_scanner")

# 支持的压缩包格式
ARCHIVE_FORMATS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".tgz"}


class ArchiveScanner:
    """扫描压缩包内部图片并查找重复项，全程对用户透明（无可见解压过程）。"""

    def __init__(self, config: AppConfig | None = None):
        self._config = config or AppConfig()

    def scan_archive(
        self,
        archive_path: str | Path,
        config: AppConfig | None = None,
    ) -> tuple[list[DuplicateGroup], int]:
        """扫描压缩包内的图片，返回 (重复组列表, 文件总数)。

        解压到临时目录，计算哈希并查找精确+感知重复，完成后自动清理。
        """
        archive_path = Path(archive_path)
        cfg = config or self._config

        if not archive_path.is_file():
            logger.error("压缩包不存在: %s", archive_path)
            return [], 0

        extracted_dir, temp_handle = self._temp_extract(archive_path)
        try:
            # 扫描解压目录中的图片
            scanner = Scanner()
            try:
                image_files = scanner.scan([extracted_dir])
            finally:
                scanner.cleanup()

            total_count = len(image_files)
            if total_count == 0:
                logger.info("压缩包内未找到图片: %s", archive_path)
                return [], 0

            logger.info("压缩包 %s 中发现 %d 张图片，开始计算哈希", archive_path.name, total_count)

            # 计算哈希
            cache = HashCache()
            engine = HashEngine(cache, config=cfg)
            hashes = engine.compute_hashes(image_files)

            if not hashes:
                return [], total_count

            # 查找精确重复
            exact_groups = engine.find_exact_duplicates(hashes)
            # 查找感知重复（排除已精确匹配的）
            perceptual_groups = engine.find_perceptual_duplicates(
                hashes,
                threshold=cfg.perceptual_threshold,
                exclude_exact=True,
            )

            all_groups = exact_groups + perceptual_groups

            # 重新编号 group_id
            for idx, group in enumerate(all_groups, start=1):
                group.group_id = idx

            logger.info(
                "压缩包 %s 扫描完成: %d 张图片, %d 组重复",
                archive_path.name, total_count, len(all_groups),
            )
            return all_groups, total_count

        finally:
            try:
                temp_handle.cleanup()
            except Exception as e:
                logger.debug("临时目录清理失败: %s", e)

    def remove_files_from_archive(
        self,
        archive_path: Path,
        files_to_remove: list[str],
    ) -> Path:
        """从压缩包中移除指定文件。

        ZIP 格式：创建新 ZIP（不含待删文件），替换原文件。
        RAR/7z 等格式：解压全部 → 删除文件 → 重新打包为 ZIP，删除原文件。
        返回新压缩包路径。
        """
        archive_path = Path(archive_path)
        suffix = archive_path.suffix.lower()
        remove_set = set(files_to_remove)

        if suffix == ".zip":
            return self._remove_from_zip(archive_path, remove_set)
        else:
            return self._remove_from_other(archive_path, remove_set)

    def save_archive_as(self, archive_path: Path, dest_path: Path) -> Path:
        """将压缩包复制到目标路径。"""
        archive_path = Path(archive_path)
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archive_path, dest_path)
        logger.info("压缩包已保存到: %s", dest_path)
        return dest_path

    def get_today_new_archives(self, folder_path: Path) -> list[Path]:
        """返回指定文件夹中今天修改过的压缩包列表。"""
        folder_path = Path(folder_path)
        if not folder_path.is_dir():
            logger.warning("文件夹不存在: %s", folder_path)
            return []

        today = date.today()
        archives: list[Path] = []

        for f in sorted(folder_path.iterdir()):
            if f.is_file() and f.suffix.lower() in ARCHIVE_FORMATS:
                mtime = date.fromtimestamp(f.stat().st_mtime)
                if mtime == today:
                    archives.append(f)

        logger.info("今日新增/修改的压缩包: %d 个", len(archives))
        return archives

    def _temp_extract(
        self,
        archive_path: Path,
    ) -> tuple[Path, tempfile.TemporaryDirectory]:
        """解压压缩包到临时目录，返回 (解压目录, 临时目录句柄)。

        支持 ZIP / RAR / 7z / tar / gz / bz2 / tgz。
        """
        archive_path = Path(archive_path)
        suffix = archive_path.suffix.lower()
        temp_dir = tempfile.TemporaryDirectory(prefix="imgdedup_archive_")
        extracted = Path(temp_dir.name)

        try:
            if suffix == ".zip":
                with zipfile.ZipFile(archive_path, "r") as zf:
                    zf.extractall(extracted)

            elif suffix == ".rar":
                import rarfile
                with rarfile.RarFile(str(archive_path), "r") as rf:
                    rf.extractall(str(extracted))

            elif suffix == ".7z":
                import py7zr
                with py7zr.SevenZipFile(str(archive_path), mode="r") as sz:
                    sz.extractall(path=str(extracted))

            elif suffix in (".tar", ".gz", ".bz2", ".tgz"):
                import tarfile
                with tarfile.open(str(archive_path), "r:*") as tf:
                    tf.extractall(path=str(extracted), filter="data")

            else:
                logger.warning("不支持的压缩格式: %s", suffix)

        except Exception as e:
            logger.error("解压失败 %s: %s", archive_path, e)
            # 即使解压失败也返回句柄，让调用方统一清理
            raise

        logger.debug("已解压 %s → %s", archive_path.name, extracted)
        return extracted, temp_dir

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _remove_from_zip(self, archive_path: Path, remove_set: set[str]) -> Path:
        """从 ZIP 中移除文件：创建新 ZIP 替换原文件。"""
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip", prefix="imgdedup_repack_")
        try:
            with zipfile.ZipFile(archive_path, "r") as src, \
                 zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as dst:
                for item in src.infolist():
                    if item.filename in remove_set:
                        logger.debug("移除文件: %s", item.filename)
                        continue
                    data = src.read(item.filename)
                    dst.writestr(item, data)

            # 替换原文件
            shutil.move(tmp_path, archive_path)
            logger.info("已从 ZIP 中移除 %d 个文件: %s", len(remove_set), archive_path)
            return archive_path

        except Exception:
            # 清理临时文件
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _remove_from_other(self, archive_path: Path, remove_set: set[str]) -> Path:
        """从 RAR/7z 等格式中移除文件：解压 → 删除 → 重新打包为 ZIP。"""
        extracted_dir, temp_handle = self._temp_extract(archive_path)
        try:
            # 删除指定文件
            for rel_path in remove_set:
                target = extracted_dir / rel_path
                if target.is_file():
                    target.unlink()
                    logger.debug("已删除: %s", rel_path)

            # 重新打包为 ZIP
            new_path = archive_path.with_suffix(".zip")
            with zipfile.ZipFile(new_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in sorted(extracted_dir.rglob("*")):
                    if f.is_file():
                        arcname = str(f.relative_to(extracted_dir))
                        zf.write(f, arcname)

            # 如果原文件不是 .zip，删除原文件
            if archive_path.suffix.lower() != ".zip" and archive_path.exists():
                archive_path.unlink()
                logger.info("已删除原压缩包: %s", archive_path)

            logger.info(
                "已从压缩包中移除 %d 个文件，重新打包为: %s",
                len(remove_set), new_path,
            )
            return new_path

        finally:
            try:
                temp_handle.cleanup()
            except Exception as e:
                logger.debug("临时目录清理失败: %s", e)
