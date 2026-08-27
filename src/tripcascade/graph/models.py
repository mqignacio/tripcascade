"""Pydantic v2 data models for the TripCascade dependency graph + decision records.

Implements `doc/SPECS.md` §4 (Data Model) and the event/proposal/decision
schemas from §5 (Interfaces). Every field traces to a SPECS row; flight-specific
fields (carrier, duration_minutes, ...) come from `assets/demo_itinerary.json`
(the task-02 rehearsal seed) and are needed by the forecast
(`src/tripcascade/forecast/inference.py`).

Node classification (`actionable`) is **evidence-based** (`doc/atlas_surface.md`
§4): flight = True; hotel/activity/transfer = False (advisory-only).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Enums (SPECS §4.1 / §4.3)
# ---------------------------------------------------------------------------


class NodeType(str, Enum):
    FLIGHT = "flight"
    HOTEL = "hotel"
    ACTIVITY = "activity"
    TRANSFER = "transfer"


class NodeStatus(str, Enum):
    PLANNED = "planned"
    BOOKED = "booked"  # used by the rehearsal seed (task 02)
    AT_RISK = "at_risk"
    AFFECTED = "affected"
    RE_PLANNED = "re_planned"
    SETTLED = "settled"
    HELD_FOR_APPROVAL = "held_for_approval"
    COMPLETED = "completed"


class EdgeType(str, Enum):
    DEPENDS_ON = "depends_on"
    TEMPORAL = "temporal"
    BOOKING = "booking"


class ActionType(str, Enum):
    RE_BOOK = "re_book"
    CHANGE = "change"
    CANCEL = "cancel"
    REFUND = "refund"
    NOTIFY = "notify"  # advisory nodes only


class Outcome(str, Enum):
    AUTO_SETTLED = "auto_settled"
    HUMAN_APPROVED = "human_approved"
    HUMAN_REJECTED = "human_rejected"


class DecisionStatus(str, Enum):
    """Lifecycle of a settlement decision (policy-engine internal)."""

    PROPOSED = "proposed"
    AUTO_EXECUTED = "auto_executed"
    HELD = "held"  # waiting on human Approve/Reject
    EXECUTED = "executed"  # human-approved then executed
    REJECTED = "rejected"
    ADVISORY = "advisory"  # no Atlas write (hotel/activity/transfer)
    GIVEN_UP = "given_up"  # step budget exhausted


# ---------------------------------------------------------------------------
# Atlas state refs + offer alternatives
# ---------------------------------------------------------------------------


class AtlasEntityRef(BaseModel):
    """The ATRIP state thread preserved on actionable flight nodes.

    Thread (skills/atlas_tool_protocol.md §3):
    offer_id -> booking_id -> orderNo -> payment_confirmation_id -> ticketNos.
    """

    model_config = ConfigDict(extra="allow")

    offer_id: str | None = None
    booking_id: str | None = None
    orderNo: str | None = None
    payment_confirmation_id: str | None = None


class Offer(BaseModel):
    """A Discovery search result (atlas-flight search --json, normalized).

    Carries the minimal fields the agent/policy engine need: the state-thread
    `offer_id`, the fare (for fare-difference logic), and route/segment info.
    """

    model_config = ConfigDict(extra="allow")

    offer_id: str
    total_price: float
    currency: str = "USD"
    bookable: bool = True
    carrier: str | None = None
    segments: list[dict] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Graph node + edge
# ---------------------------------------------------------------------------


class Node(BaseModel):
    """A leg/commitment in the trip DAG (SPECS §4.1).

    `actionable` is evidence-backed (doc/atlas_surface.md §4): flight=True,
    hotel/activity/transfer=False. Advisory nodes get impact analysis + a
    drafted notification; never a fake Atlas booking.
    """

    model_config = ConfigDict(extra="allow")

    node_id: str
    node_type: NodeType
    actionable: bool
    atlas_entity_ref: AtlasEntityRef | None = None
    scheduled_start: datetime
    scheduled_end: datetime
    location_origin: str | None = None
    location_destination: str | None = None
    booking_constraints: dict = Field(default_factory=dict)
    disruption_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    status: NodeStatus = NodeStatus.PLANNED
    depends_on: list[str] = Field(default_factory=list)
    temporal_constraint: dict | None = None
    passengers: list[dict] = Field(default_factory=list)
    fare_difference_cents: int | None = None
    settlement: dict | None = None
    evidence_source: str = ""

    # Flight-specific (demo seed + forecast feature availability, atlas_surface §1.2)
    carrier: str | None = None
    flight_number: str | None = None
    cabin_class: int | None = None
    duration_minutes: int | None = None
    total_price: float | None = None
    currency: str | None = None
    payment_status: str | None = None
    ticket_status: str | None = None
    ticket_numbers: list[str] = Field(default_factory=list)

    def to_forecast_leg(self) -> dict[str, Any]:
        """Map this node to the forecast inference leg dict.

        Keys expected by `tripcascade.forecast.inference.predict_disruption_prob`:
        carrier, origin, destination, scheduled_dep_ts, duration_minutes.
        """
        return {
            "carrier": self.carrier,
            "origin": self.location_origin,
            "destination": self.location_destination,
            "scheduled_dep_ts": self.scheduled_start.isoformat(),
            "duration_minutes": self.duration_minutes,
        }


class Edge(BaseModel):
    """A dependency edge in the trip DAG (SPECS §4.2)."""

    model_config = ConfigDict(extra="allow")

    edge_id: str
    from_node: str  # upstream
    to_node: str  # downstream (the dependent)
    edge_type: EdgeType = EdgeType.DEPENDS_ON
    constraint: dict = Field(default_factory=dict)
    slack_minutes: int | None = None
    note: str | None = None


# ---------------------------------------------------------------------------
# Itinerary graph
# ---------------------------------------------------------------------------


class ItineraryGraph(BaseModel):
    """The trip as a DAG of nodes connected by dependency edges (SPECS §4).

    Accepts `nodes` as a list (from the demo seed JSON) and indexes by node_id.
    """

    model_config = ConfigDict(extra="allow")

    itinerary_id: str
    trip: str | None = None
    product: str | None = None
    settlement_cap_cents: int = 5000
    passengers: list[dict] = Field(default_factory=list)
    nodes: dict[str, Node] = Field(default_factory=dict)
    edges: list[Edge] = Field(default_factory=list)
    demo_scenario_notes: dict | None = None

    @field_validator("nodes", mode="before")
    @classmethod
    def _coerce_nodes(cls, v: Any) -> Any:
        """Accept a list of node dicts (as in assets/demo_itinerary.json)."""
        if isinstance(v, list):
            out: dict[str, Node] = {}
            for item in v:
                node = item if isinstance(item, Node) else Node(**item)
                out[node.node_id] = node
            return out
        return v

    def get_node(self, node_id: str) -> Node:
        if node_id not in self.nodes:
            raise KeyError(f"node not found: {node_id}")
        return self.nodes[node_id]

    def downstream(self, node_id: str) -> list[str]:
        """Direct dependents of `node_id` (nodes whose depends_on includes it)."""
        return [n.node_id for n in self.nodes.values() if node_id in n.depends_on]

    def upstream(self, node_id: str) -> list[str]:
        return list(self.get_node(node_id).depends_on)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)


# ---------------------------------------------------------------------------
# Watcher event + LLM proposal + policy decision + decision record
# ---------------------------------------------------------------------------


class DisruptionEvent(BaseModel):
    """`disruption_likely` event from the Watcher (SPECS §5.4, S-003)."""

    event_type: str = "disruption_likely"
    node_id: str
    p_disruption: float = Field(ge=0.0, le=1.0)
    threshold: float
    ts: datetime


class ReplanProposal(BaseModel):
    """LLM proposal: WHICH alternative + rationale (never the Atlas call body).

    The LLM proposes; the deterministic policy engine builds the exact Atlas
    call from offer_id/orderNo/amount_cents (skills/human_checkpoint_rules.md §3).
    """

    node_id: str
    chosen_offer_id: str | None = None
    alternative_index: int | None = None
    rationale: str = ""
    fare_difference_cents: int = 0
    model_tier_used: str = "stub"


class SettlementDecision(BaseModel):
    """Deterministic policy-engine output (SPECS §5.3, S-006).

    `auto_settle` True + `held` False -> engine executes immediately (<= cap).
    `held` True -> surfaced to UI for human Approve/Reject (> cap).
    `advisory` True -> no Atlas write (hotel/activity/transfer; draft notify).
    """

    decision_id: str
    node_id: str
    action: ActionType
    amount_cents: int = 0
    cap_cents: int = 5000
    auto_settle: bool = False
    held: bool = False
    advisory: bool = False
    reasoning_trace: str = ""
    model_tier_used: str = "stub"
    chosen_offer_id: str | None = None
    atlas_state_refs: dict = Field(default_factory=dict)
    status: DecisionStatus = DecisionStatus.PROPOSED
    original_fare_cents: int | None = None
    new_fare_cents: int | None = None

    @property
    def verdict(self) -> str:
        if self.advisory:
            return "advisory — draft notification, no Atlas write"
        if self.auto_settle:
            return f"auto-settled under policy — S${self.amount_cents / 100:.0f} ≤ S${self.cap_cents / 100:.0f} cap, logged"
        if self.held:
            return f"approval required — S${self.amount_cents / 100:.0f} > S${self.cap_cents / 100:.0f} cap"
        return self.status.value


class DecisionRecord(BaseModel):
    """A structured, reusable decision-learning record (SPECS §4.3, FR-007).

    Written for every auto-settlement and every above-cap human verdict.
    `reusable=True` so the corpus can train a future threshold (the moat).
    """

    record_id: str
    timestamp: str  # ISO8601
    node_id: str
    action: ActionType
    amount_cents: int = 0
    cap_cents: int = 5000
    outcome: Outcome
    human_verdict: str | None = None
    reasoning_trace: str = ""
    model_tier_used: str = "stub"
    atlas_state_refs: dict = Field(default_factory=dict)
    reusable: bool = True


class CascadeResult(BaseModel):
    """Output of cascade propagation (SPECS S-004): affected nodes + per-edge slack."""

    at_risk_node_id: str
    affected_node_ids: list[str] = Field(default_factory=list)
    edges_traversed: list[str] = Field(default_factory=list)
    slack_minutes: dict[str, int | None] = Field(default_factory=dict)

    @property
    def affected_count(self) -> int:
        return len(self.affected_node_ids)
