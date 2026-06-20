"""Background transport thread for batching and delivering events to the backend."""

from __future__ import annotations

import gzip
import hashlib
import json
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
        """Send all queued events to the backend."""
        with self._lock:
            if not self._queue:
                return
            batch = self._queue[:]
            self._queue.clear()

        try:
            mark_sdk_call()
            payload = json.dumps({"events": batch}, default=str).encode("utf-8")
            compressed = gzip.compress(payload, compresslevel=6)
            self._get_client().post(
                f"{self._backend_url}/api/ingest",
                content=compressed,
            )
        except Exception:
            pass
        finally:
            unmark_sdk_call()

    def flush_sync(self) -> None:
        """Synchronously flush remaining events. Called on shutdown."""
        self._flush()

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
