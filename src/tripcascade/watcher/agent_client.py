"""HTTP client for the TripCascade agent endpoint.

Posts `disruption_likely` events from the Watcher (Alibaba Cloud Function Compute
or local smoke test) to the agent HTTP service and returns the re-plan JSON.

Uses stdlib ``urllib.request`` (not httpx) so the watcher's critical path has
ZERO third-party dependencies — the FC function imports cleanly and degrades
gracefully even without a deps layer installed.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

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

    FC 3.0 fcapp.run WSGI HTTP triggers strip the request body (CONTENT_LENGTH=0,
    wsgi.input empty). As a workaround, the event is sent BOTH as the JSON body
    AND as a base64-encoded ``event`` query parameter. The agent reads the
    query param if the body is empty.

    Args:
        disruption_event: dict matching the `DisruptionEvent` schema.
        timeout: request timeout in seconds.

    Returns:
        parsed JSON response from the agent.

    Raises:
        RuntimeError: on non-200 / connection failure.
    """
    import base64
    import urllib.parse as up

    endpoint = get_agent_endpoint()
    url = f"{endpoint}/disruption"
    logger.info("POST %s -> %s", disruption_event.get("node_id"), url)
    body_json = json.dumps(disruption_event, default=str)
    event_b64 = base64.b64encode(body_json.encode("utf-8")).decode("ascii")
    url_with_qs = f"{url}?event={up.quote(event_b64)}"
    data = body_json.encode("utf-8")
    req = urllib.request.Request(
        url_with_qs,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500] if e.fp else ""
        raise RuntimeError(f"agent returned {e.code}: {detail}") from e
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"agent POST failed: {e}") from e