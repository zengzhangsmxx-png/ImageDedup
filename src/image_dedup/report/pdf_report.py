"""PDF report generator — A4 document with summary and detail tables."""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..engine.hasher import DuplicateGroup

_METHOD_LABELS = {
    "exact": "精准匹配",
    "perceptual": "感知哈希",
    "feature": "特征匹配",
    "video": "视频查重",
    "semantic": "AI语义",
}

# ── font registration ────────────────────────────────────────

_CN_FONT = "Helvetica"  # fallback


def _register_chinese_font() -> str:
    """Try to register a Chinese-capable font; return the font name."""
    candidates = [
        # macOS
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        # Linux
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        # Windows
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ]
    for font_path in candidates:
        if os.path.isfile(font_path):
            try:
                pdfmetrics.registerFont(TTFont("ChineseFont", font_path))
                return "ChineseFont"
            except Exception:
                continue
    return "Helvetica"


_CN_FONT = _register_chinese_font()


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# ── styles ───────────────────────────────────────────────────

def _build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "CNTitle",
            parent=base["Title"],
            fontName=_CN_FONT,
            fontSize=18,
            leading=24,
            alignment=1,  # center
        ),
        "heading": ParagraphStyle(
            "CNHeading",
            parent=base["Heading2"],
            fontName=_CN_FONT,
            fontSize=13,
            leading=18,
            spaceBefore=12,
        ),
        "body": ParagraphStyle(
            "CNBody",
            parent=base["Normal"],
            fontName=_CN_FONT,
            fontSize=9,
            leading=12,
        ),
    }


_HEADER_BG = colors.HexColor("#4CAF50")
_HEADER_TEXT = colors.white
_GREEN_BG = colors.HexColor("#E8F5E9")

_TABLE_STYLE_BASE = [
    ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
    ("TEXTCOLOR", (0, 0), (-1, 0), _HEADER_TEXT),
    ("FONTNAME", (0, 0), (-1, 0), _CN_FONT),
    ("FONTSIZE", (0, 0), (-1, 0), 9),
    ("FONTNAME", (0, 1), (-1, -1), _CN_FONT),
    ("FONTSIZE", (0, 1), (-1, -1), 8),
    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ("TOPPADDING", (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
]


class PDFReportGenerator:
    """Generate a PDF duplicate report."""

    def generate(
        self,
        groups: list[DuplicateGroup],
        output_path: str | Path,
    ) -> Path:
        output_path = Path(output_path)
        styles = _build_styles()

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )

        story: list = []

        # title
        story.append(Paragraph("图片查重报告", styles["title"]))
        story.append(Spacer(1, 10 * mm))

        # summary
        story.append(Paragraph("概览", styles["heading"]))
        story.append(Spacer(1, 3 * mm))
        story.extend(self._build_summary_table(groups))
        story.append(Spacer(1, 8 * mm))

        # details
        story.append(Paragraph("详细结果", styles["heading"]))
        story.append(Spacer(1, 3 * mm))
        story.extend(self._build_detail_elements(groups, styles))

        doc.build(story)
        return output_path.resolve()

    # ── builders ─────────────────────────────────────────────

    @staticmethod
    def _build_summary_table(groups: list[DuplicateGroup]) -> list:
        method_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for g in groups:
            mc = method_counts[g.detection_method]
            mc[0] += 1
            mc[1] += len(g.files)

        data = [["检测方法", "重复组数", "涉及文件数"]]
        for method in ("exact", "perceptual", "feature", "video", "semantic"):
            if method not in method_counts:
                continue
            cnt, files = method_counts[method]
            data.append([_METHOD_LABELS.get(method, method), str(cnt), str(files)])

        if len(data) == 1:
            return []

        table = Table(data, colWidths=[120, 80, 80])
        table.setStyle(TableStyle(_TABLE_STYLE_BASE))
        return [table]

    @staticmethod
    def _build_detail_elements(
        groups: list[DuplicateGroup],
        styles: dict[str, ParagraphStyle],
    ) -> list:
        elements: list = []

        for idx, g in enumerate(groups):
            label = _METHOD_LABELS.get(g.detection_method, g.detection_method)
            similarity = f"{g.similarity_score * 100:.1f}%"
            header_text = f"组 {g.group_id}　|　{label}　|　相似度 {similarity}"
            elements.append(Paragraph(header_text, styles["body"]))
            elements.append(Spacer(1, 2 * mm))

            data = [["文件名", "文件路径", "文件大小", "尺寸(宽x高)"]]
            for f in g.files:
                data.append([
                    Path(f.file_path).name,
                    f.file_path,
                    _human_size(f.file_size),
                    f"{f.width}x{f.height}",
                ])

            col_widths = [100, 260, 60, 70]
            table = Table(data, colWidths=col_widths)

            style_cmds = list(_TABLE_STYLE_BASE)
            style_cmds.append(("ALIGN", (1, 1), (1, -1), "LEFT"))
            # alternating row colors per group
            if idx % 2 == 0:
                style_cmds.append(("BACKGROUND", (0, 1), (-1, -1), _GREEN_BG))

            table.setStyle(TableStyle(style_cmds))
            elements.append(table)
            elements.append(Spacer(1, 5 * mm))

        return elements
