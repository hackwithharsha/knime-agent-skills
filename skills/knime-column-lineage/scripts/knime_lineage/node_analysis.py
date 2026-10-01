"""Per-node-type lineage analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Evidence, JoinCandidate, NodeInfo

_DOLLAR_BRACKET_RE = re.compile(r'\$\["([^"]+)"\]')
_DOLLAR_RULE_RE = re.compile(r"\$([^$]+)\$")
_SQL_ALIAS_RE_TEMPLATE = r'\bAS\s+"?{}"?\b'
_PYTHON_COL_REF_RE = re.compile(r'''\[["']([^"']+)["']\]''')
_SQL_KEYWORDS = {
    "select", "as", "from", "where", "and", "or", "not", "null", "is",
    "case", "when", "then", "else", "end", "in", "on", "join", "group",
    "by", "order", "having", "distinct", "table",
}


def _sql_defines_column(sql: str, column: str) -> bool:
    pattern = _SQL_ALIAS_RE_TEMPLATE.format(re.escape(column))
    return bool(re.search(pattern, sql, re.IGNORECASE))


def _sql_referenced_columns(sql: str, derived_column: str) -> set[str]:
    pattern = _SQL_ALIAS_RE_TEMPLATE.format(re.escape(derived_column))
    match = re.search(pattern, sql, re.IGNORECASE)
    if not match:
        return set()
    segment = sql[: match.start()]
    segment = segment.rsplit(",", 1)[-1]
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", segment)
    return {t for t in tokens if t.lower() not in _SQL_KEYWORDS and t != derived_column}


def _python_assignment_info(code: str, column: str) -> tuple[bool, bool, set[str]]:
    esc = re.escape(column)
    line_re = re.compile(rf'''["']{esc}["']\s*\]\s*=''')
    for line in code.splitlines():
        if line_re.search(line):
            rhs = line.split("=", 1)[1] if "=" in line else ""
            also_read = column in rhs
            referenced = {c for c in _PYTHON_COL_REF_RE.findall(rhs) if c != column}
            return True, also_read, referenced
    return False, False, set()


@dataclass
class NodeAnalysis:
    touches: bool
    action: str = ""
    evidence: Evidence = Evidence.TRACED_FROM_SETTINGS
    input_wants: dict[int, set[str]] = field(default_factory=dict)
    join_candidates: list[JoinCandidate] | None = None
    settings: dict = field(default_factory=dict)


def passthrough(names: set[str]) -> NodeAnalysis:
    return NodeAnalysis(touches=False, input_wants={1: set(names)})


def _column_selection_names(selection: dict) -> set[str]:
    return set(selection.get("included") or [])


_AGGREGATION_NAME_RENDERERS = {
    "keep original name(s)": lambda column, method: column,
    "aggregation method (column name)": lambda column, method: f"{method}({column})",
    "column name (aggregation method)": lambda column, method: f"{column} ({method})",
}
_DEFAULT_AGGREGATION_POLICY = "aggregation method (column name)"


def aggregation_output_name(column: str, method: str, policy: str | None) -> str | None:
    key = (policy or "").strip().casefold() or _DEFAULT_AGGREGATION_POLICY
    renderer = _AGGREGATION_NAME_RENDERERS.get(key)
    return renderer(column, method) if renderer else None


def aggregation_output_names(column: str, method: str, policy: str | None) -> set[str]:
    exact = aggregation_output_name(column, method, policy)
    if exact is not None:
        return {exact}
    return {render(column, method) for render in _AGGREGATION_NAME_RENDERERS.values()}


def analyze_column_renamer(node: NodeInfo, wanted: set[str]) -> NodeAnalysis:
    renames = {r["new"]: r["old"] for r in node.settings.get("renames", []) if r.get("new") and r.get("old")}
    hit = wanted & set(renames)
    if not hit:
        return passthrough(wanted)
    upstream = {renames[n] for n in hit} | (wanted - hit)
    parts = [f'renames "{renames[n]}" to "{n}"' for n in sorted(hit)]
    return NodeAnalysis(
        touches=True,
        action="; ".join(parts),
        evidence=Evidence.TRACED_FROM_SETTINGS,
        input_wants={1: upstream},
        settings={"renames": node.settings.get("renames", [])},
    )


def analyze_column_filter(node: NodeInfo, wanted: set[str]) -> NodeAnalysis:
    cf = node.settings.get("column_filter", {})
    mode = cf.get("mode")
    included = _column_selection_names(cf)
    pattern = cf.get("pattern")
    hit: set[str] = set()
    if mode == "STANDARD":
        hit = wanted & included
    elif pattern:
        try:
            regex = re.compile(pattern if cf.get("pattern_type") == "Regex" else _wildcard_to_regex(pattern))
            hit = {n for n in wanted if regex.search(n)}
        except re.error:
            hit = set()
    if not hit:
        return passthrough(wanted)
    descr = f'kept via {mode} pattern "{pattern}"' if pattern and mode != "STANDARD" else f"kept ({mode} mode)"
    return NodeAnalysis(
        touches=True,
        action=f"{descr}: {', '.join(sorted(hit))}",
        evidence=Evidence.TRACED_FROM_SETTINGS,
        input_wants={1: wanted},
        settings=cf,
    )


def _wildcard_to_regex(pattern: str) -> str:
    return "^" + re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".") + "$"


def analyze_row_filter(node: NodeInfo, wanted: set[str]) -> NodeAnalysis:
    rf = node.settings.get("row_filter", {})
    predicate_columns = {p.get("column") for p in rf.get("predicates", []) if p.get("column")}
    hit = wanted & predicate_columns
    if not hit:
        return passthrough(wanted)
    predicates = [p for p in rf.get("predicates", []) if p.get("column") in hit]
    descr = "; ".join(f'filters rows where "{p["column"]}" {p.get("operator")} {p.get("value")!r}' for p in predicates)
    return NodeAnalysis(
        touches=True,
        action=descr,
        evidence=Evidence.TRACED_FROM_SETTINGS,
        input_wants={1: wanted},
        settings=rf,
    )


def analyze_groupby(node: NodeInfo, wanted: set[str]) -> NodeAnalysis:
    gb = node.settings.get("groupby", {})
    group_cols = set(gb.get("group_columns") or [])
    aggregations = gb.get("aggregations") or []
    policy = gb.get("column_name_policy") or ""

    upstream: set[str] = set()
    touched_parts: list[str] = []
    hit_any = False

    for w in wanted:
        if w in group_cols:
            upstream.add(w)
            touched_parts.append(f'group-by key "{w}"')
            hit_any = True
            continue
        matched_agg = None
        for agg in aggregations:
            col, method = agg.get("column"), agg.get("method")
            if not col or not method:
                continue
            if w in aggregation_output_names(col, method, policy):
                matched_agg = agg
                break
        if matched_agg:
            upstream.add(matched_agg["column"])
            touched_parts.append(f'aggregates "{matched_agg["column"]}" via {matched_agg["method"]} -> "{w}"')
            hit_any = True

    if not hit_any:
        return passthrough(wanted)
    return NodeAnalysis(
        touches=True,
        action="; ".join(touched_parts),
        evidence=Evidence.TRACED_FROM_SETTINGS,
        input_wants={1: upstream},
        settings=gb,
    )


def analyze_expression(node: NodeInfo, wanted: set[str]) -> NodeAnalysis:
    expr = node.settings.get("expression", {})
    created = expr.get("created_column")
    replaced = expr.get("replaced_column")
    mode = expr.get("output_mode")
    code = node.code or ""

    target = None
    if mode == "APPEND" and created in wanted:
        target = created
    elif mode == "REPLACE_EXISTING" and replaced in wanted:
        target = replaced

    if target is None:
        return NodeAnalysis(
            touches=True,
            action="passes through unchanged (untouched by this node's expression)",
            evidence=Evidence.TRACED_FROM_SETTINGS,
            input_wants={1: wanted},
            settings=expr,
        )

    referenced = set(_DOLLAR_BRACKET_RE.findall(code))
    upstream = set(wanted) - {target}
    if mode == "REPLACE_EXISTING":
        upstream.add(target)
    upstream |= referenced

    verb = "appends new column" if mode == "APPEND" else "replaces column"
    return NodeAnalysis(
        touches=True,
        action=f'{verb} "{target}" = {code.strip() or "(no script captured)"}',
        evidence=Evidence.INFERRED_FROM_CODE,
        input_wants={1: upstream},
        settings=expr,
    )


def analyze_rule_engine(node: NodeInfo, wanted: set[str]) -> NodeAnalysis:
    re_settings = node.settings.get("rule_engine", {})
    created = re_settings.get("new_column_name")
    replaced = re_settings.get("replace_column_name")
    code = node.code or ""
    target = next((t for t in (created, replaced) if t and t in wanted), None)

    referenced = set(_DOLLAR_RULE_RE.findall(code))
    if target is not None:
        upstream = (set(wanted) - {target}) | referenced
        if target == replaced:
            upstream.add(target)
        action = f'rule engine computes "{target}" from rules referencing {sorted(referenced) or "(none found)"}'
    else:
        upstream = set(wanted) | referenced
        action = "rules do not target this column by name; kept for inference"

    return NodeAnalysis(
        touches=True,
        action=action,
        evidence=Evidence.INFERRED_FROM_CODE,
        input_wants={1: upstream},
        settings=re_settings,
    )


def analyze_code_generic(node: NodeInfo, wanted: set[str]) -> NodeAnalysis:
    code = node.code or ""
    upstream: set[str] = set()
    parts: list[str] = []

    for w in wanted:
        is_target, also_read, referenced = _python_assignment_info(code, w)
        sql_defines = _sql_defines_column(code, w)
        if is_target and not also_read:
            upstream |= referenced
            parts.append(f'creates/derives "{w}" from {sorted(referenced) or "(no columns detected)"}')
        elif is_target and also_read:
            upstream.add(w)
            upstream |= referenced
            parts.append(f'modifies "{w}" in place')
        elif sql_defines:
            sql_referenced = _sql_referenced_columns(code, w)
            upstream |= sql_referenced
            parts.append(f'derives "{w}" via SQL from {sorted(sql_referenced) or "(no columns detected)"}')
        else:
            upstream.add(w)
            parts.append(f'passes "{w}" through (unconfirmed without full interpretation)')

    return NodeAnalysis(
        touches=True,
        action="; ".join(parts),
        evidence=Evidence.INFERRED_FROM_CODE,
        input_wants={1: upstream},
        settings={},
    )


def analyze_string_manipulation(node: NodeInfo, wanted: set[str]) -> NodeAnalysis:
    sm = node.settings.get("string_manipulation", {})
    target = sm.get("replaced_column")
    if target in wanted:
        upstream = set(wanted)
        return NodeAnalysis(
            touches=True,
            action=f'string manipulation modifies "{target}"',
            evidence=Evidence.INFERRED_FROM_CODE,
            input_wants={1: upstream},
            settings=sm,
        )
    return NodeAnalysis(
        touches=True,
        action="passes through (no structural pass-through guarantee for this node type)",
        evidence=Evidence.INFERRED_FROM_CODE,
        input_wants={1: wanted},
        settings=sm,
    )


def _resolve_join_side(
    wanted_name: str, left_cols: set[str], right_cols: set[str], suffix: str | None
) -> tuple[str | None, str | None]:
    if suffix and wanted_name.endswith(suffix):
        base = wanted_name[: -len(suffix)]
        if base in right_cols:
            return "right", base
    if wanted_name in left_cols and wanted_name in right_cols:
        return "left", wanted_name
    if wanted_name in left_cols:
        return "left", wanted_name
    if wanted_name in right_cols:
        return "right", wanted_name
    return None, None


def analyze_joiner(node: NodeInfo, wanted: set[str]) -> NodeAnalysis:
    join = node.settings.get("join", {})
    left_cols = _column_selection_names(join.get("left_output_columns", {})) | set(
        join.get("left_include_columns", [])
    )
    right_cols = _column_selection_names(join.get("right_output_columns", {})) | set(
        join.get("right_include_columns", [])
    )
    left_keys = set(join.get("left_join_columns", []))
    right_keys = set(join.get("right_join_columns", []))
    suffix = join.get("suffix")

    input_wants: dict[int, set[str]] = {1: set(), 2: set()}
    parts: list[str] = []
    candidates: list[JoinCandidate] = []
    hit_any = False

    for w in wanted:
        side, upstream_name = _resolve_join_side(w, left_cols, right_cols, suffix)
        if side is None:
            input_wants[1].add(w)
            input_wants[2].add(w)
            continue
        hit_any = True
        port = 1 if side == "left" else 2
        input_wants[port].add(upstream_name)
        is_key = upstream_name in (left_keys if side == "left" else right_keys)
        role = "join key" if is_key else "pass-through column"
        parts.append(f'"{w}" is the {side}-side input\'s {role} (port {port})')
        if w in left_cols and w in right_cols:
            candidates.append(JoinCandidate(side="left", source_node="(left input)", kept=(side == "left")))
            candidates.append(JoinCandidate(side="right", source_node="(right input)", kept=(side == "right")))

    if not hit_any:
        return passthrough(wanted)
    return NodeAnalysis(
        touches=True,
        action="; ".join(parts),
        evidence=Evidence.TRACED_FROM_SETTINGS,
        input_wants={p: names for p, names in input_wants.items() if names},
        join_candidates=candidates or None,
        settings=join,
    )


def analyze_source(node: NodeInfo, wanted: set[str]) -> NodeAnalysis:
    for port_spec in node.output_specs.values():
        if port_spec.columns and any(c.name in wanted for c in port_spec.columns):
            hit = {c.name for c in port_spec.columns} & wanted
            return NodeAnalysis(
                touches=True,
                action=f"output spec confirms column(s) {sorted(hit)} originate here",
                evidence=Evidence.TRACED_FROM_SPEC,
            )

    raw = node.settings.get("raw_model", {})
    literal_hits = {w for w in wanted if appears_in_settings(raw, w)}
    if literal_hits:
        return NodeAnalysis(
            touches=True,
            action=f"settings show column(s) {sorted(literal_hits)} defined here",
            evidence=Evidence.TRACED_FROM_SETTINGS,
        )

    return NodeAnalysis(
        touches=True,
        action=f"assumed to originate here (no on-disk schema to confirm {sorted(wanted)})",
        evidence=Evidence.TRACED_FROM_SETTINGS,
    )


def produces_column_name(node: NodeInfo, column_name: str) -> bool:
    factory = node.factory or ""

    if factory.endswith("column.renamer.ColumnRenamerNodeFactory"):
        return any(r.get("new") == column_name for r in node.settings.get("renames", []))

    if factory.endswith("joiner3.Joiner3NodeFactory") or factory.endswith("joiner.Joiner2NodeFactory"):
        join = node.settings.get("join", {})
        left_cols = _column_selection_names(join.get("left_output_columns", {})) | set(
            join.get("left_include_columns", [])
        )
        right_cols = _column_selection_names(join.get("right_output_columns", {})) | set(
            join.get("right_include_columns", [])
        )
        side, _ = _resolve_join_side(column_name, left_cols, right_cols, join.get("suffix"))
        return side is not None

    if factory.endswith("groupby.GroupByNodeFactory"):
        gb = node.settings.get("groupby", {})
        if column_name in (gb.get("group_columns") or []):
            return True
        policy = gb.get("column_name_policy")
        for agg in gb.get("aggregations") or []:
            col, method = agg.get("column"), agg.get("method")
            if not col or not method:
                continue
            if column_name in aggregation_output_names(col, method, policy):
                return True
        return False

    if factory.endswith("expressions.node.row.mapper.ExpressionRowMapperNodeFactory") or factory.endswith(
        "expressions.node.row.filter.ExpressionRowFilterNodeFactory"
    ):
        expr = node.settings.get("expression", {})
        return column_name in (expr.get("created_column"), expr.get("replaced_column"))

    if factory.endswith("rules.engine.RuleEngineNodeFactory") or factory.endswith(
        "rules.engine.RuleEngineFilterNodeFactory"
    ):
        re_settings = node.settings.get("rule_engine", {})
        return column_name in (re_settings.get("new_column_name"), re_settings.get("replace_column_name"))

    if factory.endswith("stringmanipulation.StringManipulationNodeFactory"):
        return node.settings.get("string_manipulation", {}).get("replaced_column") == column_name

    code = node.code or ""
    if code:
        is_target, _, _ = _python_assignment_info(code, column_name)
        if is_target or _sql_defines_column(code, column_name):
            return True

    return appears_in_settings(node.settings, column_name)


def appears_in_settings(value: object, name: str) -> bool:
    if isinstance(value, str):
        return value == name
    if isinstance(value, dict):
        return any(appears_in_settings(v, name) for v in value.values())
    if isinstance(value, list):
        return any(appears_in_settings(v, name) for v in value)
    return False
