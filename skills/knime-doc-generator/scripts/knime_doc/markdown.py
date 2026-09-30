"""
A small Markdown reader for the subset this skill's documents use, plus the
defensive fixups that LLM output needs.

Why not markdown-it-py or `markdown`: this runs in Claude's sandbox, where
neither is guaranteed present and nothing can be installed. The subset is not
general Markdown — it is exactly what `references/doc-template.md` prescribes:
ATX headings, bullet and numbered lists (one level of nesting), pipe tables,
paragraphs, and inline bold / italic / code. Anything outside that degrades to
plain text rather than failing.
"""

import re
from dataclasses import dataclass, field
from html import escape

# Anchored end-to-end (via fullmatch) so this only matches when the *entire*
# document is one big fence — never a legitimate code block the doc itself
# includes partway through (e.g. a config snippet in Notes), since that
# wouldn't span from the very first to the very last character.
_WRAPPING_FENCE_RE = re.compile(r"```(?:markdown|md)?\s*\n(.*)\n```", re.DOTALL)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_ORDERED_RE = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_TABLE_DIVIDER_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def strip_wrapping_code_fence(markdown_text: str) -> str:
    """Removes a single ```markdown fence wrapped around the *entire* document,
    if present. A model writing this document occasionally responds as if
    demonstrating Markdown syntax (fencing its whole answer) rather than
    emitting raw Markdown. Left in, every heading and list would render as one
    inert block of preformatted text."""
    match = _WRAPPING_FENCE_RE.fullmatch(markdown_text.strip())
    return match.group(1) if match else markdown_text


def strip_leading_h1(markdown_text: str) -> str:
    """Removes a single leading '# Title' line, if present. The exporter renders
    its own title, date, and disclaimer header; the document body should hold
    only the five '##' sections, but a model sometimes adds a title line anyway.
    Left in, it shows up as a duplicate heading above "Purpose"."""
    stripped = markdown_text.lstrip()
    if stripped.startswith("# "):
        _, _, rest = stripped.partition("\n")
        return rest.lstrip("\n")
    return markdown_text


def clean_markdown(markdown_text: str) -> str:
    """Applies both fixups in the order that matters: unwrap a whole-document
    code fence first (a stray leading '#' line would be *inside* the fence),
    then strip that H1."""
    return strip_leading_h1(strip_wrapping_code_fence(markdown_text))


# ── Block model ───────────────────────────────────────────────────────────


@dataclass
class Heading:
    level: int
    text: str


@dataclass
class ParagraphBlock:
    text: str


@dataclass
class ListItem:
    text: str
    depth: int = 0


@dataclass
class ListBlock:
    ordered: bool
    items: list[ListItem] = field(default_factory=list)


@dataclass
class TableBlock:
    header: list[str]
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class CodeBlock:
    text: str


Block = Heading | ParagraphBlock | ListBlock | TableBlock | CodeBlock


def parse_blocks(markdown_text: str) -> list[Block]:
    """Parse the document into a flat list of blocks, in order."""
    lines = markdown_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(ParagraphBlock(" ".join(s.strip() for s in paragraph).strip()))
            paragraph.clear()

    i = 0
    while i < len(lines):
        line = lines[i]

        if not line.strip():
            flush_paragraph()
            i += 1
            continue

        if line.lstrip().startswith("```"):
            flush_paragraph()
            i += 1
            body: list[str] = []
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1  # closing fence
            blocks.append(CodeBlock("\n".join(body)))
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            blocks.append(Heading(len(heading.group(1)), heading.group(2).strip()))
            i += 1
            continue

        # A table needs a header row followed by a divider row.
        if "|" in line and i + 1 < len(lines) and _TABLE_DIVIDER_RE.match(lines[i + 1]):
            flush_paragraph()
            header = _split_table_row(line)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_split_table_row(lines[i]))
                i += 1
            blocks.append(TableBlock(header, rows))
            continue

        bullet = _BULLET_RE.match(line)
        ordered = _ORDERED_RE.match(line)
        if bullet or ordered:
            flush_paragraph()
            is_ordered = ordered is not None
            block = ListBlock(ordered=is_ordered)
            while i < len(lines):
                match = _ORDERED_RE.match(lines[i]) if is_ordered else _BULLET_RE.match(lines[i])
                other = _BULLET_RE.match(lines[i]) if is_ordered else _ORDERED_RE.match(lines[i])
                if match:
                    depth = min(len(match.group(1)) // 2, 2)
                    block.items.append(ListItem(match.group(2).strip(), depth))
                    i += 1
                elif other or not lines[i].strip():
                    break
                elif lines[i].startswith((" ", "\t")) and block.items:
                    # A wrapped continuation line of the previous item.
                    block.items[-1].text += " " + lines[i].strip()
                    i += 1
                else:
                    break
            blocks.append(block)
            continue

        paragraph.append(line)
        i += 1

    flush_paragraph()
    return blocks


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


# ── Inline markup ─────────────────────────────────────────────────────────

# ReportLab's Paragraph accepts a small HTML-like markup, so inline Markdown is
# translated into that rather than into real HTML.
_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_ITALIC_RE = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)|(?<![_\w])_([^_\n]+)_(?![\w_])")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def inline_to_rl(text: str, code_font: str = "Courier") -> str:
    """Convert inline Markdown to ReportLab's paragraph markup.

    Code spans are extracted before escaping so their contents are never
    re-interpreted as markup, then restored at the end.
    """
    placeholders: list[str] = []

    def stash_code(match: re.Match[str]) -> str:
        placeholders.append(match.group(1))
        return f"\x00{len(placeholders) - 1}\x00"

    text = _CODE_RE.sub(stash_code, text)
    text = escape(text, quote=False)
    text = _LINK_RE.sub(r"\1", text)  # links render as their label; no clickable targets
    text = _BOLD_RE.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = _ITALIC_RE.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", text)

    def restore_code(match: re.Match[str]) -> str:
        body = escape(placeholders[int(match.group(1))], quote=False)
        return f'<font face="{code_font}">{body}</font>'

    return re.sub(r"\x00(\d+)\x00", restore_code, text)


def to_plain_text(text: str) -> str:
    """Strip inline markers, for contexts that take no markup."""
    text = _CODE_RE.sub(r"\1", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _BOLD_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = _ITALIC_RE.sub(lambda m: m.group(1) or m.group(2), text)
    return text
