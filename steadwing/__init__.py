"""Steadwing Python SDK — auto-captures exceptions, error logs, and HTTP breadcrumbs."""

from __future__ import annotations

from steadwing.client import SteadwingClient
from steadwing.types import SDK_VERSION

__version__ = SDK_VERSION


def init(
    api_key: str,
    service: str,
    environment: str = "PROD",
    enabled: bool = True,
) -> SteadwingClient:
    """Initialize the Steadwing SDK.

    Idempotent — returns existing client if already initialized.
    Pure auto-capture: no manual API needed after init.

    Args:
        api_key: Your Steadwing API key (e.g. "st_...").
        service: Name of your service (e.g. "payment-service").
        environment: Deployment environment (e.g. "PROD", "DEV").
        enabled: Whether to enable capture (default True). Set False to disable.

    Returns:
        The initialized SteadwingClient instance.
    """
    existing = SteadwingClient.get_instance()
    if existing is not None:
        return existing

    client = SteadwingClient(
        api_key=api_key,
        service=service,
        environment=environment,
        enabled=enabled,
    )
    SteadwingClient.set_instance(client)
    return client
