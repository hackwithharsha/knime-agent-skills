#!/usr/bin/env python3
"""Trace how a column in a KNIME workflow was derived.

Usage
-----
List every column the workflow mentions (use this when you don't know the exact name):

    python3 scripts/trace_lineage.py workflow.knwf --list-columns

Trace one column (outputs JSON + writes an interactive HTML diagram):

    python3 scripts/trace_lineage.py workflow.knwf -c "Count of Flights" --html lineage.html

Show a slim node-graph overview:

    python3 scripts/trace_lineage.py workflow.knwf --summary

All modes output JSON to stdout and exit 0 on success, 1 on error.
The --html file is written alongside the JSON when -c is given.

Requirements: Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

# Allow running as "python3 scripts/trace_lineage.py" from any working directory.
_SCRIPTS_DIR = pathlib.Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from knime_lineage.columns import collect_known_columns, resolve_column_spelling
from knime_lineage.graph_builder import build_workflow_graph
from knime_lineage.models import to_serializable
from knime_lineage.render_html import render_lineage_html
from knime_lineage.walker import ColumnNotFoundError, get_column_lineage_subgraph
from knime_lineage.xml_config import KnwfArchive


def _load_graph(knwf_path: str):
    path = pathlib.Path(knwf_path)
    name = path.stem
    with KnwfArchive(knwf_path) as archive:
        return build_workflow_graph(archive, name)


def cmd_list_columns(args) -> int:
    try:
        graph = _load_graph(args.knwf)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    columns = collect_known_columns(graph)
    print(json.dumps({"workflow": graph.name, "column_count": len(columns), "columns": columns}, indent=2))
    return 0


def cmd_summary(args) -> int:
    try:
        graph = _load_graph(args.knwf)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        return 1

    nodes = [
        {
            "id": n.id,
            "name": n.name,
            "category": n.category.value,
            "has_code": bool(n.code),
            "uses_flow_variable": any(b.used_variable for b in n.flow_variable_bindings),
            "is_component": n.is_component,
            "is_metanode": n.is_metanode,
            "unrecognized": n.unrecognized,
            "annotation": n.annotation,
        }
        for n in graph.nodes
    ]
    connections = [
        {"source": c.source_node, "dest": c.dest_node, "source_port": c.source_port, "dest_port": c.dest_port}
        for c in graph.connections
    ]
    result = {
        "workflow": graph.name,
        "description": graph.description,
        "node_count": len(nodes),
        "connection_count": len(connections),
        "nodes": nodes,
        "connections": connections,
    }
    print(json.dumps(result, indent=2))
    return 0


def cmd_trace(args) -> int:
    try:
        graph = _load_graph(args.knwf)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        return 1

    try:
        subgraph = get_column_lineage_subgraph(graph, args.column)
    except ColumnNotFoundError:
        known = collect_known_columns(graph)
        suggestion = resolve_column_spelling(graph, args.column)
        result = {
            "error": f'Column "{args.column}" not found in "{graph.name}".',
            "did_you_mean": suggestion,
            "available_columns": known,
        }
        print(json.dumps(result, indent=2))
        return 1

    html = render_lineage_html(subgraph)

    if args.html:
        html_path = pathlib.Path(args.html)
        html_path.write_text(html, encoding="utf-8")
        diagram_info = {"diagram_html_path": str(html_path)}
    else:
        diagram_info = {"diagram_html": html}

    result = {"lineage": to_serializable(subgraph), **diagram_info}
    print(json.dumps(result, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Trace KNIME column lineage from a .knwf workflow export."
    )
    parser.add_argument("knwf", help="Path to the .knwf workflow file (or renamed .zip)")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--list-columns",
        action="store_true",
        help="List every column name the workflow mentions. Use this to find the exact name to pass to -c.",
    )
    mode.add_argument(
        "--summary",
        action="store_true",
        help="Print a slim node-graph overview (node names, categories, connections).",
    )
    mode.add_argument(
        "-c", "--column",
        metavar="COLUMN_NAME",
        help="Column name to trace (case-sensitive, exactly as it appears in the workflow).",
    )

    parser.add_argument(
        "--html",
        metavar="PATH",
        help="Write the interactive HTML diagram to this file (recommended). "
             "Without this flag the HTML is embedded in the JSON output.",
    )

    args = parser.parse_args()

    if args.list_columns:
        return cmd_list_columns(args)
    if args.summary:
        return cmd_summary(args)
    return cmd_trace(args)


if __name__ == "__main__":
    sys.exit(main())
