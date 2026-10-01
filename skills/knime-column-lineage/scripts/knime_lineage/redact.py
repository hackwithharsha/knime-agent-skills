"""Secret redaction for parsed node settings and code text."""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

_SECRET_KEY_RE = re.compile(
    r"password|passwd|secret|token|credential|api[_-]?key", re.IGNORECASE
)
_CONN_STRING_CREDS_RE = re.compile(
    r"(://[^:/\s]+:)([^@\s]+)(@)", re.IGNORECASE
)
_INLINE_KEYVALUE_SECRET_RE = re.compile(
    r"((?:password|passwd|pwd|secret|token)\s*=\s*)([^;&\s]+)", re.IGNORECASE
)


def redact_text(value: str) -> str:
    """Redact credential-shaped substrings inside a free-text value (code, URLs)."""
    redacted = _CONN_STRING_CREDS_RE.sub(rf"\1{REDACTED}\3", value)
    redacted = _INLINE_KEYVALUE_SECRET_RE.sub(rf"\1{REDACTED}", redacted)
    return redacted


def _is_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY_RE.search(key))


def redact_settings(value: object, key: str | None = None) -> object:
    """Recursively redact a parsed settings structure (dict/list/scalar)."""
    if key is not None and _is_secret_key(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: redact_settings(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_settings(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
