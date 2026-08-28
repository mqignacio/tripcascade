"""Thin HTTP service wrapping the TripCascade orchestrator.

Exposes the agent as a reachable endpoint so the cloud Watcher can POST
`disruption_likely` events and receive the re-plan JSON. Uses stdlib only
(zero new deps — `http.server`).

The orchestrator uses :class:`StubAtlasClient` (deterministic, no Sandbox
rate-limit flakiness) by default; set `TRIPCASCADE_LLM_BACKEND=dashscope` in
`.env` for real Qwen proposals (requires DASHSCOPE_API_KEY).

Run:
  uv run python -m tripcascade.agent.http_service --port 8088
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

from tripcascade.agent.config import get_settings
from tripcascade.agent.decision_log import DecisionLog
from tripcascade.agent.orchestrator import Orchestrator
from tripcascade.atlas_tools.client import StubAtlasClient
from tripcascade.graph.builder import load_demo_itinerary
from tripcascade.agent.orchestrator import OrchestratorResult
from tripcascade.graph.models import DisruptionEvent

logger = logging.getLogger(__name__)


class _AgentHandler(BaseHTTPRequestHandler):
    """GET /health | POST /disruption (body: DisruptionEvent JSON)."""

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"status": "ok", "product": "TripCascade"})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/disruption":
            self._json(404, {"error": "not found"})
            return
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length > 0 else {}
        event = DisruptionEvent(**body) if body.get("node_id") else None
        if event is None:
            self._json(400, {"error": "missing or invalid DisruptionEvent body"})
            return
        result = _orchestrator_handle(event)
        self._json(200, result)

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, default=str, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info(fmt % args)


# Module-level singleton (lazy-init on first request) to avoid loading the
# forecast + graph on import (fast startup; cheap on first real call).
_ORCH: Orchestrator | None = None
_GRAPH: Any = None


def _orchestrator_handle(event: DisruptionEvent) -> dict:
    global _ORCH, _GRAPH
    if _ORCH is None:
        settings = get_settings()
        _GRAPH = load_demo_itinerary()
        _ORCH = Orchestrator(
            graph=_GRAPH,
            client=StubAtlasClient(settings),
            decision_log=DecisionLog(),
            settings=settings,
        )
    res: OrchestratorResult = _ORCH.handle_disruption(event)
    return {
        "event": {"node_id": res.event.node_id, "p_disruption": res.event.p_disruption},
        "cascade": res.cascade.model_dump() if res.cascade else None,
        "decisions": [_d.model_dump() for _d in res.decisions],
        "notifications": list(res.notifications),
        "results": [
            {
                "orderNo": r.orderNo,
                "asserted": r.asserted,
                "record": r.record.model_dump() if r.record else None,
            }
            for r in res.results
        ],
        "records": [r.model_dump() for r in res.records],
        "given_up": res.given_up,
        "give_up_reason": res.give_up_reason,
        "steps_taken": res.steps_taken,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="TripCascade agent HTTP service")
    parser.add_argument("--port", type=int, default=8088, help="listen port")
    parser.add_argument("--host", default="127.0.0.1", help="bind address")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    server = HTTPServer((args.host, args.port), _AgentHandler)
    print(f"TripCascade agent HTTP service listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
    print("\nshutdown")


# ─── Alibaba Cloud FC HTTP-trigger entry point ──────────────────

def fc_http_handler(event: Any, context: Any = None) -> str:
    """FC HTTP-trigger entry point for the agent service.

    FC 3.0 fcapp.run serves the return value verbatim as the body, so we return
    a JSON string. Handles GET /health + POST /disruption.
    Reuses the same event-parsing logic as the watcher's http_event_handler.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    evt = _parse_fc_http_event(event)
    method = evt["method"].upper()
    path = evt["path"]
    logger.info("fc_http_handler: raw_event_type=%s parsed_method=%s parsed_path=%s",
               type(event).__name__, method, path)

    if method == "GET" and path in ("/", "/health"):
        return json.dumps({"status": "ok", "product": "TripCascade"})

    if method == "POST" and path == "/disruption":
        try:
            body = json.loads(evt["body"]) if evt["body"] else {}
        except json.JSONDecodeError:
            return json.dumps({"error": "invalid JSON body", "raw_body": evt["body"][:200]})
        event_obj = DisruptionEvent(**body) if body.get("node_id") else None
        if event_obj is None:
            return json.dumps({"error": "missing or invalid DisruptionEvent body", "parsed": evt})
        result = _orchestrator_handle(event_obj)
        return json.dumps(result, default=str)

    return json.dumps({"error": "not found"})


def _parse_fc_http_event(event: Any) -> dict:
    """Normalize an FC HTTP-trigger event into {method, path, body}.

    FC 3.0 fcapp.run passes a WSGI environ dict (keys: REQUEST_METHOD,
    PATH_INFO, wsgi.input, CONTENT_LENGTH). Handles WSGI + the event-function
    schemas (method/httpMethod, path/url, requestContext.http.*) as fallbacks.
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

    # WSGI environ (FC 3.0 fcapp.run standard HTTP trigger)
    if "REQUEST_METHOD" in event or "wsgi.input" in event:
        method = event.get("REQUEST_METHOD", "GET")
        path = event.get("PATH_INFO", "/")
        body = ""
        fp = event.get("wsgi.input")
        if fp is not None and method in ("POST", "PUT", "PATCH"):
            # CONTENT_LENGTH may be missing/0 even when a body exists; read
            # what's available, falling back to a generous max if absent.
            content_length = int(event.get("CONTENT_LENGTH", 0) or 0)
            try:
                if content_length > 0:
                    body = fp.read(content_length).decode(errors="replace")
                else:
                    # Best-effort read when CONTENT_LENGTH is absent (FC quirk).
                    try:
                        fp.seek(0, 2)  # seek to end
                        size = fp.tell()
                        fp.seek(0)
                        if size > 0:
                            body = fp.read(size).decode(errors="replace")
                    except (AttributeError, OSError, ValueError):
                        pass
            except Exception:
                body = ""
        return {"method": method, "path": path, "body": body}

    # Event-function schemas (fallback)
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


if __name__ == "__main__":
    main()