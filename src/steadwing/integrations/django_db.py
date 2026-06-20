"""Django ORM integration for DB query breadcrumbs."""

from __future__ import annotations

import time

from steadwing.breadcrumbs import add_breadcrumb

_patched = False
_original_execute = None
_original_executemany = None


def patch_django_db() -> None:
    """Auto-patch Django's database backend to capture queries as breadcrumbs.

    Wraps CursorWrapper.execute and CursorWrapper.executemany to record
    query text, duration, and errors.
    """
    global _patched, _original_execute, _original_executemany

    if _patched:
        return

    try:
        from django.db.backends.utils import CursorWrapper

        _original_execute = CursorWrapper.execute

        def _patched_execute(self, sql, params=None):
            start = time.time()
            try:
                result = _original_execute(self, sql, params)
                duration_ms = (time.time() - start) * 1000
                add_breadcrumb({
                    "type": "db",
                    "timestamp": start,
                    "data": {
                        "statement": _truncate_query(str(sql)),
                        "duration_ms": round(duration_ms, 2),
                    },
                })
                return result
            except Exception as exc:
                duration_ms = (time.time() - start) * 1000
                add_breadcrumb({
                    "type": "db",
                    "timestamp": start,
                    "data": {
                        "statement": _truncate_query(str(sql)),
                        "duration_ms": round(duration_ms, 2),
                        "error": str(exc)[:256],
                    },
                })
                raise

        CursorWrapper.execute = _patched_execute

        _original_executemany = CursorWrapper.executemany

        def _patched_executemany(self, sql, param_list):
            start = time.time()
            try:
                result = _original_executemany(self, sql, param_list)
                duration_ms = (time.time() - start) * 1000
                add_breadcrumb({
                    "type": "db",
                    "timestamp": start,
                    "data": {
                        "statement": _truncate_query(str(sql)),
                        "duration_ms": round(duration_ms, 2),
                        "batch_size": len(param_list) if param_list else 0,
                    },
                })
                return result
            except Exception as exc:
                duration_ms = (time.time() - start) * 1000
                add_breadcrumb({
                    "type": "db",
                    "timestamp": start,
                    "data": {
                        "statement": _truncate_query(str(sql)),
                        "duration_ms": round(duration_ms, 2),
                        "error": str(exc)[:256],
                        "batch_size": len(param_list) if param_list else 0,
                    },
                })
                raise

        CursorWrapper.executemany = _patched_executemany

        _patched = True
    except ImportError:
        pass
    except Exception:
        pass


def _truncate_query(statement: str, max_length: int = 1024) -> str:
    """Truncate long SQL queries."""
    if len(statement) <= max_length:
        return statement
    return statement[:max_length] + "...[truncated]"


def unpatch_django_db() -> None:
    """Restore original Django cursor behavior."""
    global _patched, _original_execute, _original_executemany

    if not _patched:
        return

    try:
        from django.db.backends.utils import CursorWrapper

        if _original_execute is not None:
            CursorWrapper.execute = _original_execute
        if _original_executemany is not None:
            CursorWrapper.executemany = _original_executemany
        _patched = False
    except Exception:
        _patched = False
