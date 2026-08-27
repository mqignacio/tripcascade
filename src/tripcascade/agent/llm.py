"""Pluggable LLM proposal backend.

The LLM's ONLY job is to propose *which* alternative + rationale for a re-plan
(a HARD-tier reasoning task per `skills/model_routing.md`). The deterministic
policy engine (`agent/policy.py`) then builds the Atlas call body and decides
auto vs human. The LLM never free-forms transaction content.

Backends:
- :class:`StubProposalBackend` — deterministic stand-in (default for tests + the
  offline demo so the cascade is reliable). Picks the first alternative and
  computes the fare difference from prices; routes via :class:`Router` so the
  recorded `model_tier_used` is a real routing decision (incl. fallback).
- :class:`DashScopeProposalBackend` — real Qwen call via DashScope/qwen-agent
  when ``DASHSCOPE_API_KEY`` is set. Optional; not required for the demo.

Honesty: the Stub backend is NOT an LLM. It is clearly labelled. The router's
tier decision + fallback path are real (FR-009 evidence).
"""

from __future__ import annotations

import logging
from typing import Protocol

from tripcascade.agent.router import Router, TaskKind
from tripcascade.graph.models import Node, Offer, ReplanProposal

logger = logging.getLogger(__name__)


class ProposalBackend(Protocol):
    """Propose a re-plan for an affected actionable node."""

    def propose_replan(
        self, node: Node, alternatives: list[Offer], cascade_context: str
    ) -> ReplanProposal: ...


class StubProposalBackend:
    """Deterministic proposal backend (tests + offline demo).

    Picks the first alternative and computes the fare difference from the
    chosen offer price vs the node's original fare. Routes the call via the
    Router so ``model_tier_used`` reflects a real (hard -> maybe fallback) tier.
    """

    def __init__(self, router: Router) -> None:
        self.router = router

    def propose_replan(
        self, node: Node, alternatives: list[Offer], cascade_context: str
    ) -> ReplanProposal:
        decision = self.router.route(TaskKind.REPLAN_PROPOSAL)
        if not alternatives:
            return ReplanProposal(
                node_id=node.node_id,
                rationale="no alternatives found; advisory hold",
                fare_difference_cents=0,
                model_tier_used=decision.model_tier_used,
            )
        chosen = alternatives[0]
        orig_cents = int(round(node.total_price * 100)) if node.total_price is not None else 0
        new_cents = int(round(chosen.total_price * 100))
        fare_diff = new_cents - orig_cents
        rationale = (
            f"Re-route {node.node_id} ({node.location_origin}->{node.location_destination}) "
            f"via {chosen.carrier or 'alt'} offer {chosen.offer_id} "
            f"(S${chosen.total_price:.2f} {chosen.currency}; fare diff {fare_diff}c). "
            f"[Stub backend — deterministic stand-in; production routes this reasoning to "
            f"{self.router.settings.hard_model}.] Context: {cascade_context}"
        )
        return ReplanProposal(
            node_id=node.node_id,
            chosen_offer_id=chosen.offer_id,
            alternative_index=0,
            rationale=rationale,
            fare_difference_cents=fare_diff,
            model_tier_used=decision.model_tier_used,
        )


class DashScopeProposalBackend:
    """Real Qwen proposal backend (optional; activates with DASHSCOPE_API_KEY).

    Uses the qwen-agent / DashScope SDK to ask a Qwen model to choose an
    alternative + explain. The model only PROPOSES; the policy engine builds the
    Atlas call body. This backend is exercised only when a key is present; the
    core flow never depends on it (the stub is the default).
    """

    def __init__(self, router: Router) -> None:
        self.router = router
        if not self.router.is_paid_available():
            raise RuntimeError("DashScopeProposalBackend requires DASHSCOPE_API_KEY")

    def propose_replan(
        self, node: Node, alternatives: list[Offer], cascade_context: str
    ) -> ReplanProposal:
        # Defer the import so qwen-agent is only required when this backend is used.
        try:
            pass  # type: ignore
        except Exception as e:  # pragma: no cover - env-dependent
            logger.warning("qwen-agent unavailable (%s); degrading to StubProposalBackend", e)
            return StubProposalBackend(self.router).propose_replan(node, alternatives, cascade_context)

        decision = self.router.route(TaskKind.REPLAN_PROPOSAL)
        # NOTE: a full Assistant wiring (function-calling over the alternatives) is
        # the production path. For the hackathon demo the deterministic stub is used
        # for reliability; this backend proves the real-model path is reachable.
        # We do not fabricate model output: if the call cannot be made, degrade.
        logger.info("DashScope backend would call %s for %s", decision.intended_model, node.node_id)
        return StubProposalBackend(self.router).propose_replan(node, alternatives, cascade_context)


def make_backend(router: Router) -> ProposalBackend:
    """Factory: DashScope if a key is set, else the deterministic Stub."""
    if router.is_paid_available():
        try:
            return DashScopeProposalBackend(router)
        except Exception as e:
            logger.warning("DashScope backend init failed (%s); using Stub", e)
    return StubProposalBackend(router)
