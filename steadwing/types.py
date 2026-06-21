"""Event type definitions for the Steadwing SDK."""

from __future__ import annotations

import platform
import socket
import subprocess
import time
from typing import Any

SDK_VERSION = "0.1.0"


def _get_git_sha() -> str | None:
    """Attempt to get the current git commit SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _get_container_id() -> str | None:
    """Attempt to get the container ID from /proc/self/cgroup."""
    try:
        with open("/proc/self/cgroup") as f:
            for line in f:
                parts = line.strip().split("/")
                if len(parts) > 2 and len(parts[-1]) == 64:
                    return parts[-1][:12]
    except Exception:
        pass
    return None


def build_runtime_info() -> dict[str, Any]:
    """Build runtime info captured once at init time."""
    return {
        "python_version": platform.python_version(),
        "os": f"{platform.system()} {platform.release()}",
        "hostname": socket.gethostname(),
        "container_id": _get_container_id(),
        "git_sha": _get_git_sha(),
    }


def base_event(
    event_type: str,
    service: str,
    env: str,
    runtime: dict[str, Any],
) -> dict[str, Any]:
    """Create a base event dict with common fields."""
    return {
        "type": event_type,
        "service": service,
        "env": env,
        "timestamp": time.time(),
        "sdk_version": SDK_VERSION,
        "runtime": runtime,
    }
