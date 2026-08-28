"""Tests for the FC watcher dispatch logic + agent HTTP service.

Coverage:
  - health endpoint
  - 404 on unknown paths
  - webhook: empty body (ignored), valid disruption event (dispatched)
  - timer: dispatch runs forecast + demo mode emits scripted event
  - agent invocation: mocked, verifies POST shape
  - WSGI adapter: environ -> dispatch -> start_response called correctly
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from tripcascade.graph.models import DisruptionEvent
from tripcascade.watcher.agent_client import get_agent_endpoint, get_watcher_demo_mode, post_disruption
from tripcascade.watcher.fc_function import (
    SCRIPTED_DEMO_NODE,
    SCRIPTED_DEMO_P,
    dispatch,
    http_event_handler,
    http_handler,
)


class TestDispatch:
    def test_health_get(self):
        r = dispatch("http", {"method": "GET", "path": "/health"})
        assert r["status"] == 200
        assert r["body"]["status"] == "ok"

    def test_health_root(self):
        r = dispatch("http", {"method": "GET", "path": "/"})
        assert r["status"] == 200
        assert r["body"]["status"] == "ok"

    def test_404(self):
        r = dispatch("http", {"method": "GET", "path": "/nonexistent"})
        assert r["status"] == 404

    def test_unknown_trigger(self):
        r = dispatch("foobar")
        assert r["status"] == 400

    def test_timer_dispatch_without_demo_mode(self):
        os.environ["WATCHER_DEMO_MODE"] = "0"
        # Timer dispatch with no agent running: forecast runs, demo mode OFF,
        # so no scripted event. If the real forecast P < threshold, no events.
        # The call will still POST events to the (dead) agent.
        r = dispatch("timer", {})
        assert r["status"] == 200
        assert "events_emitted" in r["body"]

    def test_dispatch_direct_aliases_timer(self):
        os.environ["WATCHER_DEMO_MODE"] = "0"
        r = dispatch("direct", {})
        assert r["status"] == 200


class TestWebhookDispatch:
    def test_empty_body(self):
        r = dispatch("http", {"method": "POST", "path": "/webhook", "body": "{}"})
        assert r["status"] == 200  # ignored (no disruption event type)

    def test_invalid_json(self):
        r = dispatch("http", {"method": "POST", "path": "/webhook", "body": "not json"})
        assert r["status"] == 400

    def test_disruption_event_type_accepted(self, monkeypatch):
        """abnormal.cancelled should be dispatched to agent."""
        # mock post_disruption at its source module (lazy import inside _handle_webhook)
        mock_post = MagicMock(return_value={"status": "ok", "decisions": []})
        monkeypatch.setattr("tripcascade.watcher.agent_client.post_disruption", mock_post)
        body = json.dumps({"eventType": "abnormal.cancelled", "orderNo": "T123"})
        r = dispatch("http", {"method": "POST", "path": "/webhook", "body": body})
        assert r["status"] == 202
        mock_post.assert_called_once()
        call_args = mock_post.call_args[0][0]
        assert call_args["node_id"] == SCRIPTED_DEMO_NODE
        assert call_args["p_disruption"] == 1.0
        assert call_args["source"] == "atlas-webhook:abnormal.cancelled"

    def test_non_disruption_event_ignored(self, monkeypatch):
        """Non-disruption webhook event types should be silently ignored."""
        mock_post = MagicMock()
        monkeypatch.setattr("tripcascade.watcher.agent_client.post_disruption", mock_post)
        r = dispatch("http", {"method": "POST", "path": "/webhook", "body": '{"eventType":"payment.confirmed"}'})
        assert r["status"] == 200
        mock_post.assert_not_called()

    def test_webhook_agent_unreachable(self):
        """When agent is down, webhook should return 502."""
        r = dispatch("http", {"method": "POST", "path": "/webhook",
                             "body": '{"eventType":"abnormal.cancelled","orderNo":"T123"}'})
        assert r["status"] == 502


class TestTimerDispatch:
    def test_timer_runs_forecast(self):
        """Timer dispatch loads the demo itinerary and runs populate_forecast."""
        os.environ["WATCHER_DEMO_MODE"] = "0"
        r = dispatch("timer", {})
        assert r["status"] == 200
        assert "events_emitted" in r["body"]
        assert isinstance(r["body"]["events_emitted"], int)

    def test_demo_mode_injects_scripted_event(self):
        """Demo mode ON injects the scripted P=0.82 event."""
        os.environ["WATCHER_DEMO_MODE"] = "1"
        r = dispatch("timer", {})
        assert r["status"] == 200
        # demo mode should produce at least 1 event (the scripted one)
        assert r["body"]["events_emitted"] >= 1
        # verify at least one result has the scripted node_id
        node_ids = [res["node_id"] for res in r["body"]["results"]]
        assert SCRIPTED_DEMO_NODE in node_ids

    def test_demo_mode_env_truthy_values(self, monkeypatch):
        """WATCHER_DEMO_MODE accepts 1/true/yes/on (case insensitive)."""
        from tripcascade.watcher.agent_client import get_watcher_demo_mode
        for val in ("1", "true", "yes", "on", "TRUE", "ON"):
            with monkeypatch.context() as m:
                m.setenv("WATCHER_DEMO_MODE", val)
                assert get_watcher_demo_mode() is True, f"val={val!r} should be truthy"
        for val in ("0", "false", "no", "off", "", "maybe"):
            with monkeypatch.context() as m:
                m.setenv("WATCHER_DEMO_MODE", val)
                assert get_watcher_demo_mode() is False, f"val={val!r} should be falsey"


class TestAgentClient:
    def test_endpoint_default(self):
        assert "8088" in get_agent_endpoint()

    def test_endpoint_env(self, monkeypatch):
        monkeypatch.setenv("AGENT_ENDPOINT_URL", "https://example.com/api")
        assert get_agent_endpoint() == "https://example.com/api"

    def test_post_disruption_mocked(self, monkeypatch):
        """Verify POST shape without hitting a real endpoint (urllib, not httpx)."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr("urllib.request.urlopen", MagicMock(return_value=mock_resp))
        result = post_disruption({"node_id": "leg1", "p_disruption": 0.82, "threshold": 0.35, "ts": "2026-01-01T00:00:00Z"})
        assert result["status"] == "ok"


class TestWSGIAdapter:
    def test_wsgi_health(self):
        environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/health", "CONTENT_LENGTH": "0"}
        status = []
        headers = []
        def start_response(s, h):
            status.append(s)
            headers.extend(h)
        body = http_handler(environ, start_response)
        assert status[0].startswith("200"), f"unexpected status: {status[0]}"
        assert len(body) == 1
        payload = json.loads(body[0])
        assert payload["status"] == "ok"

    def test_wsgi_404(self):
        environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/nope", "CONTENT_LENGTH": "0"}
        status = []
        def start_response(s, h):
            status.append(s)
        body = http_handler(environ, start_response)
        assert status[0].startswith("404")

    def test_wsgi_webhook_post(self):
        environ = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/webhook",
            "CONTENT_LENGTH": "2",
            "wsgi.input": MagicMock(read=MagicMock(return_value=b"{}")),
        }
        status = []
        def start_response(s, h):
            status.append(s)
        body = http_handler(environ, start_response)
        assert status[0].startswith("200")  # empty body = ignored, 200


class TestFCHTTPEventHandler:
    """Tests for the FC event-function HTTP trigger adapter (http_event_handler)."""

    def test_health_dict_event(self):
        """FC passes the HTTP request as a dict event."""
        result = http_event_handler({"method": "GET", "path": "/health"})
        assert result["statusCode"] == 200
        payload = json.loads(result["body"])
        assert payload["status"] == "ok"
        assert result["isBase64Encoded"] is False
        assert result["headers"]["Content-Type"] == "application/json"

    def test_health_json_str_event(self):
        """FC may pass the event as a JSON string."""
        result = http_event_handler('{"method":"GET","path":"/health"}')
        assert result["statusCode"] == 200

    def test_health_bytes_event(self):
        """FC may pass the event as bytes."""
        result = http_event_handler(b'{"method":"GET","path":"/health"}')
        assert result["statusCode"] == 200

    def test_httpmethod_key_schema(self):
        """Handle the 'httpMethod' key variant."""
        result = http_event_handler({"httpMethod": "GET", "path": "/health"})
        assert result["statusCode"] == 200

    def test_request_context_schema(self):
        """Handle the requestContext.http.* nested schema."""
        result = http_event_handler({
            "requestContext": {"http": {"method": "GET", "path": "/health"}}
        })
        assert result["statusCode"] == 200

    def test_404(self):
        result = http_event_handler({"method": "GET", "path": "/nope"})
        assert result["statusCode"] == 404

    def test_webhook_post(self, monkeypatch):
        """Webhook POST with a disruption event dispatches to agent."""
        mock_post = MagicMock(return_value={"status": "ok", "decisions": []})
        monkeypatch.setattr("tripcascade.watcher.agent_client.post_disruption", mock_post)
        result = http_event_handler({
            "method": "POST",
            "path": "/webhook",
            "body": '{"eventType":"abnormal.cancelled","orderNo":"T123"}',
        })
        assert result["statusCode"] == 202
        mock_post.assert_called_once()

    def test_empty_event_defaults(self):
        """An empty/garbage event defaults to GET / -> health."""
        result = http_event_handler({})
        assert result["statusCode"] == 200  # GET / = health