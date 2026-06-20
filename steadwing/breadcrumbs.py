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
            # Try to get status code from response
            try:
                if hasattr(self, "getresponse"):
                    pass  # status is captured after getresponse is called
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


def patch_http_client() -> None:
    """Monkey-patch http.client to capture outgoing HTTP requests as breadcrumbs."""
    global _original_http_request, _original_https_request, _patched

    if _patched:
        return

    try:
        _original_http_request = http.client.HTTPConnection.request
        http.client.HTTPConnection.request = _patched_request(_original_http_request)

        if hasattr(http.client, "HTTPSConnection"):
            _original_https_request = http.client.HTTPSConnection.request
            http.client.HTTPSConnection.request = _patched_request(_original_https_request)

        _patched = True
    except Exception:
        pass


def unpatch_http_client() -> None:
    """Restore original http.client methods."""
    global _original_http_request, _original_https_request, _patched

    if not _patched:
        return

    try:
        if _original_http_request is not None:
            http.client.HTTPConnection.request = _original_http_request
        if _original_https_request is not None and hasattr(http.client, "HTTPSConnection"):
            http.client.HTTPSConnection.request = _original_https_request
        _patched = False
    except Exception:
        pass
