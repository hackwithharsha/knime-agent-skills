"""Shapes for a parsed KNIME workflow.

Plain dataclasses, not pydantic: this skill runs inside Claude's sandbox, where
only the standard library and a handful of preinstalled packages are available
and there is no reliable way to install anything else. Every module here is
stdlib-only for that reason.
"""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class WorkflowConnection:
    source_id: int
    target_id: int
    source_port: int = 0
    target_port: int = 0


@dataclass
class WorkflowNode:
    id: int
    name: str
    node_type: str  # "NativeNode" | "MetaNode" | "SubNode"
    factory: str | None = None
    type_label: str | None = None
    annotation: str | None = None
    description: str | None = None
    state: str | None = None
    is_source: bool = False
    is_sink: bool = False
    settings: dict[str, Any] = field(default_factory=dict)
    flow_variables: list[str] = field(default_factory=list)
    children: "WorkflowGraph | None" = None


@dataclass
class WorkflowGraph:
    name: str
    description: str | None = None
    nodes: list[WorkflowNode] = field(default_factory=list)
    connections: list[WorkflowConnection] = field(default_factory=list)
    flow_variables: list[str] = field(default_factory=list)
    source_node_ids: list[int] = field(default_factory=list)
    sink_node_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready nested dict. asdict() recurses through nested dataclasses
        and lists; `settings` is already plain dicts/lists/scalars."""
        return asdict(self)
