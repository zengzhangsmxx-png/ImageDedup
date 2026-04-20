"""File discovery — walks directories, extracts ZIP/Excel/PDF archives."""

from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..logging_setup import get_logger

logger = get_logger("scanner")

SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
DOCUMENT_FORMATS = {".xlsx", ".xls", ".pdf"}


@dataclass
class ImageFile:
    path: Path
    original_path: Path
    file_size: int
    format: str
    source_type: str  # "folder", "file", "archive", "document"
    source_group: str | None = None


class Scanner:
    def __init__(self):
        self._temp_dirs: list[tempfile.TemporaryDirectory] = []

    def scan(self, paths: list[str | Path], errors=None) -> list[ImageFile]:
        results: list[ImageFile] = []
        seen: set[str] = set()
        for p in paths:
            p = Path(p)
            if p.is_dir():
                results.extend(self._walk_directory(p, seen))
            elif p.is_file():
                suffix = p.suffix.lower()
                if suffix in (".zip",):
                    results.extend(self._extract_archive(p, seen, errors))
                elif suffix in DOCUMENT_FORMATS:
                    results.extend(self._extract_document(p, seen, errors))
                elif suffix in SUPPORTED_FORMATS:
                    rp = str(p.resolve())
                    if rp not in seen:
                        seen.add(rp)
                        results.append(ImageFile(
                            path=p.resolve(), original_path=p,
                            file_size=p.stat().st_size,
                            format=suffix.lstrip("."),
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

    def _extract_archive(self, archive_path: Path, seen: set[str], errors=None) -> list[ImageFile]:
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
        except zipfile.BadZipFile as e:
            logger.warning("Bad zip file: %s", archive_path)
            if errors:
                errors.add(str(archive_path), "scan", e)
        except Exception as e:
            logger.warning("Archive extraction failed %s: %s", archive_path, e)
            if errors:
                errors.add(str(archive_path), "scan", e)
        return results

    def _extract_document(self, doc_path: Path, seen: set[str], errors=None) -> list[ImageFile]:
        suffix = doc_path.suffix.lower()
        if suffix in (".xlsx", ".xls"):
            return self._extract_xlsx(doc_path, seen, errors)
        elif suffix == ".pdf":
            return self._extract_pdf(doc_path, seen, errors)
        return []

    def _extract_xlsx(self, doc_path: Path, seen: set[str], errors=None) -> list[ImageFile]:
        results = []
        td = tempfile.TemporaryDirectory(prefix="imgdedup_xlsx_")
        self._temp_dirs.append(td)
        try:
            from openpyxl import load_workbook
            wb = load_workbook(str(doc_path), data_only=True)
            img_idx = 0
            for ws in wb.worksheets:
                for img in ws._images:
                    img_idx += 1
                    ext = getattr(img, "format", "png") or "png"
                    out_path = Path(td.name) / f"img_{img_idx}.{ext}"
                    data = img._data()
                    if not data:
                        continue
                    out_path.write_bytes(data)
                    rp = str(out_path.resolve())
                    if rp not in seen:
                        seen.add(rp)
                        results.append(ImageFile(
                            path=out_path.resolve(),
                            original_path=doc_path / f"img_{img_idx}.{ext}",
                            file_size=out_path.stat().st_size,
                            format=ext,
                            source_type="document",
                            source_group=str(doc_path),
                        ))
            wb.close()
        except Exception as e:
            logger.warning("XLSX extraction failed %s: %s", doc_path, e)
            if errors:
                errors.add(str(doc_path), "scan", e)
        return results

    def _extract_pdf(self, doc_path: Path, seen: set[str], errors=None) -> list[ImageFile]:
        results = []
        td = tempfile.TemporaryDirectory(prefix="imgdedup_pdf_")
        self._temp_dirs.append(td)
        try:
            import fitz
            doc = fitz.open(str(doc_path))
            img_idx = 0
            for page_idx in range(len(doc)):
                for img_info in doc.get_page_images(page_idx, full=True):
                    xref = img_info[0]
                    try:
                        pix = fitz.Pixmap(doc, xref)
                        if pix.n > 4:
                            pix = fitz.Pixmap(fitz.csRGB, pix)
                        img_idx += 1
                        out_path = Path(td.name) / f"page{page_idx + 1}_img{img_idx}.png"
                        pix.save(str(out_path))
                        rp = str(out_path.resolve())
                        if rp not in seen:
                            seen.add(rp)
                            results.append(ImageFile(
                                path=out_path.resolve(),
                                original_path=doc_path / f"page{page_idx + 1}_img{img_idx}.png",
                                file_size=out_path.stat().st_size,
                                format="png",
                                source_type="document",
                                source_group=str(doc_path),
                            ))
                    except Exception as e:
                        logger.debug("PDF image skip xref=%d in %s: %s", xref, doc_path, e)
                        continue
            doc.close()
        except Exception as e:
            logger.warning("PDF extraction failed %s: %s", doc_path, e)
            if errors:
                errors.add(str(doc_path), "scan", e)
        return results

    def cleanup(self):
        for td in self._temp_dirs:
            try:
                td.cleanup()
            except Exception as e:
                logger.debug("Temp cleanup: %s", e)
        self._temp_dirs.clear()
