"""Baseline chunker for the "failed RAG" demo, plus structure-aware chunking.

`chunk_pages` is naive character chunking. `chunk_by_structure` splits on
document headings and keeps tables and fenced code intact. It accepts both
markdown (`##` headings) and the print PDF (`1. Purpose`, `4.1 Vonage To
OpenVidu`) after pypdf extraction.
"""

import re
from typing import List


def chunk_pages(pages: List[str], chunk_size: int = 200, chunk_overlap: int = 0) -> List[str]:
    # No separator between sections, so the tail of one section fuses with the
    # heading of the next.
    full_text = "".join(pages)

    # Newlines are what carry the markdown structure (headings, table rows,
    # code fences); collapsing them leaves undifferentiated prose.
    full_text = " ".join(full_text.split())

    chunks: List[str] = []
    if not full_text:
        return chunks

    step = max(1, chunk_size - chunk_overlap)
    for start in range(0, len(full_text), step):
        # Cut on the raw offset: no word, sentence, or line boundary respected.
        chunks.append(full_text[start:start + chunk_size])

    return chunks


def chunk_by_structure(pages: List[str]) -> List[str]:
    """Split on document structure and keep tables and fenced code intact.

    Works for both the markdown source and the print PDF extracted by
    pypdf. PDF headings look like ``1. Purpose`` / ``4.1 Vonage To OpenVidu``
    rather than ``##`` / ``###``. Each section is one chunk; subsections keep
    the parent heading so hybrid search still sees the surrounding topic.
    """
    # Reassemble pages. PDF extract_text() already inserts newlines; joining
    # with a single newline keeps a heading at the end of one page attached
    # to the body that starts on the next (e.g. "8. Usage" then the commands).
    text = "\n".join(page for page in pages if page).strip()
    if not text:
        return []

    lines = text.splitlines()

    # First non-heading line is the document title (PDF: "Migrate VSession
    # Server Script"). Kept as a parent on every chunk.
    doc_title = ""
    if lines and _structure_heading(lines[0]) is None:
        doc_title = lines[0].strip()
        lines = lines[1:]

    # Pass 1: group lines into atomic blocks. A table or fenced code block
    # must stay one unit so later heading splits cannot cut a row or a fence
    # in half (the failure mode of character chunking).
    blocks: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Opening fence (``` / ```python / ```bash). Consume until the
        # matching closer so inner "|" or "#" lines are not treated as
        # tables or headings.
        if line.startswith("```"):
            fence = [line]
            i += 1
            while i < len(lines):
                fence.append(lines[i])
                if lines[i].startswith("```"):
                    i += 1
                    break
                i += 1
            blocks.append("\n".join(fence))
            continue

        # Markdown table: consecutive lines that start with "|". Keep the
        # header, divider, and every data row in the same block.
        if line.lstrip().startswith("|"):
            table = [line]
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                table.append(lines[i])
                i += 1
            blocks.append("\n".join(table))
            continue

        # Ordinary line (heading, paragraph, list item, code, blank).
        blocks.append(line)
        i += 1

    # Pass 2: emit one chunk per heading section. heading_stack is the
    # breadcrumb of parent titles, e.g. ["3. CLI Arguments", "3.1 Client
    # Emails Resolution"], so a 3.1 chunk still carries the CLI topic.
    chunks: List[str] = []
    current: List[str] = []
    heading_stack: List[str] = []

    def flush() -> None:
        """Commit the current section if it has body text, not just a title."""
        body = "\n".join(current).strip()
        # Skip heading-only chunks (a numbered title immediately followed by
        # a subsection, or a markdown H1 with no prose).
        has_body = any(
            line.strip()
            and line.strip() != doc_title
            and _structure_heading(line) is None
            and not line.strip().startswith("#")
            for line in body.splitlines()
        )
        if body and has_body:
            chunks.append(body)
        current.clear()

    for block in blocks:
        heading = _structure_heading(block)
        if heading is None:
            current.append(block)
            continue

        flush()
        level, title = heading

        # Drop headings at this level or deeper so a new "4." replaces the
        # previous "3." (and any "3.1" under it), while keeping the parent.
        heading_stack = heading_stack[: level - 1]
        heading_stack.append(title)
        path = ([doc_title] if doc_title else []) + heading_stack
        current.append("\n".join(path))

    flush()
    return chunks


def _structure_heading(block: str) -> tuple[int, str] | None:
    """Detect a markdown ATX heading or a PDF numbered section title."""
    stripped = block.strip()
    markdown = _markdown_heading(stripped)
    if markdown is not None:
        return markdown
    return _numbered_heading(stripped)


def _markdown_heading(block: str) -> tuple[int, str] | None:
    """Return (level, full_heading_line) if block is a markdown ATX heading."""
    if not block.startswith("#"):
        return None
    hashes, _, title = block.partition(" ")
    if hashes.strip("#") != "" or not title:
        return None
    # A single "#" in PDF-extracted Python is a comment (`# log planned...`),
    # not an H1. Real markdown H1s use Title Case.
    if len(hashes) == 1 and not title[:1].isupper():
        return None
    return len(hashes), block


def _numbered_heading(block: str) -> tuple[int, str] | None:
    """Return (level, line) for PDF titles like '2. Eligibility Filters'.

    Print-PDF titles are ``1. Purpose`` (dot then space) or ``3.1 Client``
    (no extra dot after the subsection number). Numbered lists such as
    ``1. A banner showing...`` must not count as headings.
    """
    subsection = re.match(r"^(\d+(?:\.\d+)+)\s+(\S.*)$", block)
    if subsection:
        number, title = subsection.groups()
        if _looks_like_numbered_list(title):
            return None
        return number.count(".") + 1, block

    top = re.match(r"^(\d+)\.\s+(\S.*)$", block)
    if not top:
        return None
    _, title = top.groups()
    if _looks_like_numbered_list(title):
        return None
    return 1, block


def _looks_like_numbered_list(title: str) -> bool:
    if "," in title or len(title) > 55:
        return True
    if title[:1].islower():
        return True
    return title.split()[0] in {"A", "An", "The", "When", "Then", "One", "Within"}


if __name__ == "__main__":
    from pdfreader import read_pdf

    pages = read_pdf("./resources/document.pdf")
    preview = chunk_by_structure(pages)
    print(f"{len(preview)} structure chunks")
    for chunk in preview:
        first = chunk.splitlines()[0:3]
        print("---")
        print("\n".join(first))
        print(f"[{len(chunk)} chars]")
