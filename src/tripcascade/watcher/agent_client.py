"""HTTP client for the TripCascade agent endpoint.

Posts `disruption_likely` events from the Watcher (Alibaba Cloud Function Compute
or local smoke test) to the agent HTTP service and returns the re-plan JSON.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)


def get_agent_endpoint() -> str:
    """Resolve the agent endpoint URL from env (default = local smoke-test)."""
    return os.environ.get("AGENT_ENDPOINT_URL", "http://127.0.0.1:8088").rstrip("/")


def get_watcher_demo_mode() -> bool:
    """Opt-in: when truthy, the scheduled poll ALSO emits a scripted leg1 event."""
    raw = os.environ.get("WATCHER_DEMO_MODE", "").strip()
    return raw.lower() in ("1", "true", "yes", "on")


def post_disruption(disruption_event: dict, *, timeout: float = 30.0) -> dict:
    """POST a `disruption_likely` event to the agent endpoint.

    Args:
        disruption_event: dict matching the `DisruptionEvent` schema.
        timeout: httpx request timeout.

    Returns:
        parsed JSON response from the agent.

    Raises:
        RuntimeError: on non-200 / connection failure (caller decides whether to
        retry, log, or give-up).
    """
    url = f"{get_agent_endpoint()}/disruption"
    logger.info("POST %s -> %s", disruption_event.get("node_id"), url)
    try:
        resp = httpx.post(url, json=disruption_event, timeout=timeout)
        resp.raise_for_status()
    except httpx.RequestError as e:
        raise RuntimeError(f"agent POST failed: {e}") from e
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"agent returned {e.response.status_code}: {e.response.text[:500]}"
        ) from e
    return resp.json()