"""The TripCascade agent orchestrator.

Given a `disruption_likely` event on a leg, the orchestrator:
  (a) loads the dependency graph (already in hand),
  (b) computes the cascade (downstream affected nodes),
  (c) for each affected ACTIONABLE node: Discovery search -> LLM proposal
      (hard tier) -> policy.evaluate -> auto-execute (<= cap) or hold (> cap),
      asserting the real post-state after each write,
  (d) for each affected ADVISORY node: draft a notification (no Atlas call),
  (e) respects a step budget with an explicit give-up (cure for infinite loop),
  (f) writes a decision-learning record for every settlement + every give-up.

This is a deterministic control-flow loop. The LLM only PROPOSES (which
alternative + rationale); the policy engine builds the Atlas call body and
decides auto vs human (skills/human_checkpoint_rules.md §3, doc/SPECS.md §7).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from tripcascade.agent.config import Settings, get_settings
from tripcascade.agent.decision_log import DecisionLog
from tripcascade.agent.llm import ProposalBackend, make_backend
from tripcascade.agent.policy import AtlasResult, PolicyEngine
from tripcascade.agent.router import Router, TaskKind
from tripcascade.atlas_tools.client import AtlasClient, StubAtlasClient
from tripcascade.atlas_tools.discovery import search_alternatives
from tripcascade.graph.cascade import apply_cascade, compute_cascade
from tripcascade.graph.models import (
    CascadeResult,
    DecisionRecord,
    DecisionStatus,
    DisruptionEvent,
    ItineraryGraph,
    SettlementDecision,
)

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorResult:
    """Full output of handling one disruption event."""

    event: DisruptionEvent
    cascade: CascadeResult | None = None
    decisions: list[SettlementDecision] = field(default_factory=list)
    results: list[AtlasResult] = field(default_factory=list)
    notifications: list[tuple[str, str]] = field(default_factory=list)  # (node_id, text)
    records: list[DecisionRecord] = field(default_factory=list)
    given_up: bool = False
    give_up_reason: str = ""
    steps_taken: int = 0

    @property
    def auto_settled(self) -> list[SettlementDecision]:
        return [d for d in self.decisions if d.status == DecisionStatus.AUTO_EXECUTED]

    @property
    def held_for_approval(self) -> list[SettlementDecision]:
        return [d for d in self.decisions if d.status == DecisionStatus.HELD]


class Orchestrator:
    """The agent loop. Deterministic control flow + LLM proposal + policy settlement."""

    def __init__(
        self,
        graph: ItineraryGraph,
        client: AtlasClient | None = None,
        policy: PolicyEngine | None = None,
        router: Router | None = None,
        backend: ProposalBackend | None = None,
        settings: Settings | None = None,
        decision_log: DecisionLog | None = None,
    ) -> None:
        self.graph = graph
        self.settings = settings or get_settings()
        self.client = client or StubAtlasClient(self.settings)
        self.router = router or Router(self.settings)
        self.log = decision_log or DecisionLog()
        self.policy = policy or PolicyEngine(self.settings, self.client, self.log)
        self.backend = backend or make_backend(self.router)
        self._steps = 0

    def _tick(self) -> bool:
        """Increment the step counter; return False if the budget is exhausted."""
        self._steps += 1
        if self._steps > self.settings.step_budget:
            return False
        return True

    def handle_disruption(self, event: DisruptionEvent) -> OrchestratorResult:
        """Run the full cascade + re-plan + settlement for one disruption event."""
        result = OrchestratorResult(event=event)
        self._steps = 0

        # (a) mark the at-risk node (its disruption_probability is set by the watcher)
        at_risk = self.graph.get_node(event.node_id)
        at_risk.disruption_probability = event.p_disruption

        # (b) compute the cascade (S-004)
        if not self._tick():
            return self._give_up(result, "step budget exhausted before cascade")
        cascade = compute_cascade(self.graph, event.node_id)
        apply_cascade(self.graph, cascade)
        result.cascade = cascade
        logger.info("cascade from %s -> affected=%s", event.node_id, cascade.affected_node_ids)

        # pax counts for Discovery search
        pax = self.graph.passengers
        adults = sum(1 for p in pax if p.get("type") == "adult")
        children = sum(1 for p in pax if p.get("type") == "child")

        # (c)+(d) walk the at-risk node FIRST (re-plan the disrupted leg itself),
        # then the downstream affected nodes in cascade (BFS) order.
        process_order = [event.node_id, *cascade.affected_node_ids]
        for nid in process_order:
            if not self._tick():
                return self._give_up(result, "step budget exhausted during re-plan")
            node = self.graph.get_node(nid)
            cascade_context = (
                f"at-risk={event.node_id} (P={event.p_disruption:.2f}); "
                f"affected={nid}; slack={cascade.slack_minutes.get(nid)}min"
            )

            if not node.actionable:
                # (d) ADVISORY node: impact analysis + drafted notification, NO Atlas call
                impact = f"{node.node_type.value} {nid} affected by upstream disruption; "
                if node.node_type.value == "hotel":
                    impact += "non-refundable first night at risk if arrival is missed."
                notif = self.policy.draft_notification(node, impact)
                result.notifications.append((nid, notif))
                # record an advisory decision (no money, no Atlas write)
                from tripcascade.graph.models import ActionType, Outcome

                adv_dec = SettlementDecision(
                    decision_id=f"dec_{nid}_advisory",
                    node_id=nid,
                    action=ActionType.NOTIFY,
                    advisory=True,
                    status=DecisionStatus.ADVISORY,
                    reasoning_trace=impact,
                    model_tier_used=self.router.route(TaskKind.DRAFT_NOTIFICATION).model_tier_used,
                )
                result.decisions.append(adv_dec)
                continue
            # (c) ACTIONABLE node: Discovery -> propose -> policy
            if not self._tick():
                return self._give_up(result, "step budget exhausted before discovery")
            alternatives = search_alternatives(self.client, node, adults, children)
            if not self._tick():
                return self._give_up(result, "step budget exhausted before proposal")
            proposal = self.backend.propose_replan(node, alternatives, cascade_context)
            chosen = alternatives[0] if alternatives else None
            if not self._tick():
                return self._give_up(result, "step budget exhausted before policy evaluate")
            decision = self.policy.evaluate_settlement(node, proposal, chosen)
            result.decisions.append(decision)

            if decision.advisory:  # defensive (actionable should not be advisory)
                result.notifications.append(
                    (nid, self.policy.draft_notification(node, "advisory fallback"))
                )
            elif decision.auto_settle:
                if not self._tick():
                    return self._give_up(result, "step budget exhausted before execute")
                atlas_res = self.policy.execute(decision, node, proposal)
                result.results.append(atlas_res)
                if atlas_res.record:
                    result.records.append(atlas_res.record)
            elif decision.held:
                # hold for human approval (UI Approve/Reject). For an end-to-end
                # scripted run, the caller approves via approve_held() afterwards.
                decision.status = DecisionStatus.HELD
                logger.info("held for approval: %s (%s)", nid, decision.verdict)

        result.steps_taken = self._steps
        return result

    def approve(self, decision: SettlementDecision, human_verdict: str) -> AtlasResult:
        """Human-approval path for a held decision (UI Approve)."""
        node = self.graph.get_node(decision.node_id)
        # re-derive the proposal context: re-search + re-propose (re-read before write)
        pax = self.graph.passengers
        adults = sum(1 for p in pax if p.get("type") == "adult")
        children = sum(1 for p in pax if p.get("type") == "child")
        alternatives = search_alternatives(self.client, node, adults, children)
        proposal = self.backend.propose_replan(node, alternatives, "human approval path")
        chosen = alternatives[0] if alternatives else None
        # re-evaluate (re-read) so the decision reflects current live state
        decision = self.policy.evaluate_settlement(node, proposal, chosen)
        res = self.policy.execute_approved(decision, node, proposal, human_verdict)
        return res

    def _give_up(self, result: OrchestratorResult, reason: str) -> OrchestratorResult:
        """Explicit give-up (cure for infinite loop): record + stop."""
        result.given_up = True
        result.give_up_reason = reason
        result.steps_taken = self._steps
        logger.error("GIVE UP after %d steps: %s", self._steps, reason)
        from tripcascade.graph.models import ActionType, Outcome

        rec = DecisionRecord(
            record_id=DecisionLog.new_record_id(),
            timestamp=DecisionLog.now_iso(),
            node_id=result.event.node_id,
            action=ActionType.NOTIFY,
            amount_cents=0,
            cap_cents=self.settings.settlement_cap_cents,
            outcome=Outcome.HUMAN_REJECTED,  # closest: not auto-settled; needs human
            human_verdict=f"GIVE_UP: {reason}",
            reasoning_trace="step budget exhausted — orchestrator stopped to avoid infinite loop",
            model_tier_used="deterministic",
            atlas_state_refs={},
            reusable=True,
        )
        self.log.append(rec)
        result.records.append(rec)
        return result
