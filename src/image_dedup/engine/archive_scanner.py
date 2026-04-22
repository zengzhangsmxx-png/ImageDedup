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
        keep_temp: bool = False,
    ) -> tuple[list[DuplicateGroup], int] | tuple[list[DuplicateGroup], int, tempfile.TemporaryDirectory]:
        """扫描压缩包/文档/文件夹内的图片。

        支持：压缩包(.zip/.rar/.7z等)、文档(.xlsx/.xls/.pdf)、文件夹
        keep_temp=False: 返回 (重复组列表, 文件总数)，自动清理临时目录。
        keep_temp=True: 返回 (重复组列表, 文件总数, 临时目录句柄)，调用方负责清理。
        """
        archive_path = Path(archive_path)
        cfg = config or self._config

        if archive_path.is_dir():
            return self._scan_directory(archive_path, cfg, keep_temp)

        if not archive_path.is_file():
            logger.error("文件不存在: %s", archive_path)
            return ([], 0, None) if keep_temp else ([], 0)

        # 文档格式直接交给 Scanner 处理（它支持 xlsx/pdf）
        DOCUMENT_FORMATS = {".xlsx", ".xls", ".pdf"}
        if archive_path.suffix.lower() in DOCUMENT_FORMATS:
            return self._scan_document(archive_path, cfg, keep_temp)

        extracted_dir, temp_handle = self._temp_extract(archive_path)
        try:
            scanner = Scanner()
            try:
                image_files = scanner.scan([extracted_dir])
            finally:
                scanner.cleanup()

            all_groups, total_count = self._scan_dedup(image_files, cfg, archive_path.name)

            if total_count == 0:
                if not keep_temp:
                    temp_handle.cleanup()
                return ([], 0, temp_handle) if keep_temp else ([], 0)

            if not keep_temp:
                try:
                    temp_handle.cleanup()
                except Exception as e:
                    logger.debug("临时目录清理失败: %s", e)
                return all_groups, total_count

            return all_groups, total_count, temp_handle

        except Exception:
            try:
                temp_handle.cleanup()
            except Exception as e:
                logger.debug("临时目录清理失败: %s", e)
            raise

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
        """返回指定文件夹中今天修改过的压缩包、文档和子文件夹列表。

        递归扫描所有子文件夹，收集今日新增/修改的对象。
        支持：压缩包、.xlsx/.xls/.pdf 文档、今日修改的子文件夹。
        """
        folder_path = Path(folder_path)
        if not folder_path.is_dir():
            logger.warning("文件夹不存在: %s", folder_path)
            return []

        today = date.today()
        results: list[Path] = []
        DOCUMENT_FORMATS = {".xlsx", ".xls", ".pdf"}

        def scan_recursive(path: Path):
            """递归扫描目录，收集今日新增的文件和文件夹。"""
            try:
                for item in sorted(path.iterdir()):
                    try:
                        if item.is_file():
                            # 检查压缩包和文档
                            if item.suffix.lower() in ARCHIVE_FORMATS or item.suffix.lower() in DOCUMENT_FORMATS:
                                mtime = date.fromtimestamp(item.stat().st_mtime)
                                if mtime == today:
                                    results.append(item)
                        elif item.is_dir():
                            # 检查文件夹修改时间
                            mtime = date.fromtimestamp(item.stat().st_mtime)
                            if mtime == today:
                                results.append(item)
                            # 递归扫描子文件夹
                            scan_recursive(item)
                    except (PermissionError, OSError):
                        # 静默跳过无权限访问的文件/文件夹
                        pass
                    except Exception:
                        # 静默跳过其他错误
                        pass
            except (PermissionError, OSError):
                # 静默跳过无权限访问的目录
                pass
            except Exception:
                # 静默跳过其他错误
                pass

        scan_recursive(folder_path)
        logger.info("今日新增/修改的对象: %d 个", len(results))
        return results

    def _scan_dedup(self, image_files, cfg, source_name: str):
        """通用查重流程：计算哈希 → 精确匹配 → 感知匹配。"""
        total_count = len(image_files)
        if total_count == 0:
            return [], 0

        logger.info("%s 中发现 %d 张图片，开始计算哈希", source_name, total_count)

        cache = HashCache()
        engine = HashEngine(cache, config=cfg)
        hashes = engine.compute_hashes(image_files)

        if not hashes:
            return [], total_count

        exact_groups = engine.find_exact_duplicates(hashes)
        perceptual_groups = engine.find_perceptual_duplicates(
            hashes,
            threshold=cfg.perceptual_threshold,
            exclude_exact=True,
        )

        all_groups = exact_groups + perceptual_groups
        for idx, group in enumerate(all_groups, start=1):
            group.group_id = idx

        logger.info("%s 扫描完成: %d 张图片, %d 组重复", source_name, total_count, len(all_groups))
        return all_groups, total_count

    def _scan_directory(self, dir_path: Path, cfg, keep_temp: bool):
        """扫描文件夹内的图片查重。"""
        scanner = Scanner()
        try:
            image_files = scanner.scan([dir_path])
        finally:
            scanner.cleanup()

        all_groups, total_count = self._scan_dedup(image_files, cfg, dir_path.name)
        return (all_groups, total_count, None) if keep_temp else (all_groups, total_count)

    def _scan_document(self, doc_path: Path, cfg, keep_temp: bool):
        """扫描文档（xlsx/pdf）内的图片查重。"""
        scanner = Scanner()
        try:
            image_files = scanner.scan([doc_path])
        finally:
            scanner.cleanup()

        all_groups, total_count = self._scan_dedup(image_files, cfg, doc_path.name)
        return (all_groups, total_count, None) if keep_temp else (all_groups, total_count)

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
