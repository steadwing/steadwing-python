"""SQLAlchemy integration for DB query breadcrumbs."""

from __future__ import annotations

import time

from steadwing.breadcrumbs import add_breadcrumb

_patched = False


def patch_sqlalchemy() -> None:
    """Auto-patch SQLAlchemy to capture DB queries as breadcrumbs.

    Hooks into SQLAlchemy's event system to record query text, duration,
    and errors for every executed query.
    """
    global _patched

    if _patched:
        return

    try:
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        @event.listens_for(Engine, "before_cursor_execute")
        def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            conn.info.setdefault("steadwing_query_start", []).append(time.time())

        @event.listens_for(Engine, "after_cursor_execute")
        def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            start_times = conn.info.get("steadwing_query_start")
            if not start_times:
                return
            start = start_times.pop()
            duration_ms = (time.time() - start) * 1000

            add_breadcrumb({
                "type": "db",
                "timestamp": start,
                "data": {
                    "statement": _truncate_query(statement),
                    "duration_ms": round(duration_ms, 2),
                },
            })

        @event.listens_for(Engine, "handle_error")
        def _handle_error(exception_context):
            conn = exception_context.connection
            start_times = conn.info.get("steadwing_query_start") if conn else None
            start = start_times.pop() if start_times else time.time()
            duration_ms = (time.time() - start) * 1000

            add_breadcrumb({
                "type": "db",
                "timestamp": start,
                "data": {
                    "statement": _truncate_query(exception_context.statement or ""),
                    "duration_ms": round(duration_ms, 2),
                    "error": str(exception_context.original_exception)[:256],
                },
            })

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


def unpatch_sqlalchemy() -> None:
    """Mark as unpatched. SQLAlchemy event listeners persist for engine lifetime."""
    global _patched
    _patched = False
