"""Flask integration for the Steadwing SDK."""

from __future__ import annotations

from typing import Any

from steadwing.hooks import build_exception_event
from steadwing.scrubber import scrub

_patched = False
_captured_exceptions: set[int] = set()


def patch_flask(on_exception: Any) -> None:
    """Auto-patch Flask to capture unhandled exceptions with request context.

    Patches Flask.__call__ (WSGI level) to intercept all exceptions before
    Flask swallows them. Also connects to got_request_exception signal as backup.
    This matches the Sentry approach of WSGI-level wrapping.
    """
    global _patched

    if _patched:
        return

    try:
        import flask
        from flask.signals import got_request_exception

        _original_call = flask.Flask.__call__

        def _patched_call(self, environ, start_response):
            try:
                return _original_call(self, environ, start_response)
            except Exception as exc:
                exc_id = id(exc)
                if exc_id not in _captured_exceptions:
                    _captured_exceptions.add(exc_id)
                    try:
                        exc_type = type(exc)
                        exc_tb = exc.__traceback__
                        event_data = build_exception_event(exc_type, exc, exc_tb)
                        event_data["request_context"] = _extract_request_context_from_environ(environ)
                        on_exception(event_data)
                    except Exception:
                        pass
                raise

        flask.Flask.__call__ = _patched_call

        def _on_got_request_exception(sender, exception, **kwargs):
            try:
                exc_id = id(exception)
                if exc_id in _captured_exceptions:
                    _captured_exceptions.discard(exc_id)
                    return
                if not flask.has_request_context():
                    return
                exc_type = type(exception)
                exc_tb = exception.__traceback__
                event_data = build_exception_event(exc_type, exception, exc_tb)
                event_data["request_context"] = _extract_flask_request_context()
                on_exception(event_data)
            except Exception:
                pass

        got_request_exception.connect(_on_got_request_exception)

        _patched = True
    except ImportError:
        pass
    except Exception:
        pass


def _extract_request_context_from_environ(environ: dict) -> dict[str, Any]:
    """Extract request context from WSGI environ."""
    headers = {}
    for key, value in environ.items():
        if key.startswith("HTTP_"):
            header_name = key[5:].lower().replace("_", "-")
            headers[header_name] = value

    return {
        "method": environ.get("REQUEST_METHOD", ""),
        "url_path": environ.get("PATH_INFO", ""),
        "query_string": environ.get("QUERY_STRING", ""),
        "headers": scrub(headers),
    }


def _extract_flask_request_context() -> dict[str, Any]:
    """Extract request context from Flask's active request."""
    from flask import request

    headers = {}
    for key, value in request.headers:
        headers[key.lower()] = value

    return {
        "method": request.method,
        "url_path": request.path,
        "query_string": request.query_string.decode("utf-8", errors="ignore"),
        "headers": scrub(headers),
    }


def unpatch_flask() -> None:
    """Restore original Flask behavior."""
    global _patched
    _patched = False
