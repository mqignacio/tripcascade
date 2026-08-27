"""Cascade propagation: given an at-risk node, compute the affected downstream set.

Implements SPECS S-004 / FR-004. Walks the DAG via `depends_on` edges (BFS) and
marks every reachable downstream node as `affected`, carrying per-edge slack.

Demo expectation (assets/demo_itinerary.json):
    at-risk = leg1_pvg_nrt  ->  affected = {hotel_tokyo, leg2_nrt_pvg}
"""

from __future__ import annotations

import logging
from collections import deque

from tripcascade.graph.models import CascadeResult, ItineraryGraph, NodeStatus

logger = logging.getLogger(__name__)


def compute_cascade(graph: ItineraryGraph, at_risk_node_id: str) -> CascadeResult:
    """BFS downstream from `at_risk_node_id` over depends_on edges.

    Pure function: does not mutate the graph. Returns the affected node set +
    the edges traversed + per-edge slack (already computed by the builder).
    The orchestrator applies statuses via :func:`apply_cascade`.
    """
    if at_risk_node_id not in graph.nodes:
        raise KeyError(f"at-risk node not in graph: {at_risk_node_id}")

    affected: list[str] = []
    edges_traversed: list[str] = []
    slack: dict[str, int | None] = {}
    seen: set[str] = set()
    queue: deque[str] = deque([at_risk_node_id])

    while queue:
        current = queue.popleft()
        for downstream_id in graph.downstream(current):
            if downstream_id in seen:
                continue
            seen.add(downstream_id)
            affected.append(downstream_id)
            # record the edge that connected us here + its slack
            for edge in graph.edges:
                if edge.from_node == current and edge.to_node == downstream_id:
                    edges_traversed.append(edge.edge_id)
                    slack[downstream_id] = edge.slack_minutes
                    break
            queue.append(downstream_id)

    logger.info(
        "cascade from %s -> affected=%s (edges=%s)", at_risk_node_id, affected, edges_traversed
    )
    return CascadeResult(
        at_risk_node_id=at_risk_node_id,
        affected_node_ids=affected,
        edges_traversed=edges_traversed,
        slack_minutes=slack,
    )


def apply_cascade(graph: ItineraryGraph, result: CascadeResult) -> ItineraryGraph:
    """Mutate statuses: the at-risk node -> AT_RISK, affected nodes -> AFFECTED.

    Returns the same graph (mutated) for chaining. Call after compute_cascade.
    """
    at_risk = graph.get_node(result.at_risk_node_id)
    at_risk.status = NodeStatus.AT_RISK
    at_risk.disruption_probability = at_risk.disruption_probability  # set by watcher
    for nid in result.affected_node_ids:
        graph.get_node(nid).status = NodeStatus.AFFECTED
    return graph
