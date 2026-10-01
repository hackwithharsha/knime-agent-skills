"""Recursive workflow.knime / settings.xml walker producing a flat WorkflowGraph."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .models import ColumnSpec, Connection, NodeInfo, PortSpec, WorkflowGraph
from .node_settings import classify_category, extract_flow_variable_bindings, normalize_node
from .redact import redact_settings, redact_text
from .xml_config import KnwfArchive, get_path

PARSER_VERSION = "0.1.0"

_VIRTUAL_INPUT_SUFFIX = "virtual.subnode.VirtualSubNodeInputNodeFactory"
_VIRTUAL_OUTPUT_SUFFIX = "virtual.subnode.VirtualSubNodeOutputNodeFactory"
_FOLDER_LABEL_RE = re.compile(r"^(.*) \(#\d+\)$")


def _join(prefix: str, *parts: str) -> str:
    return str(PurePosixPath(prefix, *parts)) if prefix else str(PurePosixPath(*parts))


def _as_values(config_dict_or_list: object) -> list:
    if isinstance(config_dict_or_list, dict):
        return list(config_dict_or_list.values())
    if isinstance(config_dict_or_list, list):
        return config_dict_or_list
    return []


def _label_from_folder(settings_rel_path: str) -> str:
    folder = settings_rel_path.rsplit("/", 1)[0] if "/" in settings_rel_path else settings_rel_path
    match = _FOLDER_LABEL_RE.match(folder)
    return match.group(1) if match else folder


@dataclass
class _LevelResult:
    nodes: list[NodeInfo] = field(default_factory=list)
    connections: list[Connection] = field(default_factory=list)
    input_ports: dict[int, list[tuple[str, int]]] = field(default_factory=dict)
    output_ports: dict[int, list[tuple[str, int]]] = field(default_factory=dict)
    flow_variable_sources: dict[str, str] = field(default_factory=dict)


def _read_output_specs(archive: KnwfArchive, node_folder: str, ports_config: object) -> dict[int, PortSpec]:
    specs: dict[int, PortSpec] = {}
    for port_entry in _as_values(ports_config):
        if not isinstance(port_entry, dict):
            continue
        index = port_entry.get("index")
        if index is None:
            continue
        location = port_entry.get("port_dir_location")
        columns = None
        if isinstance(location, str) and location:
            spec_path = _join(node_folder, location, "spec.xml")
            if archive.exists(spec_path):
                try:
                    spec_config = archive.read_config(spec_path)
                except Exception:  # noqa: BLE001
                    spec_config = None
                if isinstance(spec_config, dict):
                    columns = []
                    n = spec_config.get("number_columns") or 0
                    for i in range(n):
                        col = spec_config.get(f"column_spec_{i}")
                        if not isinstance(col, dict):
                            continue
                        cell_class = get_path(col, "column_type", "cell_class", default="unknown")
                        columns.append(ColumnSpec(name=col.get("column_name", ""), type=cell_class))
        specs[index] = PortSpec(index=index, columns=columns)
    return specs


def _build_node_info(
    archive: KnwfArchive,
    path_id: str,
    raw: dict,
    settings_rel_path: str,
    folder_prefix: str,
) -> NodeInfo:
    factory = raw.get("factory")
    name = raw.get("name") or _label_from_folder(settings_rel_path)
    annotation = get_path(raw, "nodeAnnotation", "text") or None

    model = raw.get("model") if isinstance(raw.get("model"), dict) else {}
    settings, code, exposed_vars, unrecognized = normalize_node(factory, model)
    bindings = extract_flow_variable_bindings(raw.get("variables"))

    node_folder = _join(folder_prefix, settings_rel_path.rsplit("/", 1)[0])
    output_specs = _read_output_specs(archive, node_folder, raw.get("ports"))

    return NodeInfo(
        id=path_id,
        name=name,
        factory=factory,
        category=classify_category(factory, name),
        unrecognized=unrecognized,
        annotation=annotation,
        settings=redact_settings(settings),
        code=redact_text(code) if code else None,
        output_specs=output_specs,
        flow_variable_bindings=bindings,
        exposed_flow_variables=exposed_vars,
    )


def _build_container_node_info(path_id: str, raw: dict, settings_rel_path: str, is_component: bool) -> NodeInfo:
    name = raw.get("name") or _label_from_folder(settings_rel_path)
    annotation = get_path(raw, "nodeAnnotation", "text") or None
    return NodeInfo(
        id=path_id,
        name=name,
        factory=None,
        category=classify_category(None, name),
        unrecognized=False,
        annotation=annotation,
        is_component=is_component,
        is_metanode=not is_component,
    )


def _parse_level(archive: KnwfArchive, folder_prefix: str, path_prefix: str) -> _LevelResult:
    wf = archive.read_config(_join(folder_prefix, "workflow.knime"))
    node_entries = _as_values(wf.get("nodes"))
    connection_entries = _as_values(wf.get("connections"))

    local_to_path: dict[str, str] = {}
    boundary_input_id: str | None = None
    boundary_output_id: str | None = None
    container_results: dict[str, _LevelResult] = {}
    nodes: list[NodeInfo] = []
    flow_variable_sources: dict[str, str] = {}

    for entry in node_entries:
        if not isinstance(entry, dict) or "id" not in entry or "node_settings_file" not in entry:
            continue
        local_id = str(entry["id"])
        settings_rel = entry["node_settings_file"]
        node_type = entry.get("node_type")
        node_is_meta = bool(entry.get("node_is_meta"))
        settings_path = _join(folder_prefix, settings_rel)

        try:
            raw = archive.read_config(settings_path)
        except KeyError:
            continue

        factory = raw.get("factory")
        if isinstance(factory, str) and factory.endswith(_VIRTUAL_INPUT_SUFFIX):
            boundary_input_id = local_id
            continue
        if isinstance(factory, str) and factory.endswith(_VIRTUAL_OUTPUT_SUFFIX):
            boundary_output_id = local_id
            continue

        path_id = f"{path_prefix}:{local_id}" if path_prefix else local_id
        local_to_path[local_id] = path_id
        is_component = node_type == "SubNode"
        is_container = is_component or node_is_meta

        if is_container:
            container_folder = _join(folder_prefix, settings_rel.rsplit("/", 1)[0])
            child = _parse_level(archive, container_folder, path_id)
            container_results[local_id] = child
            nodes.extend(child.nodes)
            flow_variable_sources.update(child.flow_variable_sources)
            nodes.append(_build_container_node_info(path_id, raw, settings_rel, is_component))
        else:
            node_info = _build_node_info(archive, path_id, raw, settings_rel, folder_prefix)
            nodes.append(node_info)
            for var_name in node_info.exposed_flow_variables:
                flow_variable_sources[var_name] = path_id
            for binding in node_info.flow_variable_bindings:
                if binding.exposed_variable:
                    flow_variable_sources[binding.exposed_variable] = path_id

    def resolve_as_source(local_id: str, port: int) -> list[tuple[str, int]]:
        if local_id in container_results:
            return container_results[local_id].output_ports.get(port, [])
        if local_id in local_to_path:
            return [(local_to_path[local_id], port)]
        return []

    def resolve_as_dest(local_id: str, port: int) -> list[tuple[str, int]]:
        if local_id in container_results:
            return container_results[local_id].input_ports.get(port, [])
        if local_id in local_to_path:
            return [(local_to_path[local_id], port)]
        return []

    input_ports: dict[int, list[tuple[str, int]]] = {}
    output_ports: dict[int, list[tuple[str, int]]] = {}
    resolved_connections: list[Connection] = []

    for conn in connection_entries:
        if not isinstance(conn, dict):
            continue
        src_local = str(conn.get("sourceID"))
        dst_local = str(conn.get("destID"))
        src_port = conn.get("sourcePort")
        dst_port = conn.get("destPort")
        if src_port is None or dst_port is None:
            continue

        if boundary_input_id is not None and src_local == boundary_input_id:
            targets = resolve_as_dest(dst_local, dst_port)
            input_ports.setdefault(src_port, []).extend(targets)
            continue
        if boundary_output_id is not None and dst_local == boundary_output_id:
            sources = resolve_as_source(src_local, src_port)
            output_ports.setdefault(dst_port, []).extend(sources)
            continue

        for source_id, source_port in resolve_as_source(src_local, src_port):
            for dest_id, dest_port in resolve_as_dest(dst_local, dst_port):
                resolved_connections.append(
                    Connection(
                        source_node=source_id,
                        source_port=source_port,
                        dest_node=dest_id,
                        dest_port=dest_port,
                    )
                )

    for child in container_results.values():
        resolved_connections.extend(child.connections)

    return _LevelResult(
        nodes=nodes,
        connections=resolved_connections,
        input_ports=input_ports,
        output_ports=output_ports,
        flow_variable_sources=flow_variable_sources,
    )


_DESCRIPTION_TAG_RE = re.compile(r"<[^>]+>")


def _read_description(archive: KnwfArchive) -> str | None:
    if not archive.exists("workflow-metadata.xml"):
        return None
    try:
        text = archive.read_text("workflow-metadata.xml")
    except Exception:  # noqa: BLE001
        return None
    match = re.search(r"<description[^>]*>\s*<!\[CDATA\[(.*?)\]\]>\s*</description>", text, re.S)
    if not match:
        match = re.search(r"<description[^>]*>(.*?)</description>", text, re.S)
    if not match:
        return None
    plain = _DESCRIPTION_TAG_RE.sub(" ", match.group(1)).strip()
    return re.sub(r"\s+", " ", plain) or None


def build_workflow_graph(archive: KnwfArchive, name: str) -> WorkflowGraph:
    level = _parse_level(archive, "", "")
    description = _read_description(archive)
    return WorkflowGraph(
        parser_version=PARSER_VERSION,
        name=name,
        description=description,
        nodes=level.nodes,
        connections=level.connections,
        flow_variable_sources=level.flow_variable_sources,
    )
