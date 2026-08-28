"""Render resources/document_print.md as resources/document.pdf.

The input is the print-formatted variant of the readme: numbered plain-text
headings, code indented by four spaces, and pipe tables. Those three shapes map
directly onto PDF flowables, so no markdown parser is needed.
"""

import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

SOURCE = Path("resources/document_print.md")
OUTPUT = Path("resources/document.pdf")

HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.\s+(\S.*)$")
# Exactly two leading spaces, so a four-space code line can never match.
LIST_ITEM = re.compile(r"^ {2}(\d+\.|-)\s+(.*)$")
PAGE_MARGIN = 18 * mm
CONTENT_WIDTH = A4[0] - 2 * PAGE_MARGIN

_styles = getSampleStyleSheet()
TITLE = ParagraphStyle(
    "DocTitle", parent=_styles["Title"], fontSize=20, spaceAfter=14, alignment=0
)
H1 = ParagraphStyle(
    "H1", parent=_styles["Heading1"], fontSize=14, spaceBefore=16, spaceAfter=6
)
H2 = ParagraphStyle(
    "H2", parent=_styles["Heading2"], fontSize=11.5, spaceBefore=12, spaceAfter=5
)
BODY = ParagraphStyle(
    "Body", parent=_styles["BodyText"], fontSize=9.5, leading=13.5, spaceAfter=7
)
CODE = ParagraphStyle(
    "Code",
    parent=_styles["Code"],
    fontSize=7.6,
    leading=9.6,
    leftIndent=8,
    textColor=colors.HexColor("#1f2933"),
)
LIST = ParagraphStyle(
    "List", parent=BODY, leftIndent=20, bulletIndent=6, spaceAfter=4
)
CELL = ParagraphStyle("Cell", parent=BODY, fontSize=8.2, leading=10.8, spaceAfter=0)
CELL_HEAD = ParagraphStyle("CellHead", parent=CELL, fontName="Helvetica-Bold")


def _split_row(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_divider(cells):
    return all(set(cell) <= {"-", ":"} and cell for cell in cells)


def _table(rows):
    header, *body = rows
    columns = len(header)
    data = [[Paragraph(escape(cell), CELL_HEAD) for cell in header]]
    for row in body:
        # Pad or trim so a malformed row cannot break the grid.
        row = (row + [""] * columns)[:columns]
        data.append([Paragraph(escape(cell), CELL) for cell in row])

    # Give the first column a fixed share and split the rest evenly.
    first = CONTENT_WIDTH * (0.28 if columns > 1 else 1.0)
    rest = (CONTENT_WIDTH - first) / (columns - 1) if columns > 1 else 0
    widths = [first] + [rest] * (columns - 1)

    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c2cc")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf2")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def build_flowables(text):
    lines = text.splitlines()
    flowables = []
    paragraph = []
    index = 0
    seen_title = False

    def flush_paragraph():
        if paragraph:
            flowables.append(Paragraph(escape(" ".join(paragraph)), BODY))
            paragraph.clear()

    while index < len(lines):
        line = lines[index]

        if not line.strip():
            flush_paragraph()
            index += 1
            continue

        if LIST_ITEM.match(line):
            flush_paragraph()
            items = []
            while index < len(lines) and lines[index].startswith("  ") and lines[index].strip():
                item = LIST_ITEM.match(lines[index])
                if item:
                    items.append([item.group(1), item.group(2).strip()])
                else:
                    items[-1][1] += " " + lines[index].strip()
                index += 1
            for marker, body in items:
                bullet = "\u2022" if marker == "-" else marker
                flowables.append(Paragraph(escape(body), LIST, bulletText=bullet))
            flowables.append(Spacer(1, 6))
            continue

        if line.startswith("    "):
            flush_paragraph()
            block = []
            while index < len(lines) and (
                lines[index].startswith("    ") or not lines[index].strip()
            ):
                block.append(lines[index][4:])
                index += 1
            while block and not block[-1].strip():
                block.pop()
            # Preformatted takes raw text; escaping here would show entities.
            flowables.append(Preformatted("\n".join(block), CODE))
            flowables.append(Spacer(1, 8))
            continue

        if line.lstrip().startswith("|"):
            flush_paragraph()
            rows = []
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                cells = _split_row(lines[index])
                if not _is_divider(cells):
                    rows.append(cells)
                index += 1
            if rows:
                flowables.append(_table(rows))
                flowables.append(Spacer(1, 10))
            continue

        heading = HEADING.match(line)
        if heading:
            flush_paragraph()
            number, title = heading.groups()
            style = H1 if "." not in number else H2
            flowables.append(Paragraph(escape(f"{number}. {title}"), style))
            index += 1
            continue

        if not seen_title:
            flush_paragraph()
            flowables.append(Paragraph(escape(line.strip()), TITLE))
            seen_title = True
            index += 1
            continue

        paragraph.append(line.strip())
        index += 1

    flush_paragraph()
    return flowables


def main():
    if not SOURCE.exists():
        raise FileNotFoundError(f"The file {SOURCE} does not exist.")

    document = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
        title="Migrate VSession Server Script",
    )
    document.build(build_flowables(SOURCE.read_text(encoding="utf-8")))
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
