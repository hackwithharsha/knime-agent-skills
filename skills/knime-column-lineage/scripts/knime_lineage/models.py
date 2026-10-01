"""Dataclass models for the workflow graph (parser output) and lineage subgraph."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------


class NodeCategory(str, Enum):
    SOURCE = "source"
    SINK = "sink"
    TRANSFORM = "transform"
    CODE = "code"
    FLOW_CONTROL = "flow_control"


class Evidence(str, Enum):
    TRACED_FROM_SPEC = "traced_from_spec"
    TRACED_FROM_SETTINGS = "traced_from_settings"
    INFERRED_FROM_CODE = "inferred_from_code"


# ---------------------------------------------------------------------------
# Parser / workflow graph models
# ---------------------------------------------------------------------------


@dataclass
class ColumnSpec:
    name: str
    type: str


@dataclass
class PortSpec:
    index: int
    columns: list[ColumnSpec] | None = None


@dataclass
class FlowVariableBinding:
    setting_path: str
    used_variable: str | None = None
    exposed_variable: str | None = None


@dataclass
class NodeInfo:
    id: str
    name: str
    factory: str | None
    category: NodeCategory
    unrecognized: bool = False
    annotation: str | None = None
    settings: dict = field(default_factory=dict)
    code: str | None = None
    output_specs: dict[int, PortSpec] = field(default_factory=dict)
    flow_variable_bindings: list[FlowVariableBinding] = field(default_factory=list)
    exposed_flow_variables: list[str] = field(default_factory=list)
    is_component: bool = False
    is_metanode: bool = False


@dataclass
class Connection:
    source_node: str
    source_port: int
    dest_node: str
    dest_port: int


@dataclass
class WorkflowGraph:
    parser_version: str
    name: str
    description: str | None = None
    nodes: list[NodeInfo] = field(default_factory=list)
    connections: list[Connection] = field(default_factory=list)
    flow_variable_sources: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Lineage subgraph models
# ---------------------------------------------------------------------------


@dataclass
class JoinCandidate:
    side: str
    source_node: str
    kept: bool


@dataclass
class ColumnAction:
    node_id: str
    node_name: str
    factory: str | None
    action: str
    evidence: Evidence
    settings: dict = field(default_factory=dict)
    code: str | None = None
    join_candidates: list[JoinCandidate] | None = None


@dataclass
class SubgraphEdge:
    source_node: str
    dest_node: str
    passthrough_count: int = 0
    passthrough_node_ids: list[str] = field(default_factory=list)


@dataclass
class FlowVariableInfluence:
    variable_name: str
    setting_path: str
    controlling_node_id: str
    controlling_node_name: str
    defining_node_id: str | None = None
    defining_node_name: str | None = None


@dataclass
class LineageSubgraph:
    column_name: str
    workflow_name: str
    origin_method: str
    nodes: list[ColumnAction] = field(default_factory=list)
    edges: list[SubgraphEdge] = field(default_factory=list)
    flow_variable_influences: list[FlowVariableInfluence] = field(default_factory=list)
    truncated: bool = False
    truncation_note: str | None = None


# ---------------------------------------------------------------------------
# JSON serialization helper
# ---------------------------------------------------------------------------


def to_serializable(obj: Any) -> Any:
    """Recursively convert dataclasses and Enums to JSON-serializable types."""
    if isinstance(obj, Enum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_serializable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {k: to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_serializable(v) for v in obj]
    return obj
