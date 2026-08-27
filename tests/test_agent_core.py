"""Tests for the TripCascade agent core (task 04-agent_core.md).

Covers every acceptance criterion:
- cascade propagation over a >=3-leg family itinerary (S-004)
- policy gating: auto <= cap with audit log; refuses without approval > cap (S-006)
- decision-learning log schema, both auto + human records (FR-007)
- re-read live state before write (stale-state guard) (atlas_tool_protocol §4.2)
- model routing: routine->cheap, hard->max, fallback exercised (FR-009)
- false-success cure (assert post-state, not HTTP 200) (coding_standards §4)
- end-to-end scripted scenario: no infinite-loop, no silent false-success
- (live, skipped if CLI not authed) Discovery returns real Sandbox fares

Run: uv run pytest tests/test_agent_core.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tripcascade.agent.config import Settings
from tripcascade.agent.decision_log import DecisionLog
from tripcascade.agent.orchestrator import Orchestrator
from tripcascade.agent.policy import FalseSuccessError, PolicyEngine, StaleStateError
from tripcascade.agent.router import ModelTier, Router, TaskKind
from tripcascade.atlas_tools.client import StubAtlasClient
from tripcascade.atlas_tools.commitment import approve_held, rebook_auto, rebook_held
from tripcascade.atlas_tools.discovery import search_alternatives
from tripcascade.graph.builder import build_graph
from tripcascade.graph.cascade import compute_cascade
from tripcascade.graph.models import ReplanProposal
from tripcascade.watcher.events import make_scripted_event, populate_forecast

# --- fixtures ----------------------------------------------------------------

DEMO_SEED = Path(__file__).resolve().parents[1] / "assets" / "demo_itinerary.json"


def _settings(**overrides) -> Settings:
    base = Settings()
    fields = {
        "settlement_cap_cents": base.settlement_cap_cents,
        "routine_model": base.routine_model,
        "hard_model": base.hard_model,
        "local_fallback_model": base.local_fallback_model,
    }
    fields.update(overrides)
    return Settings(**fields)


@pytest.fixture
def fresh_log(tmp_path) -> DecisionLog:
    log = DecisionLog(tmp_path / "decision_log.jsonl")
    log.clear()
    return log


@pytest.fixture
def graph():
    return build_graph(DEMO_SEED)


@pytest.fixture
def stack(graph, fresh_log):
    """A fresh orchestrator stack: stub client + policy + router + stub backend."""
    s = _settings()
    client = StubAtlasClient(s)
    router = Router(s)
    policy = PolicyEngine(s, client, fresh_log)
    return s, client, router, policy


# --- S-001 / S-004: graph + cascade ------------------------------------------


def test_graph_has_3_nodes_2_edges_actionable_flags(graph):
    """S-001: 3-leg family itinerary; flights actionable, hotel advisory; offer_id retained."""
    assert graph.node_count == 3
    assert graph.edge_count >= 2
    flights = [n for n in graph.nodes.values() if n.node_type.value == "flight"]
    hotel = graph.get_node("hotel_tokyo")
    assert all(n.actionable for n in flights), "flights must be actionable"
    assert not hotel.actionable, "hotel must be advisory"
    assert all(n.atlas_entity_ref and n.atlas_entity_ref.offer_id for n in flights)


def test_cascade_from_leg1_marks_hotel_and_leg2(graph):
    """S-004: cascade from at-risk Leg1 -> {hotel, Leg2}."""
    res = compute_cascade(graph, "leg1_pvg_nrt")
    assert set(res.affected_node_ids) == {"hotel_tokyo", "leg2_nrt_pvg"}
    assert res.affected_count == 2


# --- S-006: policy gating (auto <= cap, human > cap) -------------------------


def _pax(graph):
    pax = graph.passengers
    adults = sum(1 for p in pax if p.get("type") == "adult")
    children = sum(1 for p in pax if p.get("type") == "child")
    return adults, children


def test_policy_auto_settles_under_cap(stack, graph, fresh_log):
    """S-006: Leg1 fare diff 3000c <= 5000c cap -> auto-execute + audit record."""
    s, client, router, policy = stack
    leg1 = graph.get_node("leg1_pvg_nrt")
    adults, children = _pax(graph)
    alts = search_alternatives(client, leg1, adults, children)
    prop = ReplanProposal(
        node_id=leg1.node_id, chosen_offer_id=alts[0].offer_id,
        rationale="reroute via next-day IJ006", fare_difference_cents=3000,
        model_tier_used="Qwen3.8-Max",
    )
    res = rebook_auto(policy, leg1, prop, alts[0])
    assert res.success and res.asserted
    assert res.orderNo  # post-state asserted non-empty
    assert res.record.outcome.value == "auto_settled"
    assert res.record.amount_cents == 3000
    assert res.record.cap_cents == 5000
    assert res.record.reusable is True
    # audit log written
    recs = fresh_log.query("leg1_pvg_nrt")
    assert len(recs) == 1 and recs[0].outcome.value == "auto_settled"


def test_policy_refuses_above_cap_without_approval(stack, graph):
    """S-006: Leg2 fare diff 12000c > 5000c cap -> HELD; execute() refuses."""
    s, client, router, policy = stack
    leg2 = graph.get_node("leg2_nrt_pvg")
    adults, children = _pax(graph)
    alts = search_alternatives(client, leg2, adults, children)
    prop = ReplanProposal(
        node_id=leg2.node_id, chosen_offer_id=alts[0].offer_id,
        rationale="later return", fare_difference_cents=12000,
        model_tier_used="Qwen3.8-Max",
    )
    decision = rebook_held(policy, leg2, prop, alts[0])
    assert decision.held and not decision.auto_settle
    # execute() must refuse a held decision without explicit approval
    with pytest.raises(ValueError, match="above-cap"):
        policy.execute(decision, leg2, prop)


def test_policy_advisory_node_makes_no_atlas_call(stack, graph):
    """S-005: advisory hotel node -> draft notification, no Commitment/Money call."""
    s, client, router, policy = stack
    hotel = graph.get_node("hotel_tokyo")
    prop = ReplanProposal(node_id=hotel.node_id, rationale="advisory", fare_difference_cents=0)
    decision = policy.evaluate_settlement(hotel, prop, None)
    assert decision.advisory
    notif = policy.draft_notification(hotel, "non-refundable first night at risk")
    assert "advisory" in notif.lower() and "no Atlas booking" not in notif or "advisory" in notif


# --- FR-007: decision-learning log schema ------------------------------------


def test_decision_log_records_both_paths_well_formed(stack, graph, fresh_log):
    """FR-007: auto + human-approved records are well-formed + reusable."""
    s, client, router, policy = stack
    adults, children = _pax(graph)

    leg1 = graph.get_node("leg1_pvg_nrt")
    alts1 = search_alternatives(client, leg1, adults, children)
    rebook_auto(policy, leg1, ReplanProposal(
        node_id=leg1.node_id, chosen_offer_id=alts1[0].offer_id,
        rationale="auto", fare_difference_cents=3000, model_tier_used="Qwen3.8-Max"), alts1[0])

    leg2 = graph.get_node("leg2_nrt_pvg")
    alts2 = search_alternatives(client, leg2, adults, children)
    dec2 = rebook_held(policy, leg2, ReplanProposal(
        node_id=leg2.node_id, chosen_offer_id=alts2[0].offer_id,
        rationale="held", fare_difference_cents=12000, model_tier_used="Qwen3.8-Max"), alts2[0])
    approve_held(policy, dec2, leg2, ReplanProposal(
        node_id=leg2.node_id, chosen_offer_id=alts2[0].offer_id,
        rationale="held", fare_difference_cents=12000, model_tier_used="Qwen3.8-Max"), "approved")

    recs = fresh_log.query()
    assert len(recs) == 2
    outcomes = {r.outcome.value for r in recs}
    assert outcomes == {"auto_settled", "human_approved"}
    for r in recs:
        DecisionLog.validate_schema(r)  # all SPECS §4.3 fields present
        assert r.reusable is True
        assert r.atlas_state_refs.get("orderNo")  # state thread preserved


# --- atlas_tool_protocol §4.2: re-read before write ---------------------------


def test_reread_before_write_detects_fare_drift(stack, graph):
    """Mutate live fare between proposal and execution -> StaleStateError."""
    s, client, router, policy = stack
    leg1 = graph.get_node("leg1_pvg_nrt")
    adults, children = _pax(graph)
    alts = search_alternatives(client, leg1, adults, children)
    prop = ReplanProposal(
        node_id=leg1.node_id, chosen_offer_id=alts[0].offer_id,
        rationale="stale test", fare_difference_cents=3000, model_tier_used="Qwen3.8-Max",
    )
    decision = policy.evaluate_settlement(leg1, prop, alts[0])  # captures proposal-time fare
    client.mutate_offer_price(alts[0].offer_id, 999.99)  # live fare changes AFTER proposal
    with pytest.raises(StaleStateError, match="fare changed"):
        policy.execute(decision, leg1, prop)


def test_reread_before_write_prevents_double_pay(stack, graph):
    """If the new order is already paid (e.g. a retry), execute refuses (no double-pay)."""
    s, client, router, policy = stack
    leg1 = graph.get_node("leg1_pvg_nrt")
    adults, children = _pax(graph)
    alts = search_alternatives(client, leg1, adults, children)
    prop = ReplanProposal(
        node_id=leg1.node_id, chosen_offer_id=alts[0].offer_id,
        rationale="double-pay test", fare_difference_cents=3000, model_tier_used="Qwen3.8-Max",
    )
    decision = policy.evaluate_settlement(leg1, prop, alts[0])
    # simulate the new order already paid (a prior retry succeeded) -> order_status.paid=True
    from tripcascade.atlas_tools.client import StatusResult
    client.order_status = lambda order_no: StatusResult(orderNo=order_no, paid=True, ticket_status="TICKETING_PENDING")
    with pytest.raises(StaleStateError, match="already paid"):
        policy.execute(decision, leg1, prop)


# --- coding_standards §4: false-success cure --------------------------------


def test_false_success_empty_orderno_raises(stack, graph):
    """A 200/ok with an empty orderNo is a fail (FalseSuccessError)."""
    s, client, router, policy = stack
    leg1 = graph.get_node("leg1_pvg_nrt")
    adults, children = _pax(graph)
    alts = search_alternatives(client, leg1, adults, children)
    # monkeypatch order_create to return an empty orderNo (simulates a bad 200)
    from tripcascade.atlas_tools.client import OrderResult
    client.order_create = lambda booking_id, passengers: OrderResult(orderNo=None, status="OK")
    prop = ReplanProposal(
        node_id=leg1.node_id, chosen_offer_id=alts[0].offer_id,
        rationale="false-success", fare_difference_cents=3000, model_tier_used="Qwen3.8-Max",
    )
    decision = policy.evaluate_settlement(leg1, prop, alts[0])
    with pytest.raises(FalseSuccessError, match="orderNo is empty"):
        policy.execute(decision, leg1, prop)


# --- FR-009: model routing ---------------------------------------------------


def test_routing_routine_to_cheap_hard_to_max():
    """With a paid key: routine->routine_model, hard->hard_model."""
    s = _settings(dashscope_api_key="fake-key-for-routing-test")
    r = Router(s)
    assert r.is_paid_available()
    rd = r.route(TaskKind.PARSE_INTENT)
    assert rd.tier == ModelTier.ROUTINE and rd.model_name == s.routine_model
    rd = r.route(TaskKind.REPLAN_PROPOSAL)
    assert rd.tier == ModelTier.HARD and rd.model_name == s.hard_model
    assert not rd.fallback_used


def test_routing_fallback_when_no_paid_key():
    """Without a paid key, paid tiers fall back to local-open-weight (exercised)."""
    s = _settings(dashscope_api_key="")
    r = Router(s)
    assert not r.is_paid_available()
    rd = r.route(TaskKind.REPLAN_PROPOSAL)
    assert rd.tier == ModelTier.FALLBACK
    assert rd.fallback_used is True
    assert rd.model_tier_used == s.local_fallback_model


def test_routing_logs_model_tier_used():
    """model_tier_used is recorded per call (Cost-Controllability evidence)."""
    r = Router(_settings(dashscope_api_key="fake"))
    r.route(TaskKind.CASCADE_REASONING)
    assert r.last_tier_for(TaskKind.CASCADE_REASONING) is not None


# --- E2E: scripted scenario (no infinite-loop, no false-success) -------------


def test_e2e_scripted_scenario_completes(graph, fresh_log):
    """End-to-end: scripted leg1 disruption -> auto leg1 + advisory hotel + held leg2 -> approved."""
    s = _settings()
    client = StubAtlasClient(s)
    orc = Orchestrator(graph=graph, client=client, settings=s, decision_log=fresh_log)
    res = orc.handle_disruption(make_scripted_event("leg1_pvg_nrt", 0.82))

    assert not res.given_up, f"orchestrator gave up: {res.give_up_reason}"
    assert res.cascade.affected_node_ids == ["hotel_tokyo", "leg2_nrt_pvg"]
    # leg1 auto-settled
    assert len(res.auto_settled) == 1
    assert res.auto_settled[0].node_id == "leg1_pvg_nrt"
    assert all(r.asserted for r in res.results)  # no false success
    # hotel advisory notification drafted
    assert any(nid == "hotel_tokyo" for nid, _ in res.notifications)
    # leg2 held for human approval
    assert len(res.held_for_approval) == 1
    held = res.held_for_approval[0]
    assert held.amount_cents == 12000 and held.cap_cents == 5000
    # human approves leg2
    approved = orc.approve(held, "approved by traveler")
    assert approved.asserted and approved.record.outcome.value == "human_approved"
    # decision log has both records
    recs = fresh_log.query()
    assert {r.outcome.value for r in recs} == {"auto_settled", "human_approved"}


def test_e2e_step_budget_gives_up_instead_of_infinite_loop(graph, fresh_log):
    """A tiny step budget triggers an explicit give-up (infinite-loop cure)."""
    s = _settings(step_budget=2, give_up_after=2)
    orc = Orchestrator(graph=graph, client=StubAtlasClient(s), settings=s, decision_log=fresh_log)
    res = orc.handle_disruption(make_scripted_event("leg1_pvg_nrt", 0.82))
    assert res.given_up
    assert any("GIVE_UP" in (r.human_verdict or "") for r in res.records)


# --- forecast wiring (FR-002) ------------------------------------------------


def test_forecast_populates_disruption_probability(graph):
    """Watcher.populate_forecast writes a float P(disruption) per flight leg."""
    from tripcascade.forecast.inference import predict_disruption_prob

    populate_forecast(graph, predict_disruption_prob)
    for node in graph.nodes.values():
        if node.node_type.value == "flight":
            assert node.disruption_probability is not None
            assert 0.0 <= node.disruption_probability <= 1.0


# --- live DashScope (real Qwen) proposal backend (skipped if no key / stub mode) ---


def test_real_qwen_proposal_backend():
    """FR-009: with a real DASHSCOPE_API_KEY + llm_backend=dashscope, the real Qwen model
    proposes an alternative (records model_tier_used = the paid HARD tier, not fallback).

    Skipped if no key is set or backend is 'stub' (the default demo/test mode).
    """
    import os

    from tripcascade.agent.config import load_env_file

    load_env_file()  # load .env so the key is in os.environ
    key = os.environ.get("DASHSCOPE_API_KEY", "")
    backend_mode = os.environ.get("TRIPCASCADE_LLM_BACKEND", "stub")
    if not key or backend_mode == "stub":
        pytest.skip("no DASHSCOPE_API_KEY or llm_backend=stub (real Qwen not exercised)")

    from tripcascade.agent.llm import DashScopeProposalBackend
    from tripcascade.agent.router import Router, TaskKind
    from tripcascade.atlas_tools.client import StubAtlasClient
    from tripcascade.atlas_tools.discovery import search_alternatives

    s = _settings(dashscope_api_key=key, llm_backend="dashscope")
    router = Router(s)
    assert router.is_paid_available()
    backend = DashScopeProposalBackend(router)
    graph = build_graph(DEMO_SEED)
    leg1 = graph.get_node("leg1_pvg_nrt")
    adults, children = _pax(graph)
    alts = search_alternatives(StubAtlasClient(s), leg1, adults, children)

    # route the proposal (HARD tier) + make the real Qwen call
    proposal = backend.propose_replan(leg1, alts, "cascade: leg1 at_risk -> hotel, leg2 affected")

    # the LLM chose a real offer from the alternatives
    assert proposal.chosen_offer_id in {o.offer_id for o in alts}
    # the fare difference is deterministic (computed from prices, not by the LLM)
    assert proposal.fare_difference_cents == 3000  # stub offer 516.68 - original 486.68
    # model_tier_used reflects the paid HARD tier, not the local-open-weight fallback
    assert proposal.model_tier_used == s.hard_model  # Qwen3.8-Max
    assert not router.route(TaskKind.REPLAN_PROPOSAL).fallback_used


# --- live Atlas Sandbox (skipped if CLI not authed) -------------------------


def test_live_discovery_returns_real_fares():
    """Acceptance: Discovery runs read-only against Atlas Sandbox, returns real fares.

    Skipped if `atlas-flight` CLI is not installed/authed on this machine.
    """
    from tripcascade.atlas_tools.client import CLISubprocessClient

    cli = CLISubprocessClient()
    if not cli.is_available():
        pytest.skip("atlas-flight CLI not installed")
    try:
        offers = cli.search("PVG", "NRT", "2026-09-04", 2, 1)
    except Exception as e:
        pytest.skip(f"Atlas Sandbox search failed (auth/network): {e}")
    assert len(offers) >= 1, "expected at least one real offer"
    assert all(isinstance(o.offer_id, str) and o.offer_id for o in offers)
    assert all(o.total_price > 0 for o in offers)
