"""Aftercare capability: order status / incident query + gated change/cancel/refund.

Read-only queries (order status, incident poll) are ungated. Aftercare actions
that result in a re-book (change/cancel/refund) route through the FR-006 policy
engine. CLI gaps (doc/atlas_surface.md §1.3): no change/cancel/refund/void CLI
commands -> these are REST/ATRIP-portal only; the demo's auto-settled re-book
uses a new search->verify->order->pay cycle (not a "change" endpoint).
"""

from __future__ import annotations

import logging

from tripcascade.agent.policy import AtlasResult, PolicyEngine
from tripcascade.atlas_tools.client import RestClient, StatusResult
from tripcascade.graph.models import Node, Offer, ReplanProposal

logger = logging.getLogger(__name__)


def get_order_status(client, order_no: str) -> StatusResult:
    """Aftercare (read): order/ticket status query. Asserts post-state upstream."""
    return client.order_status(order_no)


def query_incidents(rest_client: RestClient, page_size: int = 5) -> list[dict]:
    """Aftercare (read): Atlas incident poll (webhook best-effort; doc/atlas_surface.md §3).

    Event types of interest: abnormal.cancelled, order.schedulechange,
    email.schedulechange. Delivery is best-effort -> scheduled poll stays P0.
    """
    return rest_client.query_incidents(page_size=page_size)


def refund(
    policy: PolicyEngine, node: Node, proposal: ReplanProposal, chosen_offer: Offer | None
) -> AtlasResult:
    """Aftercare (gated): refund routes through the policy engine (auto <= cap / human > cap).

    A price *decrease* (refund) still routes through Aftercare policy-gating and
    is recorded (skills/human_checkpoint_rules.md §1). The same cap rule applies.
    """
    decision = policy.evaluate_settlement(node, proposal, chosen_offer)
    # refund = action REFUND; fare_difference_cents may be negative (a decrease)
    from tripcascade.graph.models import ActionType

    decision.action = ActionType.REFUND
    if decision.advisory:
        raise ValueError(f"node {node.node_id} is advisory; no Atlas refund")
    if decision.held:
        return decision  # caller surfaces to UI for approval
    return policy.execute(decision, node, proposal)
