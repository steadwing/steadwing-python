"""Main SteadwingClient class — singleton that orchestrates all SDK functionality."""

from __future__ import annotations

import atexit
import os
import signal
import threading
from typing import Any

from steadwing.breadcrumbs import patch_http_client
from steadwing.hooks import patch_hooks
from steadwing.integrations.asyncio_hook import patch_asyncio
from steadwing.logging_handler import install_logging_handler
from steadwing.transport import Transport
from steadwing.types import base_event, build_runtime_info

_DEFAULT_BACKEND_URL = "https://api.steadwing.com"
_HEARTBEAT_INTERVAL = 60.0


class SteadwingClient:
    """Core SDK client that manages patching, event capture, and transport."""

    _instance: SteadwingClient | None = None
    _init_lock = threading.Lock()

    def __init__(
        self,
        api_key: str,
        service: str,
        env: str = "PROD",
        enabled: bool = True,
    ):
        self.api_key = api_key
        self.service = service
        self.env = env
        self.enabled = enabled
        self.backend_url = os.environ.get("STEADWING_BACKEND_URL", _DEFAULT_BACKEND_URL)
        self.runtime = build_runtime_info()
        self._transport: Transport | None = None
        self._heartbeat_timer: threading.Timer | None = None
        self._shutdown = False

        if self.enabled:
            self._setup()

    def _setup(self) -> None:
        """Set up transport, patches, and heartbeat."""
        # Start transport
        self._transport = Transport(api_key=self.api_key, backend_url=self.backend_url)
        self._transport.start()

        # Install exception hooks
        patch_hooks(on_exception=self._handle_exception)

        # Install logging handler
        install_logging_handler(on_log_event=self._handle_log_event)

        # Patch http.client for breadcrumbs
        patch_http_client()

        # Capture unhandled errors from asyncio tasks / event loop
        patch_asyncio(on_exception=self._handle_exception)

        # Auto-detect and patch supported frameworks
        self._try_patch_frameworks()

        # Start heartbeat
        self._start_heartbeat()

        # Register shutdown handlers (atexit + SIGTERM for containers)
        atexit.register(self._atexit_handler)
        try:
            signal.signal(signal.SIGTERM, lambda *_: self._atexit_handler())
        except (OSError, ValueError):
            pass

    def _try_patch_frameworks(self) -> None:
        """Auto-detect and patch supported frameworks and DB libraries."""
        # FastAPI
        try:
            import fastapi  # noqa: F401

            from steadwing.integrations.fastapi import patch_fastapi

            patch_fastapi(on_exception=self._handle_exception)
        except ImportError:
            pass
        except Exception:
            pass

        # Django
        try:
            import django  # noqa: F401

            from steadwing.integrations.django import patch_django

            patch_django(on_exception=self._handle_exception)
        except ImportError:
            pass
        except Exception:
            pass

        # Django DB (query breadcrumbs)
        try:
            from django.db.backends.utils import CursorWrapper  # noqa: F401

            from steadwing.integrations.django_db import patch_django_db

            patch_django_db()
        except ImportError:
            pass
        except Exception:
            pass

        # Flask
        try:
            import flask  # noqa: F401

            from steadwing.integrations.flask import patch_flask

            patch_flask(on_exception=self._handle_exception)
        except ImportError:
            pass
        except Exception:
            pass

        # SQLAlchemy (query breadcrumbs)
        try:
            import sqlalchemy  # noqa: F401

            from steadwing.integrations.sqlalchemy import patch_sqlalchemy

            patch_sqlalchemy()
        except ImportError:
            pass
        except Exception:
            pass

    def _handle_exception(self, event_data: dict[str, Any], flush: bool = False) -> None:
        """Handle a captured exception event.

        Args:
            event_data: The exception event payload.
            flush: If True (uncaught/thread/async errors that kill the process),
                flush the transport synchronously so the event isn't lost.
        """
        if not self.enabled or self._transport is None:
            return

        try:
            event = base_event("exception", self.service, self.env, self.runtime)
            event.update(event_data)
            self._transport.enqueue(event)
            if flush:
                self._transport.flush_sync()
        except Exception:
            pass

    def _handle_log_event(self, log_data: dict[str, Any]) -> None:
        """Handle a captured log event."""
        if not self.enabled or self._transport is None:
            return

        try:
            event = base_event("log", self.service, self.env, self.runtime)
            event.update(log_data)
            self._transport.enqueue(event)
        except Exception:
            pass

    def _start_heartbeat(self) -> None:
        """Start the recurring heartbeat timer."""
        if self._shutdown:
            return

        def heartbeat() -> None:
            if self._shutdown:
                return
            try:
                event = base_event("heartbeat", self.service, self.env, self.runtime)
                event["status"] = "healthy"
                if self._transport is not None:
                    self._transport.enqueue(event)
            except Exception:
                pass
            # Reschedule
            if not self._shutdown:
                self._heartbeat_timer = threading.Timer(_HEARTBEAT_INTERVAL, heartbeat)
                self._heartbeat_timer.daemon = True
                self._heartbeat_timer.start()

        self._heartbeat_timer = threading.Timer(_HEARTBEAT_INTERVAL, heartbeat)
        self._heartbeat_timer.daemon = True
        self._heartbeat_timer.start()

    def _atexit_handler(self) -> None:
        """Flush remaining events on process exit."""
        self._shutdown = True
        if self._heartbeat_timer is not None:
            self._heartbeat_timer.cancel()
        if self._transport is not None:
            self._transport.shutdown()

    @classmethod
    def get_instance(cls) -> SteadwingClient | None:
        """Get the singleton instance."""
        return cls._instance

    @classmethod
    def set_instance(cls, instance: SteadwingClient) -> None:
        """Set the singleton instance."""
        with cls._init_lock:
            cls._instance = instance
