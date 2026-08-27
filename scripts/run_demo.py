"""Headless demo runner for TripCascade.

Runs the scripted scenario end-to-end and prints the trip graph, per-leg forecast,
cascade, policy verdicts, and the decision-learning log. Use for verification and
demo capture; the interactive UI is `python -m tripcascade.ui.app`.

Run: uv run python scripts/run_demo.py
"""

from __future__ import annotations

import logging

from tripcascade.agent.config import get_settings
from tripcascade.agent.decision_log import DecisionLog
from tripcascade.agent.orchestrator import Orchestrator
from tripcascade.atlas_tools.client import StubAtlasClient
from tripcascade.forecast.inference import predict_disruption_prob
from tripcascade.graph.builder import load_demo_itinerary
from tripcascade.ui.app import render_decisions, render_graph, render_log
from tripcascade.watcher.events import make_scripted_event, populate_forecast

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> None:
    log = DecisionLog()
    log.clear()
    graph = load_demo_itinerary()

    print("=" * 72)
    print("TripCascade — scripted disruption scenario")
    print("=" * 72)

    # 1. wire the forecast (real P(disruption) per leg)
    populate_forecast(graph, predict_disruption_prob)
    print("\n" + render_graph(graph))

    # 2. scripted disruption event on leg1 (typhoon-augmented forecast signal)
    event = make_scripted_event("leg1_pvg_nrt", 0.82)
    print(f"\n>>> Disruption event: {event.node_id} P={event.p_disruption:.0%} (threshold={event.threshold})")

    # 3. orchestrator: cascade -> discovery -> propose -> policy -> assert
    orc = Orchestrator(graph=graph, client=StubAtlasClient(get_settings()), decision_log=log)
    res = orc.handle_disruption(event)

    print("\n" + render_graph(graph, res.cascade))
    print("\n" + render_decisions(res))

    # 4. human approves the held above-cap leg2
    if res.held_for_approval:
        held = res.held_for_approval[0]
        print(f"\n>>> Human approves held re-plan: {held.node_id} ({held.verdict})")
        approved = orc.approve(held, "approved by traveler — return re-book confirmed")
        print(f"    -> orderNo={approved.orderNo} asserted={approved.asserted} outcome={approved.record.outcome.value}")

    print("\n" + render_log(log))
    print("=" * 72)
    print(f"given_up={res.given_up} steps={res.steps_taken} | decisions={len(res.decisions)} "
          f"records={len(log.query())}")
    print("=" * 72)


if __name__ == "__main__":
    main()
