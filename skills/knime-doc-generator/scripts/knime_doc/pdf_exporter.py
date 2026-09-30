"""
Renders documentation Markdown into a styled PDF with ReportLab.

ReportLab is used rather than an HTML-to-PDF engine because it is preinstalled
in Claude's sandbox and needs no system libraries — WeasyPrint and wkhtmltopdf
both depend on Pango or Qt, which cannot be installed there. Layout is built
directly from the block list `markdown.parse_blocks()` produces.
"""

from datetime import datetime
from typing import Any

from knime_doc.markdown import (
    Block,
    CodeBlock,
    Heading,
    ListBlock,
    ParagraphBlock,
    TableBlock,
    clean_markdown,
    inline_to_rl,
    parse_blocks,
    to_plain_text,
)
from knime_doc.style import (
    ACCENT,
    BODY,
    BODY_FONT,
    BODY_FONT_BOLD,
    CODE_BG,
    CODE_FONT,
    DISCLAIMER,
    DISCLAIMER_TEXT,
    MUTED,
    RULE,
    format_generated_date,
)

_BULLET_CHARS = ["•", "◦", "–"]  # bullet, white bullet, en dash


def _styles() -> dict[str, Any]:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle

    base = ParagraphStyle(
        "body",
        fontName=BODY_FONT,
        fontSize=10.5,
        leading=15,
        textColor=HexColor(BODY),
        alignment=TA_LEFT,
        spaceAfter=7,
    )
    return {
        "body": base,
        "title": ParagraphStyle(
            "title",
            parent=base,
            fontName=BODY_FONT_BOLD,
            fontSize=22,
            leading=26,
            textColor=HexColor(ACCENT),
            spaceAfter=2,
        ),
        "meta": ParagraphStyle(
            "meta", parent=base, fontSize=9, leading=12, textColor=HexColor(MUTED), spaceAfter=1
        ),
        "disclaimer": ParagraphStyle(
            "disclaimer", parent=base, fontSize=9, leading=12, textColor=HexColor(DISCLAIMER), spaceAfter=16
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base,
            fontName=BODY_FONT_BOLD,
            fontSize=14.5,
            leading=18,
            textColor=HexColor(ACCENT),
            spaceBefore=14,
            spaceAfter=3,
        ),
        "h3": ParagraphStyle(
            "h3",
            parent=base,
            fontName=BODY_FONT_BOLD,
            fontSize=12,
            leading=15,
            textColor=HexColor(ACCENT),
            spaceBefore=10,
            spaceAfter=3,
        ),
        "item": ParagraphStyle("item", parent=base, spaceAfter=3),
        "cell": ParagraphStyle("cell", parent=base, fontSize=9.5, leading=12.5, spaceAfter=0),
        "cellhead": ParagraphStyle(
            "cellhead", parent=base, fontName=BODY_FONT_BOLD, fontSize=9.5, leading=12.5, spaceAfter=0
        ),
        "code": ParagraphStyle(
            "code",
            parent=base,
            fontName=CODE_FONT,
            fontSize=9,
            leading=12,
            backColor=HexColor(CODE_BG),
            borderPadding=6,
            spaceBefore=4,
            spaceAfter=10,
        ),
    }


def _rule_flowable() -> Any:
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import HRFlowable

    return HRFlowable(width="100%", thickness=0.7, color=HexColor(ACCENT), spaceBefore=1, spaceAfter=8)


def _build_table(block: TableBlock, styles: dict[str, Any], avail_width: float) -> Any:
    from reportlab.lib.colors import HexColor, white
    from reportlab.platypus import Paragraph, Table, TableStyle

    header = [Paragraph(inline_to_rl(c, CODE_FONT), styles["cellhead"]) for c in block.header]
    body = [[Paragraph(inline_to_rl(c, CODE_FONT), styles["cell"]) for c in row] for row in block.rows]

    # Normalize ragged rows so ReportLab does not raise on a short row.
    width = len(block.header)
    for row in body:
        while len(row) < width:
            row.append(Paragraph("", styles["cell"]))
        del row[width:]

    table = Table([header, *body], colWidths=[avail_width / width] * width, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HexColor(ACCENT)),
                ("TEXTCOLOR", (0, 0), (-1, 0), white),
                ("GRID", (0, 0), (-1, -1), 0.5, HexColor(RULE)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _flowables(blocks: list[Block], styles: dict[str, Any], avail_width: float) -> list[Any]:
    from reportlab.platypus import Paragraph, Spacer

    out: list[Any] = []
    for block in blocks:
        if isinstance(block, Heading):
            key = "h2" if block.level <= 2 else "h3"
            out.append(Paragraph(inline_to_rl(block.text, CODE_FONT), styles[key]))
            if block.level <= 2:
                out.append(_rule_flowable())
        elif isinstance(block, ParagraphBlock):
            out.append(Paragraph(inline_to_rl(block.text, CODE_FONT), styles["body"]))
        elif isinstance(block, ListBlock):
            counter = 0
            for item in block.items:
                if block.ordered and item.depth == 0:
                    counter += 1
                    marker = f"{counter}."
                else:
                    marker = _BULLET_CHARS[min(item.depth, len(_BULLET_CHARS) - 1)]
                style = styles["item"].clone(f"item{item.depth}")
                style.leftIndent = 14 + item.depth * 14
                style.bulletIndent = 2 + item.depth * 14
                out.append(
                    Paragraph(inline_to_rl(item.text, CODE_FONT), style, bulletText=marker)
                )
            out.append(Spacer(1, 5))
        elif isinstance(block, TableBlock):
            out.append(_build_table(block, styles, avail_width))
            out.append(Spacer(1, 10))
        elif isinstance(block, CodeBlock):
            for line in block.text.split("\n") or [""]:
                out.append(Paragraph(to_plain_text(line).replace(" ", "&nbsp;") or "&nbsp;", styles["code"]))
    return out


def build_pdf(workflow_name: str, generated_at: datetime, markdown: str) -> bytes:
    """Render the document and return the PDF bytes.

    ReportLab is imported here rather than at module import time so a missing
    install surfaces as export_pdf.py's actionable message.
    """
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    styles = _styles()
    margin = 2.0 * cm
    avail_width = A4[0] - 2 * margin

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=2.2 * cm,
        bottomMargin=2.2 * cm,
        title=workflow_name or "Documentation",
        author="KNIME Doc Generator",
    )

    story: list[Any] = [
        Paragraph(inline_to_rl(workflow_name or "Documentation", CODE_FONT), styles["title"]),
        Paragraph(f"Generated: {format_generated_date(generated_at)}", styles["meta"]),
        Paragraph(DISCLAIMER_TEXT, styles["disclaimer"]),
    ]
    story += _flowables(parse_blocks(clean_markdown(markdown)), styles, avail_width)

    doc.build(story)
    return buffer.getvalue()
