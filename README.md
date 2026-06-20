# Steadwing Python SDK

Auto-captures exceptions, error logs, and HTTP breadcrumbs from Python applications and sends them to the Steadwing backend for Root Cause Analysis.

## Installation

```bash
pip install steadwing
```

## Quick Start

```python
import steadwing

steadwing.init(
    api_key="st_your_api_key",
    service="payment-service",
    environment="production",
)
```

That's it. The SDK will automatically:
- Capture unhandled exceptions (including in threads)
- Capture `logging.error()` and `logging.critical()` calls
- Record outgoing HTTP requests as breadcrumbs
- Send heartbeats every 60 seconds
- Patch FastAPI to capture route errors with request context (if installed)

## Configuration

```python
steadwing.init(
    api_key="st_...",           # Required: your API key
    service="my-service",       # Required: service name
    environment="production",   # Optional: defaults to "production"
    enabled=True,               # Optional: set False to disable
    backend_url="https://...",  # Optional: override backend URL
)
```

The backend URL can also be set via the `STEADWING_BACKEND_URL` environment variable.

## Manual Capture

```python
import steadwing

# Capture a specific exception
try:
    risky_operation()
except Exception as e:
    steadwing.capture_exception(e)

# Capture the current exception (in an except block)
try:
    risky_operation()
except Exception:
    steadwing.capture_exception()

# Capture a message
steadwing.capture_message("Deployment completed", level="info")
```

## What Gets Captured

### Exceptions
- Full stack trace with local variables
- Exception chain (`__cause__`, `__context__`)
- Last 100 breadcrumbs leading up to the error
- Request context (for FastAPI routes)

### Logs
- `logging.error()` and `logging.critical()` are sent as events
- All log levels are recorded as breadcrumbs

### Breadcrumbs
- Outgoing HTTP requests (method, URL, duration)
- Log messages at any level
- Rolling buffer of last 100 entries

## Data Scrubbing

Sensitive data is automatically scrubbed from captured events. Keys matching the following patterns (case-insensitive) have their values replaced with `[REDACTED]`:

`password`, `passwd`, `secret`, `api_key`, `apikey`, `token`, `auth`, `authorization`, `cookie`, `csrf`, `session`, `credit_card`, `ssn`

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run specific tests
pytest tests/test_scrubber.py -v
```

## Requirements

- Python >= 3.10
- httpx >= 0.24.0
