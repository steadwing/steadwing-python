"""Background transport thread for batching and delivering events to the backend."""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
import threading
import time
from typing import Any

import httpx

from steadwing.breadcrumbs import mark_sdk_call, unmark_sdk_call
from steadwing.types import SDK_VERSION

FLUSH_INTERVAL_SECONDS = 5.0
FLUSH_BATCH_SIZE = 100
MAX_EVENT_SIZE_BYTES = 512 * 1024  # 512KB
MAX_QUEUE_SIZE = 256

DEDUP_WINDOW_SECONDS = 60.0
DEDUP_CACHE_MAX_SIZE = 1000
HTTP_TIMEOUT_SECONDS = 5.0


class Transport:
    """Background daemon thread that batches and sends events to the Steadwing backend."""

    def __init__(self, api_key: str, backend_url: str):
        self._api_key = api_key
        self._backend_url = backend_url.rstrip("/")
        self._queue: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._flush_event = threading.Event()
        self._shutdown = False
        # dedup_key -> {"ts": float, "event": dict} (event ref lets us bump count)
        self._dedup_cache: dict[str, dict[str, Any]] = {}
        self._dedup_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._http_client: httpx.Client | None = None

        # Delivery health / diagnostics.
        self._auth_failed = False
        self._auth_warned = False
        self._had_success = False
        self._last_status_code: int | None = None
        self._last_error: str | None = None
        self._events_sent = 0
        self._events_dropped = 0

    def start(self) -> None:
        """Start the background transport thread."""
        self._thread = threading.Thread(target=self._run, daemon=True, name="steadwing-transport")
        self._thread.start()

    def enqueue(self, event: dict[str, Any]) -> None:
        """Add an event to the send queue. Thread-safe."""
        try:
            # Truncate oversized events
            event_json = json.dumps(event, default=str)
            if len(event_json.encode("utf-8")) > MAX_EVENT_SIZE_BYTES:
                # Truncate large fields
                if "traceback" in event:
                    event["traceback"] = event["traceback"][:10000] + "...[truncated]"
                if "frames" in event:
                    event["frames"] = event["frames"][:10]
                if "breadcrumbs" in event:
                    event["breadcrumbs"] = event["breadcrumbs"][-50:]

            # Deduplication for exceptions (time-window based). Instead of
            # silently dropping repeats of the same error in a tight loop, we
            # send a single event carrying a `count` of how many times it fired.
            if event.get("type") == "exception":
                dedup_key = self._get_dedup_key(event)
                if dedup_key:
                    now = time.time()
                    with self._dedup_lock:
                        entry = self._dedup_cache.get(dedup_key)
                        if entry is not None and (now - entry["ts"]) < DEDUP_WINDOW_SECONDS:
                            # Same error within the window: bump the count on the
                            # original event if it's still buffered (not yet sent).
                            original = entry["event"]
                            with self._lock:
                                if any(e is original for e in self._queue):
                                    original["count"] = original.get("count", 1) + 1
                                    return
                            # Original already flushed — start a fresh window so
                            # the next occurrence is sent as a new representative.
                        event["count"] = 1
                        self._dedup_cache[dedup_key] = {"ts": now, "event": event}
                        if len(self._dedup_cache) > DEDUP_CACHE_MAX_SIZE:
                            oldest_key = next(iter(self._dedup_cache))
                            del self._dedup_cache[oldest_key]

            with self._lock:
                if len(self._queue) >= MAX_QUEUE_SIZE:
                    self._events_dropped += 1
                    return
                self._queue.append(event)
                if len(self._queue) >= FLUSH_BATCH_SIZE:
                    self._flush_event.set()
        except Exception:
            pass

    def _get_dedup_key(self, event: dict[str, Any]) -> str | None:
        """Generate a deduplication key for an exception event."""
        try:
            exc_type = event.get("exception_type", "")
            frames = event.get("frames", [])
            if frames:
                top_frame = frames[-1]
                key_str = f"{exc_type}:{top_frame.get('filename', '')}:{top_frame.get('lineno', '')}"
            else:
                key_str = f"{exc_type}:unknown"
            return hashlib.md5(key_str.encode()).hexdigest()
        except Exception:
            return None

    def _run(self) -> None:
        """Background thread loop: flush periodically or when batch is full."""
        while not self._shutdown:
            self._flush_event.wait(timeout=FLUSH_INTERVAL_SECONDS)
            self._flush_event.clear()
            self._flush()

    def _get_client(self) -> httpx.Client:
        """Get or create the persistent HTTP client with connection pooling."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.Client(
                timeout=HTTP_TIMEOUT_SECONDS,
                headers={
                    "X-API-Key": self._api_key,
                    "X-Steadwing-SDK-Version": f"python/{SDK_VERSION}",
                    "Content-Type": "application/json",
                    "Content-Encoding": "gzip",
                },
            )
        return self._http_client

    def _flush(self) -> None:
        """Send queued events, inspecting the response so failures aren't lost.

        A rejected key stops delivery (warned once), permanent client errors
        drop the batch, and transient failures (429/5xx/network) are put back on
        the queue to retry on the next flush cycle.
        """
        if self._auth_failed:
            # Known-bad key — drain so memory stays bounded, skip pointless calls.
            with self._lock:
                self._events_dropped += len(self._queue)
                self._queue.clear()
            return

        with self._lock:
            if not self._queue:
                return
            batch = self._queue[:]
            self._queue.clear()

        status: int | None = None
        error: str | None = None
        try:
            mark_sdk_call()
            payload = json.dumps({"events": batch}, default=str).encode("utf-8")
            compressed = gzip.compress(payload, compresslevel=6)
            status = self._get_client().post(f"{self._backend_url}/api/ingest", content=compressed).status_code
        except Exception as exc:  # network error / timeout / etc.
            error = f"{type(exc).__name__}: {exc}"
        finally:
            unmark_sdk_call()

        if status is not None and 200 <= status < 300:
            self._had_success = True
            self._events_sent += len(batch)
            self._last_status_code = status
            self._last_error = None
        elif status in (401, 403):
            self._auth_failed = True
            self._last_status_code = status
            self._last_error = f"authentication rejected (HTTP {status})"
            self._events_dropped += len(batch)
            if not self._auth_warned:
                self._auth_warned = True
                print(
                    f"[steadwing] API key rejected (HTTP {status}). Events will NOT be "
                    f"delivered. Check your Steadwing API key.",
                    file=sys.stderr,
                )
        elif status is not None and 400 <= status < 500 and status != 429:
            # Other 4xx won't be fixed by retrying this payload — drop it.
            self._last_status_code = status
            self._last_error = f"HTTP {status}"
            self._events_dropped += len(batch)
        else:
            # Transient: 429, 5xx, or a network exception — retain and retry.
            self._last_status_code = status
            self._last_error = error or (f"HTTP {status}" if status else "unknown error")
            with self._lock:
                self._queue = (batch + self._queue)[:MAX_QUEUE_SIZE]

    def flush_sync(self) -> None:
        """Synchronously flush remaining events. Called on shutdown / fatal paths."""
        self._flush()

    def get_health(self) -> dict[str, Any]:
        """Snapshot of delivery health for diagnostics."""
        with self._lock:
            queued = len(self._queue)
        if self._auth_failed:
            status = "unauthorized"
        elif not self._had_success and self._last_error is None:
            status = "never_sent"
        elif self._last_error is not None:
            status = "degraded"
        else:
            status = "ok"
        return {
            "status": status,
            "last_status_code": self._last_status_code,
            "last_error": self._last_error,
            "events_sent": self._events_sent,
            "events_dropped": self._events_dropped,
            "queued": queued,
        }

    def shutdown(self) -> None:
        """Stop the transport thread and flush remaining events."""
        self._shutdown = True
        self._flush_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self.flush_sync()
        if self._http_client is not None:
            try:
                self._http_client.close()
            except Exception:
                pass
