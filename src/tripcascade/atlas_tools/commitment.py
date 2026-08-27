"""Commitment + Money capability: order create / order pay — POLICY-GATED.

Every Commitment/Money action routes through the deterministic policy engine
(`agent/policy.py`, FR-006): auto-execute <= cap with an audit-log record; hold
and surface to the UI for human approval > cap. The policy engine builds the
Atlas call body from structured data (offer_id/orderNo/amount_cents); the LLM
never free-forms transaction content (`skills/human_checkpoint_rules.md` §3.1).
"""

from __future__ import annotations

import logging

from tripcascade.agent.policy import AtlasResult, PolicyEngine, StaleStateError
from tripcascade.graph.models import (
    DecisionStatus,
    Node,
    Offer,
    ReplanProposal,
    SettlementDecision,
)

logger = logging.getLogger(__name__)


def evaluate_rebook(
    policy: PolicyEngine, node: Node, proposal: ReplanProposal, chosen_offer: Offer | None
) -> SettlementDecision:
    """Policy-gated evaluate: returns the decision (auto / held / advisory).

    The orchestrator calls this after the LLM proposes an alternative. The
    decision's `verdict` property is the UI-facing string.
    """
    return policy.evaluate_settlement(node, proposal, chosen_offer)


def rebook_auto(
    policy: PolicyEngine, node: Node, proposal: ReplanProposal, chosen_offer: Offer | None
) -> AtlasResult:
    """Commitment+Money (auto path): execute an at-or-below-cap re-book.

    Raises StaleStateError if live state changed between proposal and execution
    (the re-read-before-write cure). Raises FalseSuccessError on an empty post-state.
    """
    decision = policy.evaluate_settlement(node, proposal, chosen_offer)
    if decision.advisory:
        raise ValueError(f"node {node.node_id} is advisory; use draft_notification, not rebook")
    if decision.held:
        raise ValueError(
            f"node {node.node_id} fare diff {decision.amount_cents}c > cap {decision.cap_cents}c; "
            "use rebook_held -> UI approve, not rebook_auto"
        )
    return policy.execute(decision, node, proposal)


def rebook_held(
    policy: PolicyEngine, node: Node, proposal: ReplanProposal, chosen_offer: Offer | None
) -> SettlementDecision:
    """Commitment+Money (human path): return a HELD decision for UI approval.

    The UI's Approve control calls :func:`approve_held` to execute.
    """
    decision = policy.evaluate_settlement(node, proposal, chosen_offer)
    if not decision.held:
        raise ValueError(
            f"node {node.node_id} fare diff {decision.amount_cents}c <= cap {decision.cap_cents}c; "
            "use rebook_auto, not rebook_held"
        )
    decision.status = DecisionStatus.HELD
    return decision


def approve_held(
    policy: PolicyEngine,
    decision: SettlementDecision,
    node: Node,
    proposal: ReplanProposal,
    human_verdict: str,
) -> AtlasResult:
    """Execute an above-cap re-book after explicit human approval (UI Approve)."""
    return policy.execute_approved(decision, node, proposal, human_verdict)


def reject_held(
    policy: PolicyEngine, decision: SettlementDecision, human_verdict: str
):
    """Record a human rejection of an above-cap re-book (UI Reject). No Atlas write."""
    return policy.reject(decision, human_verdict)
