"""Build an ItineraryGraph from a seed JSON file + compute edge slack.

Seed: `assets/demo_itinerary.json` (task-02 Sandbox rehearsal). Each edge's
`slack_minutes` is computed here (the seed leaves it null per its notes).
Slack = signed minutes from the upstream node's end to the downstream node's
start (timezone-aware). Negative slack = the downstream commitment starts
before the upstream arrives (late-arrival-tolerant, cancellation-vulnerable).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from tripcascade.graph.models import Edge, ItineraryGraph, Node

logger = logging.getLogger(__name__)

# Locate the demo itinerary seed. Search upward from this file for an `assets/`
# directory so it works both in the dev repo (src/tripcascade/graph/builder.py
# -> <repo>/assets/) AND on Alibaba Cloud FC (code at /code/tripcascade/...
# -> /code/assets/).
def _find_seed() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / "assets" / "demo_itinerary.json"
        if candidate.exists():
            return candidate
    # Fallback: the dev-repo-relative path (parents[3] on a normal checkout).
    return here.parents[3] / "assets" / "demo_itinerary.json"

DEFAULT_SEED = _find_seed()


def compute_edge_slack(edge: Edge, graph: ItineraryGraph) -> int | None:
    """Signed minutes from upstream end -> downstream start (None if unknown)."""
    try:
        upstream = graph.get_node(edge.from_node)
        downstream = graph.get_node(edge.to_node)
        delta = downstream.scheduled_start - upstream.scheduled_end
        return int(round(delta.total_seconds() / 60))
    except (KeyError, TypeError) as e:
        logger.debug("slack undefined for edge %s: %s", edge.edge_id, e)
        return None


def build_graph(seed_path: Path | str | None = None) -> ItineraryGraph:
    """Load a seed JSON itinerary into an ItineraryGraph with computed slack.

    Args:
        seed_path: path to an itinerary JSON (defaults to assets/demo_itinerary.json).

    Returns:
        ItineraryGraph with nodes indexed by node_id and edge slack_minutes set.
    """
    path = Path(seed_path) if seed_path else DEFAULT_SEED
    logger.info("Building itinerary graph from %s", path)
    data = json.loads(path.read_text())
    graph = ItineraryGraph(**data)

    for edge in graph.edges:
        if edge.slack_minutes is None:
            edge.slack_minutes = compute_edge_slack(edge, graph)

    _validate_graph(graph)
    return graph


def _validate_graph(graph: ItineraryGraph) -> None:
    """Assert SPECS S-001 invariants: actionable flags + flight offer_id retained."""
    for node in graph.nodes.values():
        if node.actionable and node.atlas_entity_ref and node.atlas_entity_ref.offer_id:
            # actionable flight nodes must retain their offer_id (state thread)
            assert node.atlas_entity_ref.offer_id, (
                f"actionable node {node.node_id} missing offer_id"
            )
        # actionable flag must match node_type per doc/atlas_surface.md §4
        expected = node.node_type.value == "flight"
        assert node.actionable == expected, (
            f"node {node.node_id} actionable={node.actionable} but type={node.node_type}"
        )


def load_demo_itinerary() -> ItineraryGraph:
    """Convenience: load the canonical demo seed (assets/demo_itinerary.json)."""
    return build_graph(DEFAULT_SEED)


def actionable_nodes(graph: ItineraryGraph) -> list[Node]:
    """Return only the actionable (flight) nodes — Atlas-re-bookable."""
    return [n for n in graph.nodes.values() if n.actionable]


def advisory_nodes(graph: ItineraryGraph) -> list[Node]:
    """Return advisory nodes (hotel/activity/transfer) — notification-only."""
    return [n for n in graph.nodes.values() if not n.actionable]
