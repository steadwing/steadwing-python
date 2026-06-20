"""Exception hooks for sys.excepthook and threading patches."""

from __future__ import annotations

import sys
import threading
import traceback
from typing import Any

from steadwing.breadcrumbs import get_breadcrumbs
from steadwing.scrubber import scrub

_original_excepthook: Any = None
_original_thread_run: Any = None
_patched = False
_on_exception_callback: Any = None

MAX_LOCAL_VAR_LENGTH = 1024
MAX_STACK_FRAMES = 50


def _extract_locals(tb: Any) -> list[dict[str, Any]]:
    """Extract local variables from traceback frames."""
    frames = []
    current = tb
    while current is not None:
        try:
            frame = current.tb_frame
            local_vars = {}
            for key, value in frame.f_locals.items():
                if key.startswith("__"):
                    continue
                try:
                    val_repr = repr(value)
                    if len(val_repr) > MAX_LOCAL_VAR_LENGTH:
                        val_repr = val_repr[:MAX_LOCAL_VAR_LENGTH] + "..."
                    local_vars[key] = val_repr
                except Exception:
                    local_vars[key] = "<unrepresentable>"
            frames.append({
                "filename": frame.f_code.co_filename,
                "lineno": current.tb_lineno,
                "function": frame.f_code.co_name,
                "locals": scrub(local_vars),
            })
        except Exception:
            pass
        current = current.tb_next
    return frames


def _extract_exception_chain(exc: BaseException) -> list[dict[str, Any]]:
    """Extract the exception chain (__cause__ and __context__)."""
    chain = []
    seen: set[int] = set()
    current: BaseException | None = exc

    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append({
            "type": type(current).__name__,
            "module": type(current).__module__,
            "message": str(current),
        })
        # Follow __cause__ first, then __context__
        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__context__ is not None and not current.__suppress_context__:
            current = current.__context__
        else:
            current = None

    return chain


def build_exception_event(
    exc_type: type,
    exc_value: BaseException,
    exc_tb: Any,
) -> dict[str, Any]:
    """Build an exception event payload."""
    frames = _extract_locals(exc_tb) if exc_tb else []
    if len(frames) > MAX_STACK_FRAMES:
        frames = frames[-MAX_STACK_FRAMES:]
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

    return {
        "exception_type": exc_type.__name__,
        "exception_module": exc_type.__module__,
        "exception_message": str(exc_value),
        "traceback": tb_str,
        "frames": frames,
        "exception_chain": _extract_exception_chain(exc_value),
        "breadcrumbs": get_breadcrumbs(),
    }


def _steadwing_excepthook(exc_type: type, exc_value: BaseException, exc_tb: Any) -> None:
    """Custom excepthook that captures exceptions then calls the original."""
    try:
        if _on_exception_callback is not None:
            event_data = build_exception_event(exc_type, exc_value, exc_tb)
            # Uncaught exception → process is about to die. Flush synchronously
            # so startup/boot crashes still reach the backend.
            _on_exception_callback(event_data, flush=True)
    except Exception:
        pass

    # Always call the original excepthook
    if _original_excepthook is not None:
        _original_excepthook(exc_type, exc_value, exc_tb)


def _patched_thread_run(self: threading.Thread) -> None:
    """Patched Thread.run that captures exceptions in threads."""
    try:
        if _original_thread_run is not None:
            _original_thread_run(self)
    except Exception:
        try:
            if _on_exception_callback is not None:
                exc_type, exc_value, exc_tb = sys.exc_info()
                if exc_type is not None:
                    event_data = build_exception_event(exc_type, exc_value, exc_tb)
                    # Thread is dying from this exception — flush before re-raise.
                    _on_exception_callback(event_data, flush=True)
        except Exception:
            pass
        raise


def patch_hooks(on_exception: Any) -> None:
    """Install exception hooks.

    Args:
        on_exception: Callback function that receives exception event data dict.
    """
    global _original_excepthook, _original_thread_run, _patched, _on_exception_callback

    if _patched:
        return

    _on_exception_callback = on_exception

    try:
        _original_excepthook = sys.excepthook
        sys.excepthook = _steadwing_excepthook

        _original_thread_run = threading.Thread.run
        threading.Thread.run = _patched_thread_run

        _patched = True
    except Exception:
        pass


def unpatch_hooks() -> None:
    """Restore original exception hooks."""
    global _original_excepthook, _original_thread_run, _patched, _on_exception_callback

    if not _patched:
        return

    try:
        if _original_excepthook is not None:
            sys.excepthook = _original_excepthook
        if _original_thread_run is not None:
            threading.Thread.run = _original_thread_run
        _patched = False
        _on_exception_callback = None
    except Exception:
        pass
