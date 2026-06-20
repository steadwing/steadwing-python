"""HTTP breadcrumb capture via http.client monkey-patching."""

from __future__ import annotations

import http.client
import threading
import time
from collections import deque
from typing import Any

_breadcrumbs: deque[dict[str, Any]] = deque(maxlen=100)
_lock = threading.Lock()
_original_http_request: Any = None
_original_https_request: Any = None
_original_http_getresponse: Any = None
_original_https_getresponse: Any = None
_patched = False
_in_sdk_call = threading.local()


def get_breadcrumbs() -> list[dict[str, Any]]:
    """Return a copy of the current breadcrumbs."""
    with _lock:
        return list(_breadcrumbs)


def clear_breadcrumbs() -> None:
    """Clear all breadcrumbs."""
    with _lock:
        _breadcrumbs.clear()


def add_breadcrumb(breadcrumb: dict[str, Any]) -> None:
    """Add a breadcrumb to the rolling buffer."""
    with _lock:
        _breadcrumbs.append(breadcrumb)


def mark_sdk_call():
    """Mark current thread as making an SDK-internal HTTP call (skip breadcrumb)."""
    _in_sdk_call.active = True


def unmark_sdk_call():
    """Unmark current thread."""
    _in_sdk_call.active = False


def _patched_request(original_fn: Any):
    """Create a patched request function that records HTTP breadcrumbs."""

    def wrapper(self: Any, method: str, url: str, body: Any = None, headers: Any = None, **kwargs: Any) -> Any:
        if headers is None:
            headers = {}
        if getattr(_in_sdk_call, "active", False):
            return original_fn(self, method, url, body=body, headers=headers, **kwargs)
        start = time.time()
        try:
            result = original_fn(self, method, url, body=body, headers=headers, **kwargs)
            duration_ms = (time.time() - start) * 1000
            breadcrumb = {
                "type": "http",
                "timestamp": start,
                "data": {
                    "method": method,
                    "url": f"{self.host}{url}",
                    "duration_ms": round(duration_ms, 2),
                },
            }
            # Stash the breadcrumb on the connection so the matching
            # getresponse() call can fill in the status code.
            try:
                self._steadwing_breadcrumb = breadcrumb
            except Exception:
                pass
            add_breadcrumb(breadcrumb)
            return result
        except Exception as exc:
            duration_ms = (time.time() - start) * 1000
            add_breadcrumb({
                "type": "http",
                "timestamp": start,
                "data": {
                    "method": method,
                    "url": f"{self.host}{url}",
                    "duration_ms": round(duration_ms, 2),
                    "error": repr(exc)[:256],
                },
            })
            raise

    return wrapper


def _patched_getresponse(original_fn: Any):
    """Create a patched getresponse that records the HTTP status code."""

    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        response = original_fn(self, *args, **kwargs)
        try:
            breadcrumb = getattr(self, "_steadwing_breadcrumb", None)
            if breadcrumb is not None:
                status = getattr(response, "status", None)
                if status is not None:
                    breadcrumb["data"]["status_code"] = status
                self._steadwing_breadcrumb = None
        except Exception:
            pass
        return response

    return wrapper


def patch_http_client() -> None:
    """Monkey-patch http.client to capture outgoing HTTP requests as breadcrumbs."""
    global _original_http_request, _original_https_request, _patched
    global _original_http_getresponse, _original_https_getresponse

    if _patched:
        return

    try:
        _original_http_request = http.client.HTTPConnection.request
        http.client.HTTPConnection.request = _patched_request(_original_http_request)
        _original_http_getresponse = http.client.HTTPConnection.getresponse
        http.client.HTTPConnection.getresponse = _patched_getresponse(_original_http_getresponse)

        # HTTPSConnection normally inherits request/getresponse from HTTPConnection,
        # so the patches above already cover HTTPS. Only patch it separately on the
        # (rare) Python builds where it defines its own — patching inherited methods
        # again would double-wrap and emit two breadcrumbs per HTTPS request.
        https_conn = getattr(http.client, "HTTPSConnection", None)
        if https_conn is not None:
            if "request" in https_conn.__dict__:
                _original_https_request = https_conn.request
                https_conn.request = _patched_request(_original_https_request)
            if "getresponse" in https_conn.__dict__:
                _original_https_getresponse = https_conn.getresponse
                https_conn.getresponse = _patched_getresponse(_original_https_getresponse)

        _patched = True
    except Exception:
        pass


def unpatch_http_client() -> None:
    """Restore original http.client methods."""
    global _original_http_request, _original_https_request, _patched
    global _original_http_getresponse, _original_https_getresponse

    if not _patched:
        return

    try:
        if _original_http_request is not None:
            http.client.HTTPConnection.request = _original_http_request
        if _original_http_getresponse is not None:
            http.client.HTTPConnection.getresponse = _original_http_getresponse

        https_conn = getattr(http.client, "HTTPSConnection", None)
        if https_conn is not None:
            if _original_https_request is not None:
                https_conn.request = _original_https_request
            if _original_https_getresponse is not None:
                https_conn.getresponse = _original_https_getresponse

        _patched = False
    except Exception:
        pass
