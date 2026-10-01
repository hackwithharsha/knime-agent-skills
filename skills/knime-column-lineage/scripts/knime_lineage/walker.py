"""get_column_lineage_subgraph: the deterministic upstream column walk."""

from __future__ import annotations

import math
from collections import deque

from .models import (
    ColumnAction,
    Evidence,
    FlowVariableInfluence,
    LineageSubgraph,
    NodeInfo,
    SubgraphEdge,
    WorkflowGraph,
)
from . import node_analysis as na

DEFAULT_MAX_NODES = 40

_ANALYZERS = {
    "column.renamer.ColumnRenamerNodeFactory": na.analyze_column_renamer,
    "filter.column.DataColumnSpecFilterNodeFactory": na.analyze_column_filter,
    "manipulation.filter.column.DBFilterColumnNodeFactory": na.analyze_column_filter,
    "filter.row3.RowFilterNodeFactory": na.analyze_row_filter,
    "filter.row.RowFilterNodeFactory": na.analyze_row_filter,
    "manipulation.filter.row.DBFilterRowNodeFactory": na.analyze_row_filter,
    "groupby.GroupByNodeFactory": na.analyze_groupby,
    "joiner3.Joiner3NodeFactory": na.analyze_joiner,
    "joiner.Joiner2NodeFactory": na.analyze_joiner,
    "expressions.node.row.mapper.ExpressionRowMapperNodeFactory": na.analyze_expression,
    "expressions.node.row.filter.ExpressionRowFilterNodeFactory": na.analyze_expression,
    "rules.engine.RuleEngineNodeFactory": na.analyze_rule_engine,
    "rules.engine.RuleEngineFilterNodeFactory": na.analyze_rule_engine,
    "stringmanipulation.StringManipulationNodeFactory": na.analyze_string_manipulation,
}

_CODE_GENERIC_SUFFIXES = (
    "scripting.nodes2.script.PythonScriptNodeFactory",
    "manipulation.query.DBSQLQueryNodeFactory",
    "io.reader.query.DBQueryReaderNodeFactory",
    "io.parameterizedquery.ParameterizedDBSQLQueryNodeFactory",
    "manipulation.executor.DBExecutorNodeFactory",
)


class ColumnNotFoundError(ValueError):
    pass


def _find_analyzer(factory: str | None):
    if not factory:
        return None
    for suffix, fn in _ANALYZERS.items():
        if factory.endswith(suffix):
            return fn
    for suffix in _CODE_GENERIC_SUFFIXES:
        if factory.endswith(suffix):
            return na.analyze_code_generic
    return None


def _mentions_column(node: NodeInfo, column_name: str) -> bool:
    if any(cs.name == column_name for spec in node.output_specs.values() for cs in (spec.columns or [])):
        return True
    return na.produces_column_name(node, column_name)


def _has_output_spec_hit(node: NodeInfo, column_name: str) -> bool:
    return any(cs.name == column_name for spec in node.output_specs.values() for cs in (spec.columns or []))


def _reachable_downstream(start: str, forward: dict[str, list[str]]) -> set[str]:
    seen = {start}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        for nxt in forward.get(cur, []):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def _select_start_nodes(graph: WorkflowGraph, column_name: str) -> tuple[list[str], str]:
    real_nodes = [n for n in graph.nodes if not (n.is_component or n.is_metanode)]
    forward: dict[str, list[str]] = {}
    for c in graph.connections:
        forward.setdefault(c.source_node, []).append(c.dest_node)

    spec_hits = [n for n in real_nodes if _has_output_spec_hit(n, column_name)]
    if spec_hits:
        terminal = [n for n in spec_hits if n.id not in forward or not forward[n.id]]
        chosen = terminal or spec_hits
        return [n.id for n in chosen], "traced_from_spec"

    mention_hits = [n for n in real_nodes if _mentions_column(n, column_name)]
    if not mention_hits:
        raise ColumnNotFoundError(f'column "{column_name}" not found in any node\'s spec, settings, or code')

    mention_ids = {n.id for n in mention_hits}
    downstream_most = []
    for n in mention_hits:
        reachable = _reachable_downstream(n.id, forward) - {n.id}
        if not (reachable & mention_ids):
            downstream_most.append(n.id)
    return downstream_most or [n.id for n in mention_hits], "traced_from_settings_or_code"


def _upstream_by_port_has(node_id: str, upstream_by_port: dict[tuple[str, int], list[tuple[str, int]]]) -> bool:
    return any(key[0] == node_id for key in upstream_by_port)


def get_column_lineage_subgraph(
    graph: WorkflowGraph, column_name: str, max_nodes: int = DEFAULT_MAX_NODES
) -> LineageSubgraph:
    nodes_by_id = {n.id: n for n in graph.nodes}

    upstream_by_port: dict[tuple[str, int], list[tuple[str, int]]] = {}
    for c in graph.connections:
        upstream_by_port.setdefault((c.dest_node, c.dest_port), []).append((c.source_node, c.source_port))

    start_ids, origin_method = _select_start_nodes(graph, column_name)

    touches: dict[str, list[na.NodeAnalysis]] = {}
    visited_wanted: dict[str, set[str]] = {}
    edges: dict[tuple[str, str], SubgraphEdge] = {}
    depth: dict[str, int] = {}

    queue: deque[tuple[str, set[str], str | None, list[str], int]] = deque(
        (sid, {column_name}, None, [], 0) for sid in start_ids
    )

    while queue:
        node_id, wanted, from_kept, skip_ids, d = queue.popleft()
        node = nodes_by_id.get(node_id)
        if node is None:
            continue

        already = visited_wanted.get(node_id, set())
        new_wanted = wanted - already
        if not new_wanted:
            continue
        visited_wanted[node_id] = already | new_wanted

        analyzer = _find_analyzer(node.factory)
        if analyzer is not None:
            analysis = analyzer(node, new_wanted)
        elif _upstream_by_port_has(node_id, upstream_by_port):
            analysis = na.passthrough(new_wanted)
        else:
            analysis = na.analyze_source(node, new_wanted)

        if analysis.touches:
            touches.setdefault(node_id, []).append(analysis)
            depth[node_id] = min(depth.get(node_id, d), d)
            if from_kept is not None:
                reverse_key = (from_kept, node_id)
                edge = SubgraphEdge(
                    source_node=node_id,
                    dest_node=from_kept,
                    passthrough_count=len(skip_ids),
                    passthrough_node_ids=list(skip_ids),
                )
                if reverse_key not in edges or edges[reverse_key].passthrough_count > edge.passthrough_count:
                    edges[reverse_key] = edge
            next_from_kept = node_id
            next_skip_ids: list[str] = []
        else:
            next_from_kept = from_kept
            next_skip_ids = [*skip_ids, node_id]

        for port, names in analysis.input_wants.items():
            for upstream_id, _upstream_port in upstream_by_port.get((node_id, port), []):
                queue.append((upstream_id, set(names), next_from_kept, next_skip_ids, d + 1))

    kept_nodes = _finalize_nodes(nodes_by_id, touches)
    kept_edges = [e for e in edges.values() if e.dest_node in touches and e.source_node in touches]

    truncated = False
    truncation_note = None
    if len(kept_nodes) > max_nodes:
        kept_nodes, kept_edges, truncation_note = _truncate(kept_nodes, kept_edges, depth, max_nodes)
        truncated = True

    flow_influences = _collect_flow_variable_influences(graph, nodes_by_id, {n.node_id for n in kept_nodes})

    return LineageSubgraph(
        column_name=column_name,
        workflow_name=graph.name,
        origin_method=origin_method,
        nodes=kept_nodes,
        edges=kept_edges,
        flow_variable_influences=flow_influences,
        truncated=truncated,
        truncation_note=truncation_note,
    )


def _finalize_nodes(nodes_by_id: dict[str, NodeInfo], touches: dict[str, list[na.NodeAnalysis]]) -> list[ColumnAction]:
    result = []
    for node_id, analyses in touches.items():
        node = nodes_by_id[node_id]
        seen_actions: list[str] = []
        for a in analyses:
            if a.action and a.action not in seen_actions:
                seen_actions.append(a.action)
        evidences = {a.evidence for a in analyses}
        if Evidence.INFERRED_FROM_CODE in evidences:
            evidence = Evidence.INFERRED_FROM_CODE
        elif Evidence.TRACED_FROM_SPEC in evidences:
            evidence = Evidence.TRACED_FROM_SPEC
        else:
            evidence = Evidence.TRACED_FROM_SETTINGS
        merged_settings: dict = {}
        for a in analyses:
            merged_settings.update(a.settings)
        join_candidates = next((a.join_candidates for a in analyses if a.join_candidates), None)

        result.append(
            ColumnAction(
                node_id=node_id,
                node_name=node.name,
                factory=node.factory,
                action="; ".join(seen_actions) or "on path (no specific action recorded)",
                evidence=evidence,
                settings=merged_settings,
                code=node.code,
                join_candidates=join_candidates,
            )
        )
    return result


def _truncate(
    nodes: list[ColumnAction],
    edges: list[SubgraphEdge],
    depth: dict[str, int],
    max_nodes: int,
) -> tuple[list[ColumnAction], list[SubgraphEdge], str]:
    ordered = sorted(nodes, key=lambda n: depth.get(n.node_id, 0))
    keep_near_dest = math.ceil(max_nodes / 2)
    keep_near_origin = max_nodes - keep_near_dest
    kept = ordered[:keep_near_dest] + (ordered[-keep_near_origin:] if keep_near_origin else [])
    kept_ids = {n.node_id for n in kept}
    dropped = [n for n in nodes if n.node_id not in kept_ids]
    note = (
        f"{len(dropped)} node(s) nearest the middle of the path were dropped to stay under "
        f"max_nodes={max_nodes}: {', '.join(n.node_name for n in dropped)}"
    )
    kept_edges = [e for e in edges if e.source_node in kept_ids and e.dest_node in kept_ids]
    unique = list({n.node_id: n for n in kept}.values())
    return unique, kept_edges, note


def _collect_flow_variable_influences(
    graph: WorkflowGraph, nodes_by_id: dict[str, NodeInfo], kept_ids: set[str]
) -> list[FlowVariableInfluence]:
    influences = []
    for node_id in kept_ids:
        node = nodes_by_id[node_id]
        for binding in node.flow_variable_bindings:
            if not binding.used_variable:
                continue
            defining_id = graph.flow_variable_sources.get(binding.used_variable)
            defining_node = nodes_by_id.get(defining_id) if defining_id else None
            influences.append(
                FlowVariableInfluence(
                    variable_name=binding.used_variable,
                    setting_path=binding.setting_path,
                    controlling_node_id=node_id,
                    controlling_node_name=node.name,
                    defining_node_id=defining_id,
                    defining_node_name=defining_node.name if defining_node else None,
                )
            )
    return influences
