"""Custom logging.Handler to capture error+ logs and record breadcrumbs."""

from __future__ import annotations

import logging
import time
from typing import Any

from steadwing.breadcrumbs import add_breadcrumb


_IGNORED_LOGGERS = frozenset({"steadwing", "httpx", "httpcore", "urllib3"})


class SteadwingLoggingHandler(logging.Handler):
    """Logging handler that captures error/critical logs as events and all logs as breadcrumbs."""

    def __init__(self, on_log_event: Any = None):
        """Initialize the handler.

        Args:
            on_log_event: Callback for error/critical log events. Receives a dict with log data.
        """
        super().__init__()
        self._on_log_event = on_log_event

    def emit(self, record: logging.LogRecord) -> None:
        """Process a log record."""
        try:
            # Skip SDK-internal and HTTP library loggers to prevent infinite loops
            if any(record.name.startswith(ns) for ns in _IGNORED_LOGGERS):
                return

            # Always add as breadcrumb regardless of level
            breadcrumb = {
                "type": "log",
                "timestamp": time.time(),
                "data": {
                    "level": record.levelname,
                    "message": self.format(record) if self.formatter else record.getMessage(),
                    "module": record.module,
                },
            }
            add_breadcrumb(breadcrumb)

            # Only emit error and critical as events
            if record.levelno >= logging.ERROR and self._on_log_event is not None:
                log_data = {
                    "message": record.getMessage(),
                    "level": record.levelname,
                    "timestamp": time.time(),
                    "pathname": record.pathname,
                    "lineno": record.lineno,
                    "funcName": record.funcName,
                    "module": record.module,
                }
                self._on_log_event(log_data)
        except Exception:
            pass


_handler_instance: SteadwingLoggingHandler | None = None


def install_logging_handler(on_log_event: Any) -> SteadwingLoggingHandler:
    """Install the Steadwing logging handler on the root logger."""
    global _handler_instance

    if _handler_instance is not None:
        return _handler_instance

    handler = SteadwingLoggingHandler(on_log_event=on_log_event)
    handler.setLevel(logging.DEBUG)  # Capture all levels for breadcrumbs
    logging.getLogger().addHandler(handler)
    _handler_instance = handler
    return handler


def uninstall_logging_handler() -> None:
    """Remove the Steadwing logging handler from the root logger."""
    global _handler_instance

    if _handler_instance is not None:
        logging.getLogger().removeHandler(_handler_instance)
        _handler_instance = None
