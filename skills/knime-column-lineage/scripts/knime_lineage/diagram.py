"""Renders a lineage subgraph as a self-contained SVG."""

from __future__ import annotations

from xml.sax.saxutils import escape

from .models import Evidence, LineageSubgraph

BOX_W = 232
BOX_H = 76
H_GAP = 72
V_GAP = 26
MARGIN = 20
HEADER_H = 46
LEGEND_H = 30
FV_BOX_H = 30

INK = "#0f172a"
MUTED = "#475569"
LINE = "#64748b"
BOX_FILL = "#ffffff"
BOX_STROKE = "#334155"
CANVAS = "#f8fafc"
CANVAS_STROKE = "#cbd5e1"
FV_FILL = "#fef3c7"
FV_STROKE = "#b45309"
FV_INK = "#78350f"


def _xml_text(text: str) -> str:
    escaped = escape(text)
    return "".join(ch if ord(ch) < 128 else f"&#{ord(ch)};" for ch in escaped)


def _truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _wrap(text: str, width: int, max_lines: int) -> list[str]:
    words = " ".join(text.split()).split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines:
            current = ""
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if not lines:
        return [""]
    if len(" ".join(lines)) < len(" ".join(words)):
        lines[-1] = _truncate(lines[-1] + " ...", width)
    return lines


def _badge_label(count: int) -> str:
    return f"+{count} unchanged"


def _badge_width(count: int) -> int:
    return 6 * len(_badge_label(count)) + 14


def _order_nodes(subgraph: LineageSubgraph) -> list[list[str]]:
    ids = [n.node_id for n in subgraph.nodes]
    incoming: dict[str, list[str]] = {i: [] for i in ids}
    outgoing: dict[str, list[str]] = {i: [] for i in ids}
    for edge in subgraph.edges:
        if edge.source_node in incoming and edge.dest_node in incoming:
            incoming[edge.dest_node].append(edge.source_node)
            outgoing[edge.source_node].append(edge.dest_node)

    depth = {i: 0 for i in ids}
    for _ in range(len(ids)):
        changed = False
        for node_id in ids:
            for parent in incoming[node_id]:
                if depth[parent] + 1 > depth[node_id]:
                    depth[node_id] = depth[parent] + 1
                    changed = True
        if not changed:
            break

    columns: dict[int, list[str]] = {}
    for node_id in ids:
        columns.setdefault(depth[node_id], []).append(node_id)
    return [columns[d] for d in sorted(columns)]


def render_lineage_svg(subgraph: LineageSubgraph) -> str:
    """A standalone SVG document. Never raises — a diagram must not fail a lineage answer."""
    try:
        return _render(subgraph)
    except Exception:  # noqa: BLE001
        return _fallback(subgraph)


def _fallback(subgraph: LineageSubgraph) -> str:
    text = _xml_text(f"Lineage for {subgraph.column_name} ({len(subgraph.nodes)} nodes)")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="420" height="60" viewBox="0 0 420 60">'
        f'<rect width="420" height="60" fill="{CANVAS}" stroke="{CANVAS_STROKE}"/>'
        f'<text x="16" y="35" font-family="system-ui, sans-serif" font-size="13" fill="{INK}">{text}</text>'
        f"</svg>"
    )


def _render(subgraph: LineageSubgraph) -> str:
    by_id = {n.node_id: n for n in subgraph.nodes}
    columns = _order_nodes(subgraph)

    badge_w = max(
        (_badge_width(e.passthrough_count) for e in subgraph.edges if e.passthrough_count),
        default=0,
    )
    h_gap = max(H_GAP, badge_w + 20)

    fv_by_node: dict[str, list[str]] = {}
    for influence in subgraph.flow_variable_influences:
        label = f"{influence.variable_name} → {influence.setting_path}"
        fv_by_node.setdefault(influence.controlling_node_id, []).append(label)

    pos: dict[str, tuple[float, float]] = {}
    tallest = max((len(col) for col in columns), default=1)
    body_h = tallest * BOX_H + (tallest - 1) * V_GAP
    has_fv = bool(fv_by_node)
    fv_band = FV_BOX_H + 14 if has_fv else 0

    for c, column in enumerate(columns):
        x = MARGIN + c * (BOX_W + h_gap)
        col_h = len(column) * BOX_H + (len(column) - 1) * V_GAP
        y0 = MARGIN + HEADER_H + fv_band + (body_h - col_h) / 2
        for r, node_id in enumerate(column):
            pos[node_id] = (x, y0 + r * (BOX_H + V_GAP))

    width = MARGIN * 2 + len(columns) * BOX_W + max(len(columns) - 1, 0) * h_gap
    height = MARGIN * 2 + HEADER_H + fv_band + body_h + LEGEND_H

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" style="max-width:100%;height:auto" role="img" '
        f'aria-label="Column lineage for {_xml_text(subgraph.column_name)}">',
        "<defs>",
        f'<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{LINE}"/></marker>',
        "</defs>",
        f'<rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="{CANVAS}" '
        f'stroke="{CANVAS_STROKE}" stroke-width="1" rx="6"/>',
        '<g font-family="system-ui, -apple-system, Segoe UI, sans-serif">',
    ]

    title = f"Lineage of “{subgraph.column_name}”"
    out.append(
        f'<text x="{MARGIN}" y="{MARGIN + 16}" font-size="15" font-weight="600" fill="{INK}">{_xml_text(title)}</text>'
    )
    out.append(
        f'<text x="{MARGIN}" y="{MARGIN + 34}" font-size="11" fill="{MUTED}">'
        f"{_xml_text(_truncate(subgraph.workflow_name, 86) + ' · source → destination')}</text>"
    )

    for edge in subgraph.edges:
        if edge.source_node not in pos or edge.dest_node not in pos:
            continue
        sx, sy = pos[edge.source_node]
        dx, dy = pos[edge.dest_node]
        x1, y1 = sx + BOX_W, sy + BOX_H / 2
        x2, y2 = dx, dy + BOX_H / 2
        dest = by_id.get(edge.dest_node)
        dashed = dest is not None and dest.evidence == Evidence.INFERRED_FROM_CODE
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        mid_x = (x1 + x2) / 2
        path = f"M {x1:.0f} {y1:.0f} C {mid_x:.0f} {y1:.0f}, {mid_x:.0f} {y2:.0f}, {x2:.0f} {y2:.0f}"
        out.append(
            f'<path d="{path}" fill="none" stroke="{LINE}" stroke-width="1.6"{dash} marker-end="url(#arrow)"/>'
        )
        if edge.passthrough_count:
            label = _badge_label(edge.passthrough_count)
            label_w = _badge_width(edge.passthrough_count)
            ly = (y1 + y2) / 2 - 9
            out.append(
                f'<rect x="{mid_x - label_w / 2:.0f}" y="{ly:.0f}" width="{label_w}" height="16" rx="8" '
                f'fill="{CANVAS}" stroke="{LINE}" stroke-width="0.8"/>'
                f'<text x="{mid_x:.0f}" y="{ly + 11.5:.0f}" font-size="10" fill="{MUTED}" '
                f'text-anchor="middle">{_xml_text(label)}</text>'
            )

    for node in subgraph.nodes:
        if node.node_id not in pos:
            continue
        x, y = pos[node.node_id]
        inferred = node.evidence == Evidence.INFERRED_FROM_CODE
        box_dash = ' stroke-dasharray="6 4"' if inferred else ""
        out.append(
            f'<rect x="{x:.0f}" y="{y:.0f}" width="{BOX_W}" height="{BOX_H}" rx="6" fill="{BOX_FILL}" '
            f'stroke="{BOX_STROKE}" stroke-width="1.4"{box_dash}/>'
        )
        out.append(
            f'<text x="{x + 10:.0f}" y="{y + 20:.0f}" font-size="12" font-weight="600" fill="{INK}">'
            f"{_xml_text(_truncate(node.node_name, 30))}</text>"
        )
        for i, line in enumerate(_wrap(node.action, 36, 2)):
            out.append(
                f'<text x="{x + 10:.0f}" y="{y + 36 + i * 12:.0f}" font-size="10" fill="{MUTED}">'
                f"{_xml_text(line)}</text>"
            )
        out.append(
            f'<text x="{x + 10:.0f}" y="{y + 66:.0f}" font-size="9" fill="{MUTED}" font-style="italic">'
            f"{'inferred from code' if inferred else 'traced'}</text>"
        )

        for i, fv in enumerate(fv_by_node.get(node.node_id, [])):
            fx, fy = x, MARGIN + HEADER_H + i * (FV_BOX_H + 6)
            out.append(
                f'<path d="M {x + BOX_W / 2:.0f} {y:.0f} L {fx + BOX_W / 2:.0f} {fy + FV_BOX_H:.0f}" '
                f'stroke="{FV_STROKE}" stroke-width="1" stroke-dasharray="2 3" fill="none"/>'
                f'<rect x="{fx:.0f}" y="{fy:.0f}" width="{BOX_W}" height="{FV_BOX_H}" rx="4" '
                f'fill="{FV_FILL}" stroke="{FV_STROKE}" stroke-width="1"/>'
                f'<text x="{fx + 8:.0f}" y="{fy + 19:.0f}" font-size="10" fill="{FV_INK}">'
                f"{_xml_text('⚙ ' + _truncate(fv, 34))}</text>"
            )

    ly = height - MARGIN - 4
    out.append(
        f'<g font-size="10" fill="{MUTED}">'
        f'<line x1="{MARGIN}" y1="{ly - 4:.0f}" x2="{MARGIN + 22}" y2="{ly - 4:.0f}" stroke="{LINE}" '
        f'stroke-width="1.6"/>'
        f'<text x="{MARGIN + 28}" y="{ly:.0f}">traced</text>'
        f'<line x1="{MARGIN + 78}" y1="{ly - 4:.0f}" x2="{MARGIN + 100}" y2="{ly - 4:.0f}" stroke="{LINE}" '
        f'stroke-width="1.6" stroke-dasharray="6 4"/>'
        f'<text x="{MARGIN + 106}" y="{ly:.0f}">inferred from code</text>'
    )
    if has_fv:
        out.append(
            f'<rect x="{MARGIN + 222}" y="{ly - 11:.0f}" width="12" height="10" rx="2" fill="{FV_FILL}" '
            f'stroke="{FV_STROKE}"/>'
            f'<text x="{MARGIN + 240}" y="{ly:.0f}">flow variable (set at runtime)</text>'
        )
    out.append("</g>")
    out.append("</g></svg>")
    return "".join(out)
