"""File discovery — walks directories, extracts ZIP archives."""

from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}


@dataclass
class ImageFile:
    path: Path
    original_path: Path
    file_size: int
    format: str
    source_type: str  # "folder", "file", "archive"


class Scanner:
    def __init__(self):
        self._temp_dirs: list[tempfile.TemporaryDirectory] = []

    def scan(self, paths: list[str | Path]) -> list[ImageFile]:
        results: list[ImageFile] = []
        seen: set[str] = set()
        for p in paths:
            p = Path(p)
            if p.is_dir():
                results.extend(self._walk_directory(p, seen))
            elif p.is_file():
                if p.suffix.lower() in (".zip",):
                    results.extend(self._extract_archive(p, seen))
                elif p.suffix.lower() in SUPPORTED_FORMATS:
                    rp = str(p.resolve())
                    if rp not in seen:
                        seen.add(rp)
                        results.append(ImageFile(
                            path=p.resolve(), original_path=p,
                            file_size=p.stat().st_size,
                            format=p.suffix.lower().lstrip("."),
                            source_type="file",
                        ))
        return results

    def _walk_directory(self, directory: Path, seen: set[str]) -> list[ImageFile]:
        results = []
        for f in sorted(directory.rglob("*")):
            if f.is_file() and f.suffix.lower() in SUPPORTED_FORMATS:
                rp = str(f.resolve())
                if rp not in seen:
                    seen.add(rp)
                    results.append(ImageFile(
                        path=f.resolve(), original_path=f,
                        file_size=f.stat().st_size,
                        format=f.suffix.lower().lstrip("."),
                        source_type="folder",
                    ))
        return results

    def _extract_archive(self, archive_path: Path, seen: set[str]) -> list[ImageFile]:
        results = []
        td = tempfile.TemporaryDirectory(prefix="imgdedup_")
        self._temp_dirs.append(td)
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(td.name)
            extract_dir = Path(td.name)
            for f in sorted(extract_dir.rglob("*")):
                if f.is_file() and f.suffix.lower() in SUPPORTED_FORMATS:
                    rp = str(f.resolve())
                    if rp not in seen:
                        seen.add(rp)
                        results.append(ImageFile(
                            path=f.resolve(), original_path=archive_path / f.relative_to(extract_dir),
                            file_size=f.stat().st_size,
                            format=f.suffix.lower().lstrip("."),
                            source_type="archive",
                        ))
        except zipfile.BadZipFile:
            pass
        return results

    def cleanup(self):
        for td in self._temp_dirs:
            try:
                td.cleanup()
            except Exception:
                pass
        self._temp_dirs.clear()
