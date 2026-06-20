"""Django integration for the Steadwing SDK."""

from __future__ import annotations

import sys
from typing import Any

from steadwing.hooks import build_exception_event
from steadwing.scrubber import scrub

_patched = False
_on_exception_callback: Any = None


def patch_django(on_exception: Any) -> None:
    """Auto-patch Django to capture unhandled exceptions with request context.

    Hooks into Django's got_request_exception signal which fires when a view
    raises an unhandled exception. The signal provides the request object
    and the sender (the handler class).
    """
    global _patched, _on_exception_callback

    if _patched:
        return

    try:
        from django.core.signals import got_request_exception

        _on_exception_callback = on_exception

        got_request_exception.connect(_on_got_request_exception)

        _patched = True
    except ImportError:
        pass
    except Exception:
        pass


def _on_got_request_exception(sender, request=None, **kwargs):
    """Signal handler for Django's got_request_exception."""
    if _on_exception_callback is None:
        return

    exc_type, exc_value, exc_tb = sys.exc_info()
    if exc_type is None:
        return

    try:
        event_data = build_exception_event(exc_type, exc_value, exc_tb)
        if request is not None:
            event_data["request_context"] = _extract_request_context(request)
        _on_exception_callback(event_data)
    except Exception:
        pass


def _extract_request_context(request) -> dict[str, Any]:
    """Extract request context from Django HttpRequest."""
    headers = {}
    for key, value in request.META.items():
        if key.startswith("HTTP_"):
            header_name = key[5:].lower().replace("_", "-")
            headers[header_name] = value

    return {
        "method": request.method,
        "url_path": request.path,
        "query_string": request.META.get("QUERY_STRING", ""),
        "headers": scrub(headers),
    }


def unpatch_django() -> None:
    """Restore original Django behavior."""
    global _patched, _on_exception_callback

    if not _patched:
        return

    try:
        from django.core.signals import got_request_exception

        got_request_exception.disconnect(_on_got_request_exception)
        _on_exception_callback = None
        _patched = False
    except Exception:
        pass
