"""Asyncio integration: capture unhandled exceptions from tasks and the event loop.

Errors raised inside `async def` handlers, `create_task()`, `gather()`, and other
coroutines that are never awaited surface through the event loop's exception
handler rather than `sys.excepthook`. This module installs a handler on the
running loop (if any) and patches loop creation so future loops are covered too.
"""

from __future__ import annotations

import asyncio
from typing import Any

from steadwing.hooks import build_exception_event

_patched = False


def _make_handler(on_exception: Any, previous: Any) -> Any:
    """Wrap an event-loop exception handler so captured errors are forwarded."""

    def handler(loop: Any, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        if exc is not None:
            try:
                event_data = build_exception_event(type(exc), exc, exc.__traceback__)
                # Unhandled async errors are fatal-ish — flush immediately.
                on_exception(event_data, flush=True)
            except Exception:
                pass
        # Preserve prior behavior (logging the error, etc.)
        try:
            if previous is not None:
                previous(loop, context)
            else:
                loop.default_exception_handler(context)
        except Exception:
            pass

    return handler


def patch_asyncio(on_exception: Any) -> None:
    """Install an asyncio exception handler on the current and future event loops.

    Args:
        on_exception: Callback ``(event_data: dict, flush: bool)`` invoked per error.
    """
    global _patched

    if _patched:
        return

    try:
        # Cover a loop that is already running (init() called from async context).
        try:
            running = asyncio.get_running_loop()
            running.set_exception_handler(_make_handler(on_exception, running.get_exception_handler()))
        except RuntimeError:
            pass

        # Cover loops created later (the common case: init() runs before the
        # server starts its loop).
        _original_new = asyncio.new_event_loop

        def _patched_new() -> Any:
            loop = _original_new()
            try:
                loop.set_exception_handler(_make_handler(on_exception, None))
            except Exception:
                pass
            return loop

        asyncio.new_event_loop = _patched_new

        _patched = True
    except Exception:
        pass
