<div align="center">

# Steadwing Python SDK

**Error monitoring with AI-powered Root Cause Analysis for Python applications.**

[PyPI](https://pypi.org/project/steadwing/) | [Docs](https://docs.steadwing.com/python-sdk) | [Discord](https://discord.gg/4rUP86tSXn)

</div>

---

## Overview

The Steadwing Python SDK auto-instruments your application to capture exceptions, error logs, and HTTP breadcrumbs then sends them to Steadwing for automated Root Cause Analysis.

**Key features:**

- Automatic exception capture (including threads and async)
- `logging.error()` / `logging.critical()` forwarding
- HTTP request breadcrumbs for debugging context
- Built-in data scrubbing for sensitive request header and variable fields
- Framework integrations for FastAPI, Django, Flask, and more

## Installation

```bash
pip install steadwing
```

**Requires Python 3.10+**

## Quick Start

```python
import steadwing

steadwing.init(api_key="st_your_api_key")
```

That's it. Steadwing is now capturing errors in your application.

## Configuration

```python
steadwing.init(
    api_key="st_...",           # Required: your API key
    service="my-service",       # Service name for grouping (default: "default")
    env="PROD",                 # Deployment environment (default: "PROD")
    enabled=True,               # Set False to disable
)
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `api_key` | `str` | - | Your Steadwing API key (required) |
| `service` | `str` | `"default"` | Service name for grouping errors |
| `env` | `str` | `"PROD"` | Deployment environment (`"PROD"`, `"DEV"`, etc.) |
| `enabled` | `bool` | `True` | Toggle SDK on/off |

> **Note:** Only events sent with `env="PROD"` are considered for auto-monitoring. Events from other environments are received but will not trigger automated RCA.

## Usage

### Automatic Capture

Once initialized, Steadwing automatically captures:

- **Unhandled exceptions**: including in threads and async tasks
- **Error logs**: `logging.error()` and `logging.critical()` calls
- **Breadcrumbs**: outgoing HTTP requests, log messages (rolling buffer of last 100)

## Integrations

Steadwing provides first-class support for popular Python frameworks:

| Framework | Auto-instrumentation |
|-----------|---------------------|
| **FastAPI** | Route errors with request context |
| **Django** | Middleware-based exception capture |
| **Flask** | Error handler integration |
| **SQLAlchemy** | Database query breadcrumbs |
| **asyncio** | Async task exception capture |

Integrations are automatically activated when the corresponding library is detected.

## Data Scrubbing

Built-in redaction covers selected structured fields. For supported framework integrations (FastAPI, Django, Flask), the SDK replaces values whose exact field name matches the list below (case-insensitive) in captured request headers. Traceback-local variable names are also checked against this list.

`password` · `passwd` · `secret` · `api_key` · `apikey` · `token` · `auth` · `authorization` · `cookie` · `csrf` · `session` · `credit_card` · `ssn`

Redaction does **not** scan free-text logs, exception messages, stack traces, URLs or query strings, SQL, or values embedded inside strings. If your application may include sensitive data in these contexts, implement additional scrubbing at the application level before the data reaches Steadwing.

## Contributing

We welcome contributions! Here's how to get started:

```bash
# Clone the repository
git clone https://github.com/steadwing/steadwing-python.git
cd steadwing-python

# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest
```

## Community

- [Discord](https://discord.gg/4rUP86tSXn) - Ask questions, share feedback, and connect with the team
- [GitHub Issues](https://github.com/steadwing/steadwing-python/issues) - Report bugs or request features

## License

This project is licensed under the [Apache License 2.0](LICENSE).
