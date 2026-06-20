"""Sensitive data scrubbing for the Steadwing SDK."""

from __future__ import annotations

from typing import Any

DENY_LIST = frozenset({
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "token",
    "auth",
    "authorization",
    "cookie",
    "csrf",
    "session",
    "credit_card",
    "ssn",
})

REDACTED = "[REDACTED]"
MAX_DEPTH = 10


def _is_sensitive_key(key: str) -> bool:
    """Check if a key matches the deny-list (case-insensitive)."""
    return key.lower() in DENY_LIST


def scrub(data: Any, _depth: int = 0) -> Any:
    """Recursively scrub sensitive data from dicts and lists.

    Replaces values whose keys match the deny-list with "[REDACTED]".
    Stops recursion at MAX_DEPTH to prevent infinite loops on circular references.
    """
    if _depth >= MAX_DEPTH:
        return data

    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if isinstance(key, str) and _is_sensitive_key(key):
                result[key] = REDACTED
            else:
                result[key] = scrub(value, _depth + 1)
        return result
    elif isinstance(data, (list, tuple)):
        return [scrub(item, _depth + 1) for item in data]
    else:
        return data
