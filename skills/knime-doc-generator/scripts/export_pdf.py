#!/usr/bin/env python3
"""
Render documentation markdown into a styled PDF.

Adds the title / generated-date / AI-disclaimer header block itself, so the
markdown it is given should contain only the five "##" body sections. A leading
"# Title" line or a whole-document ```markdown fence is stripped defensively
rather than rejected.

Needs ReportLab, which is preinstalled in Claude's sandbox.

Usage:
  python3 scripts/export_pdf.py doc.md -n "Retry Database Connection"
  python3 scripts/export_pdf.py doc.md -n "Retry Database Connection" -o out/doc.pdf
  cat doc.md | python3 scripts/export_pdf.py - -n "My Workflow"
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from knime_doc.filenames import safe_filename
from knime_doc.markdown import clean_markdown

REQUIRED_SECTIONS = ["## Purpose", "## Inputs", "## Outputs", "## Transformation Steps", "## Notes"]

_REPORTLAB_HELP = """\
error: ReportLab could not be loaded ({detail}).

ReportLab renders the PDF and is normally already available. Install it with:

  pip install reportlab

The Markdown document is already written and is unaffected — it can be exported
again once ReportLab is available.\
"""


def _check_sections(markdown: str) -> list[str]:
    """Returns human-readable problems with the five-section template, if any."""
    problems: list[str] = []
    positions: dict[str, int] = {}
    for heading in REQUIRED_SECTIONS:
        idx = markdown.find(f"\n{heading}")
        if idx == -1 and markdown.startswith(heading):
            idx = 0
        if idx == -1:
            problems.append(f"missing required section: {heading!r}")
        else:
            positions[heading] = idx

    found = [h for h in REQUIRED_SECTIONS if h in positions]
    in_file_order = sorted(found, key=lambda h: positions[h])
    if found != in_file_order:
        problems.append(f"sections are out of order: found {' , '.join(in_file_order)}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Render documentation markdown into a styled PDF.")
    parser.add_argument("markdown", type=str, help="path to the markdown file, or '-' for stdin")
    parser.add_argument(
        "-n",
        "--workflow-name",
        required=True,
        help="workflow name, verbatim from the parsed workflow — used as the PDF title",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output .pdf path (default: '<workflow name>.pdf' beside the markdown)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail instead of warning when the five-section template is not satisfied",
    )
    args = parser.parse_args()

    if args.markdown == "-":
        markdown = sys.stdin.read()
        source_dir = Path.cwd()
    else:
        md_path = Path(args.markdown)
        if not md_path.is_file():
            print(f"error: no such file: {md_path}", file=sys.stderr)
            return 2
        markdown = md_path.read_text(encoding="utf-8")
        source_dir = md_path.parent

    if not markdown.strip():
        print("error: the markdown is empty", file=sys.stderr)
        return 2

    cleaned = clean_markdown(markdown)
    problems = _check_sections(cleaned)
    if problems:
        label = "error" if args.strict else "warning"
        for problem in problems:
            print(f"{label}: {problem}", file=sys.stderr)
        if args.strict:
            return 3

    output = args.output or source_dir / f"{safe_filename(args.workflow_name)}.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        from knime_doc.pdf_exporter import build_pdf

        pdf_bytes = build_pdf(args.workflow_name, datetime.now(), cleaned)
    except ImportError as exc:
        print(_REPORTLAB_HELP.format(detail=f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        return 4

    output.write_bytes(pdf_bytes)
    print(f"wrote {output} ({len(pdf_bytes):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
