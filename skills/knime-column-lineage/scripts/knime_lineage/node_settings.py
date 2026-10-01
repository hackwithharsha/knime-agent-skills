"""Per-node-type normalization: category classification, settings extraction, code capture."""

from __future__ import annotations

from .models import FlowVariableBinding, NodeCategory
from .xml_config import get_path

# --- category classification -------------------------------------------------

_SOURCE_HINTS = (
    "tablecreator",
    "csv.reader",
    "csvtablereader",
    "filereader",
    "excelreader",
    "sheetreader",
    "knimetablereader",
    "dbconnector",
    "dbtableselector",
    "loopstartvariable",
    "loopstartcount",
)
_SINK_HINTS = (
    "tableview",
    "dbwrite",
    "dbinsert",
    "dbupdate",
    "excelwriter",
    "csvwriter",
)
_CODE_HINTS = (
    "pythonscript",
    "expressionrowmapper",
    "expressionrowfilter",
    "expressionflowvariable",
    "rulesengine",
    "rules.engine",
    "stringmanipulation",
    "editvar",
    "javaeditvar",
    "dbsqlquery",
    "dbexecutor",
    "dbqueryreader",
    "parameterizeddbsqlquery",
    "rsnippet",
    "javasnippet",
)
_FLOW_CONTROL_HINTS = (
    "loopstart",
    "loopend",
    "trynode",
    "try_",
    "catch",
    "breakpoint",
    "variableporttry",
    "variableportcatch",
    "virtualsubnodeinput",
    "virtualsubnodeoutput",
    "ifswitch",
    "caseswitch",
    "endcase",
)


def _matches_any(haystack: str, hints: tuple[str, ...]) -> bool:
    lowered = haystack.lower()
    return any(hint in lowered for hint in hints)


def classify_category(factory: str | None, node_name: str) -> NodeCategory:
    haystack = f"{factory or ''} {node_name}"
    if _matches_any(haystack, _FLOW_CONTROL_HINTS):
        return NodeCategory.FLOW_CONTROL
    if _matches_any(haystack, _CODE_HINTS):
        return NodeCategory.CODE
    if _matches_any(haystack, _SINK_HINTS):
        return NodeCategory.SINK
    if _matches_any(haystack, _SOURCE_HINTS):
        return NodeCategory.SOURCE
    return NodeCategory.TRANSFORM


# --- flow variable bindings --------------------------------------------------


def extract_flow_variable_bindings(variables_config: object) -> list[FlowVariableBinding]:
    if not isinstance(variables_config, dict):
        return []
    root = variables_config.get("tree", variables_config)
    if not isinstance(root, dict):
        return []

    bindings: list[FlowVariableBinding] = []

    def walk(node: object, path: list[str]) -> None:
        if isinstance(node, dict):
            if "used_variable" in node or "exposed_variable" in node:
                used = node.get("used_variable") or None
                exposed = node.get("exposed_variable") or None
                if used or exposed:
                    bindings.append(
                        FlowVariableBinding(
                            setting_path=".".join(path) or "(root)",
                            used_variable=used,
                            exposed_variable=exposed,
                        )
                    )
                return
            for key, value in node.items():
                walk(value, path + [key])
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, path + [str(index)])

    walk(root, [])
    return bindings


# --- per-node settings normalization -----------------------------------------


def _normalize_column_renamer(model: dict) -> dict:
    renamings = model.get("renamings") or []
    renames = [
        {"old": item.get("oldName"), "new": item.get("newName")}
        for item in renamings
        if isinstance(item, dict)
    ]
    return {"renames": renames}


def _normalize_column_rename_regex(model: dict) -> dict:
    return {
        "rename_regex": {
            "pattern_type": model.get("patternType"),
            "search": model.get("searchString"),
            "replace": model.get("replaceString"),
            "replacement_strategy": model.get("replacementStrategy"),
            "case_sensitivity": model.get("caseSensitivity"),
        }
    }


def _column_selection_summary(config: object) -> dict:
    if not isinstance(config, dict):
        return {}
    pattern = config.get("name_pattern") if isinstance(config.get("name_pattern"), dict) else {}
    return {
        "mode": config.get("filter-type"),
        "included": config.get("included_names") or [],
        "excluded": config.get("excluded_names") or [],
        "enforce_option": config.get("enforce_option"),
        "pattern": pattern.get("pattern") or None,
        "pattern_type": pattern.get("type"),
        "case_sensitive": pattern.get("caseSensitivity"),
    }


def _normalize_column_filter(model: dict) -> dict:
    return {"column_filter": _column_selection_summary(model.get("column-filter"))}


def _normalize_db_column_filter(model: dict) -> dict:
    return {"column_filter": _column_selection_summary(model.get("selected_columns"))}


def _as_config_values(config: object) -> list:
    if isinstance(config, dict):
        return list(config.values())
    if isinstance(config, list):
        return config
    return []


def _normalize_db_row_filter(model: dict) -> dict:
    conditions = model.get("conditions")
    predicates = []
    for cond in _as_config_values(conditions):
        if not isinstance(cond, dict):
            continue
        column = get_path(cond, "columnSpec", "name")
        operator = get_path(cond, "operation", "operator", "id")
        values = get_path(cond, "operation", "values", default=[])
        predicates.append({"column": column, "operator": operator, "value": values})
    return {"row_filter": {"predicates": predicates}}


def _normalize_joiner3(model: dict) -> dict:
    return {
        "join": {
            "left_join_columns": model.get("leftTableJoinPredicate") or [],
            "right_join_columns": model.get("rightTableJoinPredicate") or [],
            "composition_mode": model.get("compositionMode"),
            "duplicate_handling": model.get("duplicateHandling"),
            "suffix": model.get("suffix"),
            "merge_join_columns": model.get("mergeJoinColumns"),
            "include_left_unmatched": model.get("includeLeftUnmatchedInOutput"),
            "include_right_unmatched": model.get("includeRightUnmatchedInOutput"),
            "left_output_columns": _column_selection_summary(model.get("leftColumnSelectionConfig")),
            "right_output_columns": _column_selection_summary(model.get("rightColumnSelectionConfig")),
        }
    }


def _normalize_joiner2(model: dict) -> dict:
    return {
        "join": {
            "left_join_columns": model.get("leftTableJoinPredicate") or [],
            "right_join_columns": model.get("rightTableJoinPredicate") or [],
            "join_mode": model.get("joinMode"),
            "duplicate_handling": model.get("duplicateHandling"),
            "suffix": model.get("suffix"),
            "left_include_columns": model.get("leftIncludeCols") or [],
            "right_include_columns": model.get("rightIncludeCols") or [],
            "left_include_all": model.get("leftIncludeAll"),
            "right_include_all": model.get("rightIncludeAll"),
            "remove_left_join_columns": model.get("rmLeftJoinCols"),
            "remove_right_join_columns": model.get("rmRightJoinCols"),
        }
    }


def _normalize_groupby(model: dict) -> dict:
    group_columns = get_path(model, "grouByColumns", "InclList", default=[]) or []
    agg = model.get("aggregationColumn") or {}
    names = agg.get("columnNames") or []
    methods = agg.get("aggregationMethod") or []
    aggregations = [
        {"column": name, "method": methods[i] if i < len(methods) else None}
        for i, name in enumerate(names)
    ]
    return {
        "groupby": {
            "group_columns": group_columns,
            "aggregations": aggregations,
            "column_name_policy": model.get("columnNamePolicy"),
        }
    }


def _row_filter_predicate_value(filter_value_parameters: object) -> object:
    if not isinstance(filter_value_parameters, dict):
        return None
    for key in ("value", "pattern"):
        if key in filter_value_parameters:
            return filter_value_parameters[key]
    return {k: v for k, v in filter_value_parameters.items() if k != "@class"}


def _normalize_row_filter_v3(model: dict) -> dict:
    predicates = model.get("predicates")
    predicate_list = []
    items = predicates.values() if isinstance(predicates, dict) else predicates or []
    for pred in items:
        if not isinstance(pred, dict):
            continue
        column_cfg = pred.get("columnV2") or {}
        column = column_cfg.get("regularChoice") or column_cfg.get("specialChoice_Internals")
        predicate_list.append(
            {
                "column": column,
                "operator": pred.get("operator"),
                "value": _row_filter_predicate_value(pred.get("filterValueParameters")),
            }
        )
    return {
        "row_filter": {
            "match_criteria": model.get("matchCriteria"),
            "output_mode": model.get("outputMode"),
            "predicates": predicate_list,
        }
    }


def _normalize_row_filter_v1(model: dict) -> dict:
    rf = model.get("rowFilter") or {}
    return {
        "row_filter": {
            "output_mode": "MATCHING" if rf.get("include", True) else "NON_MATCHING",
            "predicates": [
                {
                    "column": rf.get("ColumnName"),
                    "operator": rf.get("RowFilter_TypeID"),
                    "value": rf.get("Pattern"),
                }
            ],
        }
    }


def _normalize_rule_based(model: dict) -> tuple[dict, str | None]:
    rules = model.get("rules") or []
    code = "\n".join(rules) if isinstance(rules, list) else None
    settings = {
        "rule_engine": {
            "new_column_name": model.get("new-column-name") or None,
            "replace_column_name": model.get("replace-column-name") or None,
            "append_column": model.get("append-column"),
        }
    }
    return settings, code


def _normalize_expression_node(model: dict) -> tuple[dict, str | None]:
    settings = {
        "expression": {
            "created_column": model.get("createdColumn"),
            "replaced_column": model.get("replacedColumn"),
            "output_mode": model.get("columnOutputMode"),
        }
    }
    return settings, model.get("script")


def _normalize_string_manipulation(model: dict) -> tuple[dict, str | None]:
    settings = {
        "string_manipulation": {
            "replaced_column": model.get("replaced_column"),
            "is_replace": model.get("append_column"),
            "return_type": model.get("return_type"),
        }
    }
    return settings, model.get("expression")


def _normalize_java_edit_variable_simple(model: dict) -> tuple[dict, str | None, list[str]]:
    variable_name = model.get("replaced_column")
    settings = {
        "flow_variable_edit": {
            "variable_name": variable_name,
            "is_new_variable": model.get("append_column"),
            "return_type": model.get("return_type"),
        }
    }
    exposed = [variable_name] if variable_name else []
    return settings, model.get("expression"), exposed


def _normalize_java_snippet_edit_variable(model: dict) -> tuple[dict, str | None, list[str]]:
    out_vars = [v for v in (model.get("outVars") or []) if isinstance(v, dict)]
    in_vars = [v for v in (model.get("inVars") or []) if isinstance(v, dict)]
    exposed = [v.get("Name") for v in out_vars if v.get("Name")]
    settings = {
        "flow_variable_edit": {
            "output_variables": [{"name": v.get("Name"), "type": v.get("Type")} for v in out_vars],
            "input_variables": [{"name": v.get("Name"), "type": v.get("Type")} for v in in_vars],
        }
    }
    return settings, model.get("scriptBody"), exposed


def _normalize_db_sql(model: dict, statement_key: str) -> tuple[dict, str | None]:
    return {}, model.get(statement_key)


_SETTINGS_ONLY_NORMALIZERS = {
    "column.renamer.ColumnRenamerNodeFactory": _normalize_column_renamer,
    "columnrenameregex.ColumnRenameRegexNodeFactory": _normalize_column_rename_regex,
    "filter.column.DataColumnSpecFilterNodeFactory": _normalize_column_filter,
    "joiner3.Joiner3NodeFactory": _normalize_joiner3,
    "joiner.Joiner2NodeFactory": _normalize_joiner2,
    "groupby.GroupByNodeFactory": _normalize_groupby,
    "filter.row3.RowFilterNodeFactory": _normalize_row_filter_v3,
    "filter.row.RowFilterNodeFactory": _normalize_row_filter_v1,
    "manipulation.filter.column.DBFilterColumnNodeFactory": _normalize_db_column_filter,
    "manipulation.filter.row.DBFilterRowNodeFactory": _normalize_db_row_filter,
}

_CODE_NORMALIZERS = {
    "rules.engine.RuleEngineNodeFactory": _normalize_rule_based,
    "rules.engine.RuleEngineFilterNodeFactory": _normalize_rule_based,
    "expressions.node.row.mapper.ExpressionRowMapperNodeFactory": _normalize_expression_node,
    "expressions.node.row.filter.ExpressionRowFilterNodeFactory": _normalize_expression_node,
    "expressions.node.variable.ExpressionFlowVariableNodeFactory": _normalize_expression_node,
    "stringmanipulation.StringManipulationNodeFactory": _normalize_string_manipulation,
}

_CODE_TEXT_KEYS = {
    "manipulation.query.DBSQLQueryNodeFactory": "sql_statement",
    "io.reader.query.DBQueryReaderNodeFactory": "sql_statement",
    "io.parameterizedquery.ParameterizedDBSQLQueryNodeFactory": "sql_statement",
    "manipulation.executor.DBExecutorNodeFactory": "statement",
    "scripting.nodes2.script.PythonScriptNodeFactory": "script",
}

_JAVA_EDIT_VARIABLE_FACTORIES = {
    "jsnippet.JavaEditVarNodeFactory": _normalize_java_snippet_edit_variable,
    "script.node.editvar.JavaEditVariableNodeFactory": _normalize_java_edit_variable_simple,
}


def normalize_node(
    factory: str | None, model: dict
) -> tuple[dict, str | None, list[str], bool]:
    """Return (settings, code, exposed_flow_variables, unrecognized)."""
    if not factory or not isinstance(model, dict):
        return {}, None, [], True

    for suffix, fn in _SETTINGS_ONLY_NORMALIZERS.items():
        if factory.endswith(suffix):
            return fn(model), None, [], False

    for suffix, fn in _CODE_NORMALIZERS.items():
        if factory.endswith(suffix):
            settings, code = fn(model)
            return settings, code, [], False

    for suffix, fn in _JAVA_EDIT_VARIABLE_FACTORIES.items():
        if factory.endswith(suffix):
            settings, code, exposed = fn(model)
            return settings, code, exposed, False

    for suffix, key in _CODE_TEXT_KEYS.items():
        if factory.endswith(suffix):
            settings, code = _normalize_db_sql(model, key)
            return settings, code, [], False

    return {"raw_model": model}, None, [], True
