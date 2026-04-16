"""HTML report generator — self-contained report with base64 thumbnails."""

from __future__ import annotations

import base64
import io
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from PIL import Image

from ..engine.hasher import DuplicateGroup

_METHOD_LABELS = {
    "exact": "精准匹配 (MD5)",
    "perceptual": "感知哈希",
    "feature": "特征匹配 (ORB)",
}


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _shorten_path(path: str, max_len: int = 50) -> str:
    if len(path) <= max_len:
        return path
    return "..." + path[-(max_len - 3):]


class ReportGenerator:
    def __init__(self, thumbnail_size: tuple[int, int] = (150, 150)):
        self._thumb_size = thumbnail_size
        templates_dir = Path(__file__).parent / "templates"
        self._env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=True,
        )

    def _image_to_base64(self, path: str) -> str:
        try:
            img = Image.open(path)
            img.thumbnail(self._thumb_size, Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            fmt = "PNG" if img.mode == "RGBA" else "JPEG"
            img.save(buf, format=fmt, quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            mime = "image/png" if fmt == "PNG" else "image/jpeg"
            return f"data:{mime};base64,{b64}"
        except Exception:
            return ""

    def generate(
        self,
        groups: list[DuplicateGroup],
        output_path: str | Path,
        title: str = "图片查重报告",
    ) -> Path:
        output_path = Path(output_path)

        # Build summary
        method_counts: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
        for g in groups:
            m = g.detection_method
            cnt, files = method_counts.get(m, (0, 0))
            method_counts[m] = (cnt + 1, files + len(g.files))

        summary = []
        for method in ("exact", "perceptual", "feature"):
            if method in method_counts:
                cnt, files = method_counts[method]
                summary.append((method, _METHOD_LABELS.get(method, method), cnt, files))

        # Build group data
        total_files = 0
        rendered_groups = []
        for g in groups:
            files_data = []
            for f in g.files:
                total_files += 1
                files_data.append({
                    "name": Path(f.file_path).name,
                    "path": f.file_path,
                    "path_short": _shorten_path(f.file_path),
                    "size_human": _human_size(f.file_size),
                    "dimensions": f"{f.width}x{f.height}",
                    "thumbnail_b64": self._image_to_base64(f.file_path),
                })
            rendered_groups.append({
                "id": g.group_id,
                "method": g.detection_method,
                "method_label": _METHOD_LABELS.get(g.detection_method, g.detection_method),
                "similarity": f"{g.similarity_score * 100:.1f}",
                "files": files_data,
            })

        template = self._env.get_template("report.html")
        html = template.render(
            title=title,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            groups=rendered_groups,
            total_files=total_files,
            summary=summary,
        )

        output_path.write_text(html, encoding="utf-8")
        return output_path.resolve()
