"""Discovering which column names a workflow actually mentions."""

from __future__ import annotations

from .node_analysis import aggregation_output_name, aggregation_output_names
from .models import NodeInfo, WorkflowGraph


def node_output_columns(node: NodeInfo) -> list[str] | None:
    """Output column names from on-disk port specs, or None if not recorded."""
    if not node.output_specs:
        return None
    names: list[str] = []
    for port in sorted(node.output_specs):
        spec = node.output_specs[port]
        if spec.columns is None:
            continue
        names.extend(c.name for c in spec.columns)
    if not names:
        return None
    return list(dict.fromkeys(names))


def collect_known_columns(graph: WorkflowGraph) -> list[str]:
    """Every column name this workflow demonstrably references, sorted."""
    names: set[str] = set()
    for node in graph.nodes:
        names.update(node_output_columns(node) or [])
        names.update(_columns_from_settings(node.settings))
    return sorted(n for n in names if n and n.strip())


def _columns_from_settings(settings: dict) -> set[str]:
    names: set[str] = set()

    for rename in settings.get("renames", []) or []:
        names.update(v for v in (rename.get("old"), rename.get("new")) if v)

    cf = settings.get("column_filter") or {}
    names.update(cf.get("included") or [])
    names.update(cf.get("excluded") or [])

    rf = settings.get("row_filter") or {}
    names.update(p.get("column") for p in rf.get("predicates", []) or [] if p.get("column"))

    gb = settings.get("groupby") or {}
    names.update(gb.get("group_columns") or [])
    policy = gb.get("column_name_policy")
    for agg in gb.get("aggregations") or []:
        col, method = agg.get("column"), agg.get("method")
        if not col:
            continue
        names.add(col)
        if not method:
            continue
        exact = aggregation_output_name(col, method, policy)
        names.update({exact} if exact else aggregation_output_names(col, method, policy))

    join = settings.get("join") or {}
    left = set(join.get("left_include_columns") or []) | set(
        (join.get("left_output_columns") or {}).get("included") or []
    )
    right = set(join.get("right_include_columns") or []) | set(
        (join.get("right_output_columns") or {}).get("included") or []
    )
    names |= left | right
    names.update(join.get("left_join_columns") or [])
    names.update(join.get("right_join_columns") or [])
    suffix = join.get("suffix")
    if suffix:
        names.update(f"{name}{suffix}" for name in right & left)

    expr = settings.get("expression") or {}
    names.update(v for v in (expr.get("created_column"), expr.get("replaced_column")) if v)

    rule = settings.get("rule_engine") or {}
    names.update(v for v in (rule.get("new_column_name"), rule.get("replace_column_name")) if v)

    sm = settings.get("string_manipulation") or {}
    if sm.get("replaced_column"):
        names.add(sm["replaced_column"])

    return {n for n in names if isinstance(n, str)}


def resolve_column_spelling(graph: WorkflowGraph, column_name: str) -> str | None:
    """The workflow's own spelling of `column_name` if it differs only in case/whitespace."""
    target = column_name.strip().casefold()
    for known in collect_known_columns(graph):
        if known.casefold() == target and known != column_name:
            return known
    return None
