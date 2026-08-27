"""Discovery capability: read-only, ungated Atlas search + offer verify.

Per `skills/atlas_tool_protocol.md` §1/§4.1: Discovery is read-only and safe to
hammer in Sandbox (cache results). No policy gate, no human checkpoint.
The orchestrator calls these to find re-booking alternatives for affected nodes.
"""

from __future__ import annotations

import logging

from tripcascade.atlas_tools.client import AtlasClient, CachedDiscoveryClient, VerifyResult
from tripcascade.graph.models import Node, Offer

logger = logging.getLogger(__name__)


def search_alternatives(
    client: AtlasClient, node: Node, adults: int, children: int, depart: str | None = None
) -> list[Offer]:
    """Read-only fare/route search for an actionable (flight) node.

    Args:
        client: an AtlasClient (wrap with CachedDiscoveryClient to cache).
        node: the at-risk/affected flight node (origin/destination/date).
        adults/children: pax counts.
        depart: override depart date (YYYY-MM-DD); defaults to the node's scheduled start.
    """
    depart = depart or node.scheduled_start.strftime("%Y-%m-%d")
    origin = node.location_origin
    destination = node.location_destination
    if not origin or not destination:
        raise ValueError(f"node {node.node_id} has no origin/destination for search")
    logger.info("Discovery search %s->%s %s (adults=%d children=%d)", origin, destination, depart, adults, children)
    return client.search(origin, destination, depart, adults, children)


def verify_offer(client: AtlasClient, offer_id: str) -> VerifyResult:
    """Read-only offer verify / price confirm (re-read before write helper)."""
    return client.verify(offer_id)


def with_cache(client: AtlasClient) -> CachedDiscoveryClient:
    """Wrap a client so search() results are cached by route/date/pax."""
    return CachedDiscoveryClient(client)
