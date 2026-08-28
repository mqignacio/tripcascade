"""TripCascade Disruption Watcher — Alibaba Cloud Function Compute entry point.

Trigger modes (dispatched via :func:`dispatch`):

  - **timer**  — scheduled forecast-poll (P0, guaranteed). Loads the demo
    itinerary, runs `populate_forecast` (real P per leg, logged), and — in demo
    mode (`WATCHER_DEMO_MODE=1`) — emits a scripted typhoon-augmented leg1
    `disruption_likely` event (P=0.82, disclosed per tasks/04). Each event is
    POSTed to the agent endpoint.
  - **http**   — WSGI, dispatched by path: GET `/health` → 200; POST `/webhook`
    → Atlas webhook event ingest (P1 stretch; doc/atlas_surface.md §3).
  - **direct** — internal mode used by the local smoke test (calls dispatch
    without starting an HTTP server).

``handler(event, context)`` and ``http_handler(environ, start_response)`` are thin
adapters for the FC Python runtime. The core logic lives in ``dispatch()`` so it
can be tested without a real FC instance.

Entry-point mapping in s.yaml::

    handler: tripcascade.watcher.fc_function.handler      # Timer trigger
    http_handler: tripcascade.watcher.fc_function.http_handler  # HTTP trigger
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

SCRIPTED_DEMO_NODE = "leg1_pvg_nrt"
SCRIPTED_DEMO_P = 0.82  # typhoon-augmented forecast signal (tasks/04 disclosure)

# NOTE: tripcascade.* imports are LAZY (inside functions) so this module loads
# cleanly on Alibaba Cloud Function Compute even before third-party deps
# (pydantic, joblib, numpy, sklearn, xgboost) are installed. The health check
# path needs zero third-party deps; the Timer poll degrades gracefully if the
# forecast/graph deps are unavailable.


def dispatch(trigger: str, payload: dict | None = None) -> dict:
    """Core dispatch: normalize trigger kind + payload, run the logic, return a dict.

    Args:
        trigger: one of ``"timer"``, ``"http"``, ``"direct"``.
        payload: for "http" this is ``{"method":"GET"/"POST","path":"...","body":"..."}``;
            for "timer" this is ``{"triggerTime":"..."}`` or ``{}``.

    Returns:
        ``{"status": <int>, "body": <dict>, "headers": <dict>}``.
    """
    if trigger == "http":
        return _dispatch_http(payload or {})
    if trigger in ("timer", "direct"):
        return _dispatch_timer()
    return {"status": 400, "body": {"error": f"unknown trigger: {trigger}"}, "headers": {}}


# ─── HTTP dispatch ──────────────────────────────────────────────

def _dispatch_http(payload: dict) -> dict:
    method = payload.get("method", "GET").upper()
    path = payload.get("path", "/")

    if method == "GET" and path in ("/", "/health"):
        return _http_response(200, {"status": "ok", "product": "TripCascade"})

    if method == "POST" and path == "/webhook":
        return _handle_webhook(payload.get("body", ""))

    return _http_response(404, {"error": "not found"})


def _handle_webhook(raw_body: str) -> dict:
    """Ingest an Atlas webhook POST (P1 stretch; best-effort delivery).

    Event types of interest (doc/atlas_surface.md §3):
    abnormal.cancelled, order.schedulechange, email.schedulechange.
    Translates into a `disruption_likely` event and POSTs to the agent.
    """
    try:
        body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body
    except json.JSONDecodeError:
        return _http_response(400, {"error": "invalid JSON"})

    event_type = body.get("eventType", "")
    order_no = body.get("orderNo", "")
    logger.info("webhook received: type=%s orderNo=%s", event_type, order_no)

    if event_type in ("abnormal.cancelled", "order.schedulechange", "email.schedulechange"):
        # construct a disruption_likely event from the webhook signal.
        # P(disruption) is 1.0 (confirmed disruption, not a forecast).
        disruption_event = {
            "event_type": "disruption_likely",
            "node_id": SCRIPTED_DEMO_NODE,  # map to the demo itinerary's leg1
            "p_disruption": 1.0,            # confirmed disruption (not forecast)
            "threshold": 0.35,
            "ts": datetime.now(timezone.utc).isoformat(),
            "source": f"atlas-webhook:{event_type}",
            "webhook_body": body,
        }
        try:
            from tripcascade.watcher.agent_client import post_disruption
            agent_response = post_disruption(disruption_event)
            logger.info("agent response: %s", json.dumps(agent_response, default=str)[:500])
            return _http_response(202, {"status": "dispatched", "agent": agent_response})
        except Exception as e:
            logger.error("agent dispatch failed: %s", e)
            return _http_response(502, {"error": f"agent unreachable: {e}"})

    return _http_response(200, {"status": "ignored", "eventType": event_type})


def _http_response(status: int, body: dict) -> dict:
    return {"status": status, "body": body, "headers": {"Content-Type": "application/json"}}


# ─── Timer dispatch (scheduled forecast-poll, P0) ───────────────

def _dispatch_timer() -> dict:
    # Lazy imports: these pull in pydantic (graph models) + joblib (forecast).
    # If unavailable, the dispatch logs the error and returns gracefully — the
    # health check path never touches these.
    try:
        from tripcascade.forecast.inference import predict_disruption_prob
        from tripcascade.graph.builder import load_demo_itinerary
        from tripcascade.watcher.agent_client import get_watcher_demo_mode, post_disruption
        from tripcascade.watcher.events import make_scripted_event, populate_forecast
    except ImportError as e:
        logger.error("Timer dispatch: missing dependency (%s). Install deps on FC.", e)
        return _http_response(500, {
            "status": "error",
            "error": f"missing dependency: {e}. See doc/deploy_watcher.md §8 (install deps).",
        })

    graph = load_demo_itinerary()
    events = populate_forecast(graph, predict_disruption_prob)

    # demo mode: inject the scripted typhoon-augmented event (disclosed)
    if get_watcher_demo_mode():
        demo_event = make_scripted_event(SCRIPTED_DEMO_NODE, SCRIPTED_DEMO_P)
        events.append(demo_event)
        logger.info(
            "DEMO MODE: injected scripted %s P=%.2f (typhoon-augmented trigger; "
            "real forecast also ran + logged above)",
            demo_event.node_id,
            demo_event.p_disruption,
        )

    results: list[dict] = []
    for evt in events:
        payload = evt.model_dump(mode="json")
        try:
            agent_response = post_disruption(payload)
            results.append({"node_id": evt.node_id, "status": "dispatched", "agent": agent_response})
        except Exception as e:
            results.append({"node_id": evt.node_id, "status": "error", "error": str(e)})
            logger.error("agent POST failed for %s: %s", evt.node_id, e)

    body = {
        "status": "ok",
        "trigger": "timer",
        "events_emitted": len(events),
        "results": results,
    }
    return _http_response(200, body)


# ─── FC Python runtime adapters ─────────────────────────────────

def handler(event: Any, context: Any = None) -> dict:
    """Timer-trigger entry point (Alibaba Cloud Function Compute Python runtime).

    The FC runtime calls ``handler(event, context)`` for Timer triggers. `event`
    may be a dict, bytes, or str depending on trigger config. Normalize and
    delegate to :func:`dispatch`.

    Returns a dict (marshalled by FC) — or raise an exception for the FC
    error-logging path (Timer triggers don't serve an HTTP response).
    """
    try:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        result = dispatch("timer", {})
        logger.info("timer dispatch complete: %s", json.dumps(result["body"], default=str)[:500])
        return result["body"]
    except Exception:
        logger.exception("timer dispatch failed")
        raise


def http_handler(environ: dict, start_response) -> list[bytes]:
    """WSGI entry point for Alibaba Cloud FC HTTP triggers.

    Called by the FC runtime when the function is configured as an HTTP trigger
    (WSGI mode). FC provides a WSGI-compatible environ + start_response callback.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/")
    body_raw = _read_wsgi_body(environ)
    result = dispatch(
        "http",
        {"method": method, "path": path, "body": body_raw},
    )
    status_line = f"{result['status']} OK"
    headers = [(k, v) for k, v in result["headers"].items()]
    start_response(status_line, headers)
    body_bytes = json.dumps(result["body"], default=str).encode()
    return [body_bytes]


def http_event_handler(event: Any, context: Any = None) -> dict:
    """FC HTTP-trigger entry point (event-function model).

    FC's standard HTTP trigger calls ``handler(event, context)`` where ``event``
    is the HTTP request serialized as a dict/JSON-str. This adapter normalizes
    the event (handling the common FC schemas), delegates to :func:`dispatch`,
    and returns the FC HTTP response format
    (``{isBase64Encoded, statusCode, headers, body}``).

    Note: FC does NOT allow HTTP + Timer triggers on the same function, so the
    HTTP function (``watcher-http``) and Timer function (``watcher-poll``) are
    deployed as two functions under one service — see ``deploy/fc_watcher/s.yaml``.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    evt = _parse_fc_http_event(event)
    result = dispatch("http", evt)
    return {
        "isBase64Encoded": False,
        "statusCode": result["status"],
        "headers": result["headers"],
        "body": json.dumps(result["body"], default=str),
    }


def _parse_fc_http_event(event: Any) -> dict:
    """Normalize an FC HTTP-trigger event into {method, path, body}.

    Defensive: handles dict | JSON-str | bytes, and multiple FC event schemas
    (``method``/``httpMethod``, ``path``/``url``, requestContext.http.*).
    """
    if isinstance(event, (bytes, bytearray)):
        event = event.decode(errors="replace")
    if isinstance(event, str):
        try:
            event = json.loads(event)
        except json.JSONDecodeError:
            event = {}
    if not isinstance(event, dict):
        event = {}

    rc = event.get("requestContext", {}) or {}
    rc_http = rc.get("http", {}) or {}
    method = (
        event.get("method")
        or event.get("httpMethod")
        or rc_http.get("method")
        or event.get("requestMethod")
        or "GET"
    )
    path = (
        event.get("path")
        or event.get("url")
        or rc_http.get("path")
        or event.get("requestPath")
        or "/"
    )
    body = event.get("body") or event.get("rawBody") or ""
    if event.get("isBase64Encoded") and body:
        import base64

        try:
            body = base64.b64decode(body).decode(errors="replace")
        except Exception:
            pass
    return {"method": method, "path": path, "body": body}


def _read_wsgi_body(environ: dict) -> str:
    content_length = int(environ.get("CONTENT_LENGTH", 0) or 0)
    if content_length <= 0:
        return ""
    fp = environ.get("wsgi.input")
    if fp is None:
        return ""
    return fp.read(content_length).decode(errors="replace")


# ─── Local smoke-test harness (runs in-process, no FC needed) ────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print("=== health ===")
    r = dispatch("http", {"method": "GET", "path": "/health"})
    print(json.dumps(r, default=str, indent=2))
    print()
    print("=== timer (with demo mode) ===")
    os.environ.setdefault("WATCHER_DEMO_MODE", "1")  # demo mode ON for direct run
    os.environ.setdefault("AGENT_ENDPOINT_URL", "http://127.0.0.1:8088")
    r = dispatch("timer", {})
    print(json.dumps(r, default=str, indent=2))