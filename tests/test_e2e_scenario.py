#!/usr/bin/env python3
"""Standalone end-to-end scenario test — the full demo flow.

This is the single runnable script that exercises the entire TripCascade system
on the scripted family-trip scenario:
  itinerary load -> forecast P(disruption) -> threshold breach -> cascade ->
  proposed re-plan -> human approval (simulated) -> re-book in Sandbox (stub) ->
  fare-difference settled -> outcome asserted.

Run:
    uv run python tests/test_e2e_scenario.py

Environment:
    - Uses the StubAtlasClient for deterministic, offline execution
    - To run against live Atlas Sandbox, see doc/README.md
    - To use real Qwen (DashScope) proposals, set TRIPCASCADE_LLM_BACKEND=dashscope
      and DASHSCOPE_API_KEY in .env

Exit code: 0 = all assertions passed, 1 = any assertion failed.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure src/ is on the path
_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
sys.path.insert(0, str(_PROJECT / "src"))

from tripcascade.agent.config import Settings
from tripcascade.agent.decision_log import DecisionLog
from tripcascade.agent.orchestrator import Orchestrator
from tripcascade.atlas_tools.client import StubAtlasClient
from tripcascade.forecast.inference import predict_disruption_prob
from tripcascade.graph.builder import build_graph, load_demo_itinerary
from tripcascade.graph.models import Outcome
from tripcascade.watcher.events import make_scripted_event, populate_forecast

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEMO_SEED = _PROJECT / "assets" / "demo_itinerary.json"
DISRUPTED_LEG = "leg1_pvg_nrt"
SCRIPTED_P = 0.82  # typhoon-augmented forecast signal
SETTLEMENT_CAP_CENTS = 5000  # S$50

EXPECTED_AFFECTED = ["hotel_tokyo", "leg2_nrt_pvg"]
EXPECTED_AUTO_AMOUNT = 3000  # cents
EXPECTED_HELD_AMOUNT = 12000  # cents


def main() -> int:
    """Run the full E2E scenario. Returns 0 on success, 1 on failure."""
    failures: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)
            print(f"  FAIL: {message}")
        else:
            print(f"  PASS: {message}")

    print("=" * 70)
    print("TripCascade — End-to-End Scenario Test")
    print("=" * 70)

    # --- Step 1: Load itinerary ---
    print("\n[Step 1] Load demo itinerary...")
    assert DEMO_SEED.exists(), f"Demo seed not found: {DEMO_SEED}"
    graph = build_graph(DEMO_SEED)
    check(graph.node_count == 3, f"graph has {graph.node_count} nodes (expected 3)")
    check(graph.edge_count >= 2, f"graph has {graph.edge_count} edges (expected >=2)")

    # --- Step 2: Run forecast ---
    print("\n[Step 2] Run disruption forecast...")
    events = populate_forecast(graph, predict_disruption_prob)
    for node in graph.nodes.values():
        if node.node_type.value == "flight":
            check(
                node.disruption_probability is not None,
                f"{node.node_id} has P(disruption) = {node.disruption_probability}",
            )
            check(
                0.0 <= (node.disruption_probability or 0.0) <= 1.0,
                f"{node.node_id} P in [0,1]",
            )
    print(f"  Forecast events emitted: {len(events)}")

    # --- Step 3: Agent orchestrator handles disruption ---
    print("\n[Step 3] Agent orchestrator handles disruption event...")
    settings = Settings(settlement_cap_cents=SETTLEMENT_CAP_CENTS)
    client = StubAtlasClient(settings)
    log = DecisionLog()
    log.clear()
    orc = Orchestrator(graph=graph, client=client, settings=settings, decision_log=log)
    event = make_scripted_event(DISRUPTED_LEG, SCRIPTED_P)
    result = orc.handle_disruption(event)

    # --- Step 4: Assert cascade ---
    print("\n[Step 4] Cascade assertions...")
    check(not result.given_up, f"orchestrator did NOT give up (reason: {result.give_up_reason})")
    check(
        result.cascade is not None,
        "cascade result is not None",
    )
    check(
        result.cascade.affected_node_ids == EXPECTED_AFFECTED,
        f"affected nodes = {result.cascade.affected_node_ids} (expected {EXPECTED_AFFECTED})",
    )

    # --- Step 5: Assert leg 1 auto-settled ---
    print("\n[Step 5] Leg 1 auto-settlement assertions...")
    check(len(result.auto_settled) == 1, "Leg 1 auto-settled")
    if result.auto_settled:
        a = result.auto_settled[0]
        check(a.node_id == DISRUPTED_LEG, f"auto-settled node = {a.node_id}")
        check(
            a.amount_cents == EXPECTED_AUTO_AMOUNT,
            f"auto amount = {a.amount_cents}c (expected {EXPECTED_AUTO_AMOUNT}c)",
        )
        check(a.amount_cents <= SETTLEMENT_CAP_CENTS, "auto amount <= cap")

    # --- Step 6: Assert hotel advisory ---
    print("\n[Step 6] Hotel advisory notification assertions...")
    hotel_notified = any(nid == "hotel_tokyo" for nid, _ in result.notifications)
    check(hotel_notified, "hotel advisory notification drafted")
    hotel_not_auto = all(d.node_id != "hotel_tokyo" for d in result.auto_settled)
    check(hotel_not_auto, "hotel was NOT auto-settled (no Atlas write)")

    # --- Step 7: Assert leg 2 held for approval ---
    print("\n[Step 7] Leg 2 held-for-approval assertions...")
    check(len(result.held_for_approval) == 1, "Leg 2 held for approval")
    if result.held_for_approval:
        h = result.held_for_approval[0]
        check(h.node_id == "leg2_nrt_pvg", f"held node = {h.node_id}")
        check(
            h.amount_cents == EXPECTED_HELD_AMOUNT,
            f"held amount = {h.amount_cents}c (expected {EXPECTED_HELD_AMOUNT}c)",
        )
        check(h.amount_cents > SETTLEMENT_CAP_CENTS, "held amount > cap")

    # --- Step 8: Assert no false success ---
    print("\n[Step 8] False-success cure assertions...")
    all_asserted = all(r.asserted for r in result.results)
    check(all_asserted, "all Atlas results have asserted post-state")

    # --- Step 9: Human approves leg 2 ---
    print("\n[Step 9] Human approval of leg 2...")
    if result.held_for_approval:
        approved = orc.approve(result.held_for_approval[0], "approved by traveler — return re-book confirmed")
        check(approved.asserted, "approved result is asserted")
        check(approved.orderNo is not None, f"approved orderNo = {approved.orderNo}")
        check(
            approved.record.outcome == Outcome.HUMAN_APPROVED,
            f"outcome = {approved.record.outcome}",
        )

    # --- Step 10: Decision log assertions ---
    print("\n[Step 10] Decision-learning log assertions...")
    recs = log.query()
    check(len(recs) == 2, f"decision log has {len(recs)} records (expected 2)")
    outcomes = {r.outcome for r in recs}
    check(
        outcomes == {Outcome.AUTO_SETTLED, Outcome.HUMAN_APPROVED},
        f"outcomes = {outcomes} (expected auto_settled + human_approved)",
    )
    for r in recs:
        check(r.reusable is True, f"{r.record_id}: reusable = True")
        check(
            r.atlas_state_refs.get("orderNo") is not None,
            f"{r.record_id}: orderNo in atlas_state_refs",
        )

    # --- Summary ---
    print("\n" + "=" * 70)
    if not failures:
        print("✅ ALL SCENARIO TESTS PASSED")
        return 0
    else:
        print(f"❌ {len(failures)} SCENARIO TEST(S) FAILED:")
        for f in failures:
            print(f"   - {f}")
        return 1


if __name__ == "__main__":
    sys.exit(main())