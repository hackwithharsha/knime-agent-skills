#!/usr/bin/env python3
"""
Parse a KNIME .knwf workflow export into JSON for the agent to read.

This is the only sanctioned way to read a .knwf. It decodes KNIME's
undocumented %%NNNNN text escape, strips ~hundreds of lines of per-node JDBC
type-mapping boilerplate, and redacts credential fields — none of which
happens if the zip is opened and its XML read directly.

Standard library only — no installation required.

Usage:
  python3 scripts/parse_knwf.py <workflow.knwf>              # full JSON to stdout
  python3 scripts/parse_knwf.py <workflow.knwf> --summary    # structure outline
  python3 scripts/parse_knwf.py <workflow.knwf> -o graph.json
"""

import argparse
import json
import sys
from pathlib import Path

from knime_doc.budget import MAX_JSON_CHARS, SIZE_BUDGET_NOTE, enforce_size_budget
from knime_doc.knwf import parse_knwf
from knime_doc.models import WorkflowGraph, WorkflowNode


def _count_nodes(graph: WorkflowGraph) -> int:
    return sum(1 + (_count_nodes(n.children) if n.children else 0) for n in graph.nodes)


def _summary_lines(graph: WorkflowGraph, indent: int = 0) -> list[str]:
    """A compact structural outline: enough to plan the doc's sections without
    pulling every node's full settings into context."""
    pad = "  " * indent
    lines: list[str] = []
    if indent == 0:
        lines.append(f"Workflow: {graph.name}")
        lines.append(f"Description/annotations: {graph.description or '(none)'}")
        if graph.flow_variables:
            lines.append(f"Flow variables: {', '.join(graph.flow_variables)}")
        lines.append("")
        lines.append("Nodes:")

    by_id = {n.id: n for n in graph.nodes}
    for node in graph.nodes:
        role = " ".join(
            part
            for part in (
                "[source]" if node.is_source else "",
                "[sink]" if node.is_sink else "",
            )
            if part
        )
        label = f"{node.type_label}" if node.type_label and node.type_label != node.name else ""
        lines.append(
            f"{pad}  #{node.id} {node.name}"
            + (f" ({label})" if label else "")
            + (f" <{node.node_type}>" if node.node_type != "NativeNode" else "")
            + (f" {role}" if role else "")
        )
        if node.annotation:
            lines.append(f"{pad}      note: {node.annotation.strip().splitlines()[0][:120]}")
        if node.children:
            lines.extend(_summary_lines(node.children, indent + 2))

    if graph.connections:
        lines.append("")
        lines.append(f"{pad}Connections ({len(graph.connections)}):")
        for c in graph.connections:
            src = _endpoint(by_id, c.source_id, "in")
            dst = _endpoint(by_id, c.target_id, "out")
            lines.append(f"{pad}  {src}  ->  {dst}")
    return lines


def _endpoint(by_id: dict[int, WorkflowNode], node_id: int, boundary: str) -> str:
    """Label one end of a connection. Inside a metanode or component, KNIME uses
    id -1 for the container's own boundary ports rather than a real node."""
    node = by_id.get(node_id)
    if node is not None:
        return f"#{node_id} {node.name}"
    if node_id == -1:
        return f"(enclosing {boundary}put port)"
    return f"#{node_id} (unknown node)"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse a KNIME .knwf export into JSON (or a compact outline).",
    )
    parser.add_argument("knwf", type=Path, help="path to the .knwf file")
    parser.add_argument("-o", "--output", type=Path, help="write to this file instead of stdout")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="print a compact structural outline (nodes, roles, connections) instead of full JSON",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=MAX_JSON_CHARS,
        help=f"context budget for the JSON; per-node settings are trimmed above it (default {MAX_JSON_CHARS})",
    )
    parser.add_argument("--no-budget", action="store_true", help="never trim, whatever the size")
    parser.add_argument("--indent", type=int, default=2, help="JSON indent (default 2)")
    args = parser.parse_args()

    if not args.knwf.is_file():
        print(f"error: no such file: {args.knwf}", file=sys.stderr)
        return 2
    if args.knwf.suffix.lower() != ".knwf":
        print(
            f"warning: {args.knwf.name} does not end in .knwf — parsing anyway",
            file=sys.stderr,
        )

    try:
        graph = parse_knwf(args.knwf.read_bytes())
    except Exception as exc:  # zip/XML/structure problems all land here
        print(f"error: could not parse {args.knwf.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    trimmed = False if args.no_budget else enforce_size_budget(graph, args.max_chars)

    if args.summary:
        text = "\n".join(_summary_lines(graph))
        if trimmed:
            text += f"\n\n[settings trimmed] {SIZE_BUDGET_NOTE}"
    else:
        payload = {
            "meta": {
                "source_file": args.knwf.name,
                "workflow_name": graph.name,
                "node_count": _count_nodes(graph),
                "connection_count": len(graph.connections),
                "settings_trimmed": trimmed,
                # When true, add this verbatim as the first bullet under "## Notes" —
                # the agent has no other way to know what was cut before it read the JSON.
                "trim_note": SIZE_BUDGET_NOTE if trimmed else None,
            },
            "workflow": graph.to_dict(),
        }
        text = json.dumps(payload, indent=args.indent, ensure_ascii=False)

    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output} ({len(text):,} chars)", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
