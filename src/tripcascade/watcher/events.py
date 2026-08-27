"""Disruption Watcher (FR-003, SPECS S-003).

The guaranteed P0 trigger is a scheduled forecast-poll: run the forecast on each
flight leg, populate `disruption_probability` on the node, and emit a
`disruption_likely` event when P(disruption) >= the alert threshold. Webhook/
incident events (`abnormal.cancelled`, `order.schedulechange`) are a best-effort
P1 complementary signal (doc/atlas_surface.md §3) — kept in `aftercare.query_incidents`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from tripcascade.agent.config import Settings, get_settings
from tripcascade.graph.models import DisruptionEvent, ItineraryGraph, Node

logger = logging.getLogger(__name__)


def populate_forecast(
    graph: ItineraryGraph,
    predict_fn,
    threshold: float | None = None,
) -> list[DisruptionEvent]:
    """Run the forecast on every flight node; populate disruption_probability.

    Args:
        graph: the trip DAG (mutated: each flight node's disruption_probability set).
        predict_fn: `tripcascade.forecast.inference.predict_disruption_prob`.
        threshold: alert threshold (defaults to settings.alert_threshold = 0.35).

    Returns:
        `disruption_likely` events for legs at/above the threshold.
    """
    settings = get_settings()
    threshold = settings.alert_threshold if threshold is None else threshold
    events: list[DisruptionEvent] = []
    for node in graph.nodes.values():
        if node.node_type.value != "flight":
            continue
        leg = node.to_forecast_leg()
        try:
            p = float(predict_fn(leg))
        except Exception as e:
            logger.warning("forecast failed for %s (%s); leaving probability null", node.node_id, e)
            continue
        node.disruption_probability = max(0.0, min(1.0, p))
        logger.info("forecast %s -> P(disruption)=%.3f (threshold=%.3f)", node.node_id, p, threshold)
        if p >= threshold:
            events.append(
                DisruptionEvent(
                    node_id=node.node_id,
                    p_disruption=p,
                    threshold=threshold,
                    ts=datetime.now(timezone.utc),
                )
            )
    return events


def make_scripted_event(
    node_id: str, p_disruption: float, threshold: float | None = None
) -> DisruptionEvent:
    """Construct a scripted `disruption_likely` event (the demo trigger).

    The acceptance criteria use a scripted event. In production this event is
    emitted by :func:`populate_forecast` (real forecast) or an Atlas webhook.
    """
    settings = get_settings()
    return DisruptionEvent(
        node_id=node_id,
        p_disruption=p_disruption,
        threshold=settings.alert_threshold if threshold is None else threshold,
        ts=datetime.now(timezone.utc),
    )
