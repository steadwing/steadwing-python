# KT: steadwing-python

## What this is

This is the Python SDK for Steadwing. People add it to their Python app, and it watches for errors and sends them to Steadwing's backend. The backend then runs an automated Root Cause Analysis (RCA) on them.

The user only has to do this:

```python
import steadwing
steadwing.init(api_key="st_...", service="my-service", env="PROD")
```

After that, everything happens on its own. There's no manual "capture this error" call. The only other public function is `steadwing.get_health()`, which tells you whether events are actually reaching the backend.

The package is published on PyPI as `steadwing`. It needs Python 3.10+, and its only dependency is `httpx`.

## What it captures

1. **Crashes**: any exception that nobody catches, whether it happens in the main thread, a background thread, or an asyncio task.
2. **Error logs**: any `logging.error()` or `logging.critical()` call.
3. **Breadcrumbs**: a rolling list of the last 100 things that happened before the error, like outgoing HTTP calls, log lines at any level, and DB queries. These get attached to each exception so the RCA has context.
4. **Heartbeats**: a small "I'm alive" ping every 60 seconds.

Each event also includes some runtime info, collected once at startup: Python version, OS, hostname, container ID, and git SHA.

## How it works

`init()` creates a single `SteadwingClient`. If you call `init()` again, you get the same client back. The client then hooks itself into the app:

| What it hooks | Where | How |
|---|---|---|
| Uncaught exceptions | `hooks.py` | Replaces `sys.excepthook` and wraps `threading.Thread.run` |
| Async errors | `integrations/asyncio_hook.py` | Sets an exception handler on event loops |
| Logs | `logging_handler.py` | Adds a handler to the root logger |
| HTTP breadcrumbs | `breadcrumbs.py` | Monkey-patches `http.client` |
| FastAPI / Django / Flask | `integrations/` | Adds middleware, signal handlers or wrappers so request info (method, path, headers) is attached |
| SQLAlchemy / Django ORM | `integrations/` | Records DB queries as breadcrumbs |

Framework integrations only switch on if that library is installed. The check is in `_try_patch_frameworks()` in `client.py`.

All captured events go to the **Transport** (`transport.py`). It runs as a background thread that:

- puts events in a queue (max 256) and sends them in gzipped batches to `POST /api/ingest` every 5 seconds, or sooner once 100 events are waiting
- merges repeats of the same exception within 60 seconds into one event with a `count`, instead of sending it many times
- cuts down events bigger than 512 KB
- retries on 429, 5xx and network errors, and drops the batch on any other 4xx
- stops sending if it gets a 401/403 (bad API key), and prints a single warning to stderr

When the process is about to die (an uncaught crash, a thread crash or an async crash), the SDK sends events right away instead of waiting for the next batch. It also flushes on normal exit (`atexit`) and on `SIGTERM`. The SIGTERM handler passes the signal on to the app's own handler, so it doesn't break graceful shutdown in containers.

## Data scrubbing

`scrubber.py` replaces some values with `[REDACTED]` when the field name exactly matches a short list like `password`, `token` or `authorization`. It only runs on request headers and on local variables in stack traces. It does **not** look inside log messages, exception text, URLs or SQL. The README spells this out, so keep the two in sync if you change it.

## Design rules to keep

- **Never break the host app.** Almost everything is wrapped in `try/except: pass`. The downside is that SDK bugs fail quietly, so use `get_health()` or set `STEADWING_BACKEND_URL` to a local server when debugging.
- **Always call the original.** Every patch saves the original function or handler and calls it afterwards.
- **Don't capture yourself.** The SDK's own HTTP calls are flagged (`mark_sdk_call`) so they don't show up as breadcrumbs. Logs from `steadwing`, `httpx`, `httpcore` and `urllib3` are ignored so they don't cause loops.
- **Patch only once.** Each module has a `_patched` flag.

## Config

- `api_key` (required), `service` (default `"default"`), `env` (default `"PROD"`), `enabled` (default `True`).
- Only events with `env="PROD"` trigger automatic RCA on the backend.
- The `STEADWING_BACKEND_URL` env var overrides the backend URL (default `https://api.steadwing.com`).

## Releasing

Every push to `main` builds the package and publishes it to PyPI (`.github/workflows/publish.yml`). This means:

- Bump `version` in `pyproject.toml` before merging to main. PyPI rejects a version that already exists, so the publish job will fail otherwise.
- Also bump `SDK_VERSION` in `steadwing/types.py`. It's set separately, and it's what gets sent with every event. **Right now they don't match: `pyproject.toml` says `0.1.4` but `types.py` says `0.1.3`.**

