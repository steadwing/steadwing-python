"""FastAPI integration for the Steadwing SDK."""

from __future__ import annotations

import time
from typing import Any

from steadwing.hooks import build_exception_event
from steadwing.scrubber import scrub

_patched = False


def patch_fastapi(on_exception: Any) -> None:
    """Auto-patch FastAPI to capture unhandled exceptions with request context.

    Patches both FastAPI.__init__ (for future apps) and Starlette.__call__
    (for already-created apps). The __call__ patch dynamically wraps with
    exception capture at runtime, so init order doesn't matter.
    """
    global _patched

    if _patched:
        return

    try:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        import fastapi

        class SteadwingMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next: Any) -> Response:
                start_time = time.time()
                try:
                    response = await call_next(request)
                    return response
                except Exception as exc:
                    duration_ms = (time.time() - start_time) * 1000
                    request_context = {
                        "method": request.method,
                        "url_path": str(request.url.path),
                        "query_string": str(request.url.query) if request.url.query else None,
                        "duration_ms": round(duration_ms, 2),
                        "headers": scrub(dict(request.headers)),
                    }
                    try:
                        exc_type = type(exc)
                        exc_tb = exc.__traceback__
                        event_data = build_exception_event(exc_type, exc, exc_tb)
                        event_data["request_context"] = request_context
                        on_exception(event_data)
                    except Exception:
                        pass
                    raise

        # Patch FastAPI.__init__ for apps created AFTER init()
        _original_init = fastapi.FastAPI.__init__

        def _patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
            _original_init(self, *args, **kwargs)
            try:
                self.add_middleware(SteadwingMiddleware)
            except Exception:
                pass

        fastapi.FastAPI.__init__ = _patched_init

        # Patch Starlette.__call__ for apps created BEFORE init()
        # The middleware is injected on first call if not already present
        import starlette.applications

        _original_call = starlette.applications.Starlette.__call__

        async def _patched_call(self: Any, scope: dict, receive: Any, send: Any) -> None:
            if not getattr(self, "_steadwing_patched", False):
                try:
                    self.add_middleware(SteadwingMiddleware)
                    self._steadwing_patched = True
                except Exception:
                    self._steadwing_patched = True
            await _original_call(self, scope, receive, send)

        starlette.applications.Starlette.__call__ = _patched_call

        _patched = True
    except ImportError:
        pass
    except Exception:
        pass


def unpatch_fastapi() -> None:
    """Restore original FastAPI behavior."""
    global _patched
    _patched = False
