"""
Parser for KNIME's generic "NodeSettings" XML config format
(xmlns="http://www.knime.org/2008/09/XMLConfig"), used by both workflow.knime
and per-node settings.xml files. See references/knwf-format.md for a
description of the format, reverse-engineered and verified against real .knwf
samples.

This module is also the skill's redaction boundary: every string that reaches
the agent's context passes through _redact_value(), so credential fields and
embedded-userinfo URLs are replaced before the agent ever sees them. Never
bypass it by reading workflow.knime or a node's settings.xml directly.
"""

import re
from collections.abc import Iterator
from xml.etree.ElementTree import Element
from xml.etree.ElementTree import fromstring as _stdlib_fromstring

try:  # Preferred when present, but not installable in Claude's sandbox.
    from defusedxml.ElementTree import fromstring as _safe_fromstring
except ImportError:  # pragma: no cover - depends on the environment
    _safe_fromstring = None

MAX_STRING_LEN = 2000

# A KNIME config file never declares a DTD or entities. Anything that does is
# either corrupt or hostile (entity-expansion / external-entity attacks), so
# it is refused before a parser ever sees it. This is what keeps the stdlib
# fallback below safe when defusedxml is not installed.
_DOCTYPE_RE = re.compile(rb"<!(DOCTYPE|ENTITY)\b", re.IGNORECASE)

# The plain-Python shape config_to_value() converts KNIME's XML config tree
# into — scalars plus arbitrarily nested dicts/lists, never a custom class.
JsonValue = str | int | float | bool | None | dict[str, "JsonValue"] | list["JsonValue"]

# Wrapper metadata and UI/layout noise that carries no documentation-relevant information.
_SKIP_CONFIG_KEYS = {
    "external_to_knime_mapping",
    "knime_to_external_mapping",
    "ports",
    "filestores",
    "factory_settings",
    "flow_stack",
    "internal_node_subsettings",
    "ui_settings",
    "styles",
}
_SKIP_ENTRY_KEYS = {
    "annotation-version",
    "bgcolor",
    "x-coordinate",
    "y-coordinate",
    "width",
    "height",
    "alignment",
    "borderSize",
    "borderColor",
    "defFontSize",
    "hasContent",
    "isInactive",
    "layoutJSON",
    "configurationLayoutJSON",
    "customCSS",
    "hideInWizard",
}

_ESCAPE_RE = re.compile(r"%%(\d{5})")
_SECRET_KEY_RE = re.compile(r"password|credential|secret|token|apikey|api_key|auth", re.IGNORECASE)
_SECRET_VALUE_RE = re.compile(r"[a-zA-Z][\w+.-]*://[^/\s:@]+:[^/\s@]+@")


def parse_config_xml(data: bytes) -> Element:
    """Parse one KNIME config XML document from untrusted bytes."""
    if _DOCTYPE_RE.search(data):
        raise ValueError("Refusing to parse XML containing a DTD or entity declaration")
    if _safe_fromstring is not None:
        return _safe_fromstring(data)
    return _stdlib_fromstring(data)


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def decode_knime_text(value: str) -> str:
    """Decode KNIME's %%NNNNN control-character escape (e.g. CR/LF in annotations).

    Note the token has no closing '%%' — tokens are concatenated directly, so
    '%%00013%%00010' is two tokens (CR+LF), not one wrapped token. A regex that
    expects a trailing '%%' consumes the next token's leading '%%' as its own
    delimiter and corrupts every token after the first.
    """
    return _ESCAPE_RE.sub(lambda m: chr(int(m.group(1))), value)


def get_entry(elem: Element | None, key: str, default: JsonValue = None) -> JsonValue:
    """Return the decoded value of a direct child <entry key="..."> or default."""
    if elem is None:
        return default
    for child in elem:
        if _local(child.tag) == "entry" and child.get("key") == key:
            if child.get("isnull") == "true":
                return default
            value = child.get("value")
            if value is None:
                return default
            vtype = child.get("type")
            if vtype == "xint":
                try:
                    return int(value)
                except ValueError:
                    return value
            if vtype == "xboolean":
                return value == "true"
            if vtype == "xdouble":
                try:
                    return float(value)
                except ValueError:
                    return value
            return decode_knime_text(value)
    return default


def get_config(elem: Element | None, key: str) -> Element | None:
    """Return a direct child <config key="..."> element or None."""
    if elem is None:
        return None
    for child in elem:
        if _local(child.tag) == "config" and child.get("key") == key:
            return child
    return None


def iter_configs(elem: Element | None) -> Iterator[Element]:
    """Iterate direct child <config> elements, in document order."""
    if elem is None:
        return
    for child in elem:
        if _local(child.tag) == "config":
            yield child


def _redact_value(key: str, value: JsonValue) -> JsonValue:
    if isinstance(value, str):
        if _SECRET_KEY_RE.search(key) or _SECRET_VALUE_RE.search(value):
            return "[REDACTED]"
        if len(value) > MAX_STRING_LEN:
            return value[:MAX_STRING_LEN] + f"...[TRUNCATED, {len(value)} chars total]"
    return value


def config_to_value(elem: Element) -> JsonValue:
    """
    Recursively convert a <config> element into a plain dict/list, applying
    secret redaction and long-string truncation. Intended for a node's `model`
    settings only — skips known UI/type-mapping noise.
    """
    array_size = get_entry(elem, "array-size")
    if array_size is not None:
        array_result: list[JsonValue] = []
        for i in range(int(array_size)):
            key = str(i)
            sub_config = get_config(elem, key)
            if sub_config is not None:
                array_result.append(config_to_value(sub_config))
            else:
                item = get_entry(elem, key)
                array_result.append(_redact_value(key, item))
        return array_result

    result: dict[str, JsonValue] = {}
    for child in elem:
        tag = _local(child.tag)
        key = child.get("key")
        if key is None or key in _SKIP_ENTRY_KEYS or key in _SKIP_CONFIG_KEYS or key.endswith("_Internals"):
            continue

        if tag == "entry":
            if child.get("isnull") == "true":
                continue
            value = child.get("value")
            if value is None:
                continue
            vtype = child.get("type")
            if vtype == "xint":
                try:
                    value = int(value)
                except ValueError:
                    pass
            elif vtype == "xboolean":
                value = value == "true"
            elif vtype == "xdouble":
                try:
                    value = float(value)
                except ValueError:
                    pass
            else:
                value = decode_knime_text(value)
            result[key] = _redact_value(key, value)
        elif tag == "config":
            # Redact the whole subtree when the *key* matches, before recursing —
            # a credential block can be a nested config, not just a string value.
            if _SECRET_KEY_RE.search(key):
                result[key] = "[REDACTED]"
            else:
                result[key] = config_to_value(child)
    return result
