"""Reader for KNIME's generic XMLConfig format (workflow.knime, settings.xml, spec.xml).

The format nests <config key="..."> elements, whose children are either more
<config> elements or typed <entry key="..." type="xstring|xint|xboolean|..." value="..."/>
leaves. isnull="true" marks a null entry. There are two array conventions in the
wild, both handled here by _maybe_listify:
  - "entry array": a <config> whose children are an "array-size" entry plus
    entries keyed "0", "1", ...
  - "config array": a <config> whose children are themselves <config> elements
    keyed "0", "1", ... with no array-size marker (e.g. Row Filter's predicates).

xstring values encode literal newlines/carriage-returns as %%00010 / %%00013
(a 5-digit zero-padded decimal char code after a literal "%%"). Confirmed
across annotations, scripts, and SQL text in real KNIME files; decoded
unconditionally for every xstring entry.
"""

from __future__ import annotations

import re
import zipfile
from typing import BinaryIO
from xml.etree import ElementTree as ET

_ESCAPE_RE = re.compile(r"%%(\d{5})")
_DTD_RE = re.compile(r"<!DOCTYPE\s", re.IGNORECASE)


def _decode_knime_string(value: str) -> str:
    return _ESCAPE_RE.sub(lambda m: chr(int(m.group(1))), value)


def _local_tag(elem: ET.Element) -> str:
    tag = elem.tag
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_entry(elem: ET.Element) -> object:
    if elem.get("isnull") == "true":
        return None
    entry_type = elem.get("type", "xstring")
    value = elem.get("value", "")
    if entry_type == "xboolean":
        return value == "true"
    if entry_type in ("xint", "xshort", "xbyte", "xlong"):
        try:
            return int(value)
        except ValueError:
            return value
    if entry_type in ("xdouble", "xfloat"):
        try:
            return float(value)
        except ValueError:
            return value
    return _decode_knime_string(value)


def _maybe_listify(mapping: dict[str, object]) -> object:
    keys = list(mapping.keys())
    numeric_keys = [k for k in keys if k.isdigit()]
    non_numeric_keys = [k for k in keys if not k.isdigit()]
    if not numeric_keys:
        return mapping
    if non_numeric_keys and non_numeric_keys != ["array-size"]:
        return mapping
    n = len(numeric_keys)
    try:
        return [mapping[str(i)] for i in range(n)]
    except KeyError:
        return mapping


def _parse_config_element(elem: ET.Element) -> object:
    result: dict[str, object] = {}
    for child in elem:
        tag = _local_tag(child)
        key = child.get("key")
        if key is None:
            continue
        if tag == "entry":
            result[key] = _parse_entry(child)
        elif tag == "config":
            result[key] = _parse_config_element(child)
    return _maybe_listify(result)


def parse_xconfig_bytes(data: bytes) -> dict:
    """Parse a KNIME XMLConfig document's bytes into nested dict/list/scalar values."""
    # Guard against DTD declarations; a real KNIME export never has one.
    header = data[:2000].decode("utf-8", errors="replace")
    if _DTD_RE.search(header):
        raise ValueError("Refusing to parse XML containing a DTD")
    root = ET.fromstring(data)
    parsed = _parse_config_element(root)
    return parsed if isinstance(parsed, dict) else {}


def get_path(config: dict, *keys: str, default: object = None) -> object:
    """Safely descend a chain of dict keys, returning `default` on any miss."""
    current: object = config
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


class KnwfArchive:
    """Read-only view over a .knwf zip, resolving KNIME's internal folder paths."""

    def __init__(self, path_or_stream: str | BinaryIO) -> None:
        try:
            self._zip = zipfile.ZipFile(path_or_stream)
        except zipfile.BadZipFile as exc:
            raise ValueError(f"could not parse as a zip archive: {exc}") from exc
        self._names = set(self._zip.namelist())
        self.root = self._detect_root()
        if not self.root and "workflow.knime" not in self._names:
            raise ValueError("no workflow.knime found — not a KNIME workflow export")

    def _detect_root(self) -> str:
        top_level_dirs = {name.split("/", 1)[0] for name in self._names if "/" in name}
        for candidate in top_level_dirs:
            if f"{candidate}/workflow.knime" in self._names:
                return candidate
        return ""

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> KnwfArchive:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _resolve(self, relative_path: str) -> str:
        return f"{self.root}/{relative_path}" if self.root else relative_path

    def exists(self, relative_path: str) -> bool:
        return self._resolve(relative_path) in self._names

    def read_bytes(self, relative_path: str) -> bytes:
        return self._zip.read(self._resolve(relative_path))

    def read_config(self, relative_path: str) -> dict:
        return parse_xconfig_bytes(self.read_bytes(relative_path))

    def read_text(self, relative_path: str) -> str:
        return self.read_bytes(relative_path).decode("utf-8")
