"""Atlas tool-layer substrate: hybrid CLI + REST + deterministic Stub.

Implements `doc/atlas_surface.md` §6 (HYBRID substrate) and the interface contract
in `doc/SPECS.md` §5.1. Three backends behind one :class:`AtlasClient` protocol:

- :class:`StubAtlasClient` — deterministic, in-memory. Used for tests + the offline
  demo (reliable; no Sandbox rate-limit flakiness). Holds mutable live state so the
  "re-read before write" guard can be exercised.
- :class:`CLISubprocessClient` — shells out to `atlas-flight` (OAuth JWT in the OS
  secure store; the CLI handles auth). Used for the live Discovery test (real
  fares/routes) and optionally live booking.
- :class:`RestClient` — `x-atlas-client-id`/`x-atlas-client-secret` from `.env`
  for the incident/webhook surface (verified 2026-08-27 in doc/atlas_surface.md §2.4).

State thread (skills/atlas_tool_protocol.md §3):
offer_id -> booking_id (verify) -> orderNo (order) -> confirmation_id (pay)
-> ticketNos (order status).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from tripcascade.agent.config import Settings, get_settings
from tripcascade.graph.models import Offer

logger = logging.getLogger(__name__)

ATLAS_CLI_BIN = "atlas-flight"


# ---------------------------------------------------------------------------
# Result types (substrate-agnostic)
# ---------------------------------------------------------------------------


@dataclass
class VerifyResult:
    """`offer verify` / `booking confirm-price` outcome (Commitment, read)."""

    offer_id: str
    booking_id: str | None = None
    total_price: float | None = None
    currency: str = "USD"
    price_changed: bool = False
    raw: dict = field(default_factory=dict)


@dataclass
class OrderResult:
    """`order create` outcome (Commitment)."""

    orderNo: str | None = None
    payment_confirmation_id: str | None = None
    status: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class PayResult:
    """`order pay` outcome (Money)."""

    success: bool = False
    payment_confirmation_id: str | None = None
    ticket_status: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class StatusResult:
    """`order status` outcome (Aftercare — ticket query)."""

    orderNo: str
    ticket_status: str = ""
    ticket_numbers: list[str] = field(default_factory=list)
    paid: bool = False
    raw: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Client protocol
# ---------------------------------------------------------------------------


class AtlasClient(Protocol):
    """Substrate-agnostic Atlas client. Capability wrappers (discovery/
    commitment/aftercare) call these; writes route through the policy engine."""

    def search(
        self, origin: str, destination: str, depart: str, adults: int, children: int
    ) -> list[Offer]: ...

    def verify(self, offer_id: str) -> VerifyResult: ...

    def order_create(self, booking_id: str, passengers: list[dict]) -> OrderResult: ...

    def order_pay(self, confirmation_id: str) -> PayResult: ...

    def order_status(self, order_no: str) -> StatusResult: ...

    def query_incidents(self, page_size: int = 5) -> list[dict]: ...


# ---------------------------------------------------------------------------
# Stub backend (deterministic; tests + offline demo)
# ---------------------------------------------------------------------------


class StubAtlasClient:
    """Deterministic in-memory Atlas client.

    Returns scripted offers keyed by (origin,destination) so the demo cascade
    produces the SPECS fare differences (leg1 +S$30 auto; leg2 +S$120 human).
    Live state (`_offers` prices, `_orders` paid-flag) is mutable so the policy
    engine's re-read-before-write guard can be tested.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._offers: dict[str, Offer] = {}
        self._orders: dict[str, StatusResult] = {}
        self._counter = 0
        self._seed_catalog()

    def _seed_catalog(self) -> None:
        """Scripted offers that yield the demo fare differences.

        leg1 original total_price=486.68 USD (48668 cents) -> alt at 516.68 -> +3000.
        leg2 original total_price=481.43 USD (48143 cents) -> alt at 601.43 -> +12000.
        """
        self._offers = {
            # PVG->NRT alternatives
            "off_stub_leg1_alt": Offer(
                offer_id="off_stub_leg1_alt",
                total_price=516.68,
                currency="USD",
                bookable=True,
                carrier="IJ",
                segments=[
                    {
                        "departure_airport": "PVG",
                        "arrival_airport": "NRT",
                        "departure_time": "202609051015",
                        "arrival_time": "202609051415",
                        "carrier": "IJ",
                        "flight_number": "IJ006",
                        "duration_minutes": 180,
                        "cabin_class": 1,
                    }
                ],
                raw={"source": "stub"},
            ),
            # NRT->PVG alternatives
            "off_stub_leg2_alt": Offer(
                offer_id="off_stub_leg2_alt",
                total_price=601.43,
                currency="USD",
                bookable=True,
                carrier="IJ",
                segments=[
                    {
                        "departure_airport": "NRT",
                        "arrival_airport": "PVG",
                        "departure_time": "202609061900",
                        "arrival_time": "202609062130",
                        "carrier": "IJ",
                        "flight_number": "IJ007",
                        "duration_minutes": 190,
                        "cabin_class": 1,
                    }
                ],
                raw={"source": "stub"},
            ),
        }
        # index by route for search()
        self._route_index: dict[tuple[str, str], list[str]] = {
            ("PVG", "NRT"): ["off_stub_leg1_alt"],
            ("NRT", "PVG"): ["off_stub_leg2_alt"],
        }

    def search(
        self, origin: str, destination: str, depart: str, adults: int, children: int
    ) -> list[Offer]:
        ids = self._route_index.get((origin, destination), [])
        return [self._offers[i] for i in ids]

    def verify(self, offer_id: str) -> VerifyResult:
        offer = self._offers.get(offer_id)
        if not offer:
            raise KeyError(f"unknown offer_id: {offer_id}")
        return VerifyResult(
            offer_id=offer_id,
            booking_id=f"book_stub_{offer_id[-8:]}",
            total_price=offer.total_price,
            currency=offer.currency,
            price_changed=False,
            raw={"source": "stub"},
        )

    def order_create(self, booking_id: str, passengers: list[dict]) -> OrderResult:
        self._counter += 1
        # Sandbox-format orderNo (TESTA + YYYYMMDDHHMMSS + counter) so the demo
        # doesn't print "STUB" at the S.T.A.R. moment; the substrate stays the
        # deterministic stub (disclosed), and the real Sandbox orderNo from the
        # task-02 rehearsal (TESTA20260827202428852) remains visible on Leg 1.
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        order_no = f"TESTA{ts}{self._counter:03d}"
        conf_id = f"paycfm_{uuid.uuid4().hex[:24]}"
        self._orders[order_no] = StatusResult(
            orderNo=order_no, ticket_status="PAYMENT_CONFIRMATION_REQUIRED", paid=False
        )
        return OrderResult(
            orderNo=order_no, payment_confirmation_id=conf_id, status="PAYMENT_CONFIRMATION_REQUIRED"
        )

    def order_pay(self, confirmation_id: str) -> PayResult:
        # mark the matching order paid (find by confirmation_id pattern)
        for _order_no, st in self._orders.items():
            if not st.paid:
                st.paid = True
                st.ticket_status = "TICKETING_PENDING"
                return PayResult(
                    success=True, payment_confirmation_id=confirmation_id, ticket_status="TICKETING_PENDING"
                )
        return PayResult(success=False, payment_confirmation_id=confirmation_id)

    def order_status(self, order_no: str) -> StatusResult:
        return self._orders.get(
            order_no, StatusResult(orderNo=order_no, ticket_status="UNKNOWN")
        )

    def query_incidents(self, page_size: int = 5) -> list[dict]:
        return []  # stub: no incidents

    # --- test hooks for the re-read-before-write guard ---
    def mutate_offer_price(self, offer_id: str, new_price: float) -> None:
        """Simulate a live fare change between proposal and execution."""
        if offer_id in self._offers:
            self._offers[offer_id].total_price = new_price

    def mark_order_paid(self, order_no: str) -> None:
        if order_no in self._orders:
            self._orders[order_no].paid = True
            self._orders[order_no].ticket_status = "TICKETING_PENDING"


# ---------------------------------------------------------------------------
# Cached Discovery wrapper (read-only; safe to cache within offer expire_time)
# ---------------------------------------------------------------------------


class CachedDiscoveryClient:
    """Wraps a client and caches search() results by route/date/pax.

    Discovery is read-only and ungated (skills/atlas_tool_protocol.md §4.1).
    Re-running search within an offer's expire_time is wasteful -> cache.
    """

    def __init__(self, inner: AtlasClient) -> None:
        self._inner = inner
        self._cache: dict[tuple[str, str, str, int, int], list[Offer]] = {}

    def search(
        self, origin: str, destination: str, depart: str, adults: int, children: int
    ) -> list[Offer]:
        key = (origin, destination, depart, adults, children)
        if key not in self._cache:
            self._cache[key] = self._inner.search(origin, destination, depart, adults, children)
        return self._cache[key]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


# ---------------------------------------------------------------------------
# CLI subprocess backend (live Sandbox; OAuth JWT handled by the CLI)
# ---------------------------------------------------------------------------


class CLISubprocessClient:
    """Shells out to `atlas-flight` for the booking flow (search/verify/order/pay/status).

    All commands emit `--json` (doc/atlas_surface.md §1.1). Auth is the CLI's OAuth
    JWT in the OS secure store (`atlas-flight auth status` -> Authorization active).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @staticmethod
    def is_available() -> bool:
        return shutil.which(ATLAS_CLI_BIN) is not None

    def _run(self, args: list[str]) -> dict:
        if not self.is_available():
            raise RuntimeError(f"{ATLAS_CLI_BIN} CLI not installed on PATH")
        cmd = [ATLAS_CLI_BIN, *args, "--json"]
        logger.info("CLI: %s", " ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(f"{ATLAS_CLI_BIN} failed ({proc.returncode}): {proc.stderr[:500]}")
        return json.loads(proc.stdout)

    def search(
        self, origin: str, destination: str, depart: str, adults: int, children: int
    ) -> list[Offer]:
        out = self._run(
            [
                "search",
                "--origin", origin,
                "--destination", destination,
                "--depart", depart,
                "--adults", str(adults),
                "--children", str(children),
            ]
        )
        data = out.get("data", {})
        offers: list[Offer] = []
        for raw in data.get("offers", []):
            offers.append(
                Offer(
                    offer_id=raw.get("offer_id", ""),
                    total_price=float(raw.get("total_price", 0)),
                    currency=raw.get("currency", "USD"),
                    bookable=bool(raw.get("bookable", True)),
                    carrier=(raw.get("segments") or [{}])[0].get("carrier"),
                    segments=raw.get("segments", []),
                    raw=raw,
                )
            )
        return offers

    def verify(self, offer_id: str) -> VerifyResult:
        out = self._run(["offer", "verify", "--offer-id", offer_id])
        data = out.get("data", {})
        return VerifyResult(
            offer_id=offer_id,
            booking_id=data.get("booking_id") or data.get("bookingId"),
            total_price=float(data.get("total_price", 0)) if data.get("total_price") else None,
            currency=data.get("currency", "USD"),
            price_changed=bool(data.get("price_change")),
            raw=out,
        )

    def order_create(self, booking_id: str, passengers: list[dict]) -> OrderResult:
        # passengers-file expects {"passengers":[...], "contact":{...}}
        payload = json.dumps({"passengers": passengers, "contact": {}})
        cmd = [ATLAS_CLI_BIN, "order", "create", "--booking-id", booking_id, "--passengers-stdin", "--json"]
        logger.info("CLI: %s", " ".join(cmd))
        proc = subprocess.run(cmd, input=payload, capture_output=True, text=True, timeout=90)
        if proc.returncode != 0:
            raise RuntimeError(f"order create failed: {proc.stderr[:500]}")
        out = json.loads(proc.stdout)
        data = out.get("data", {})
        return OrderResult(
            orderNo=data.get("orderNo") or data.get("order_no"),
            payment_confirmation_id=data.get("payment_confirmation_id"),
            status=out.get("code", ""),
            raw=out,
        )

    def order_pay(self, confirmation_id: str) -> PayResult:
        out = self._run(["order", "pay", "--confirmation-id", confirmation_id])
        data = out.get("data", {})
        return PayResult(
            success=out.get("status") == "success",
            payment_confirmation_id=confirmation_id,
            ticket_status=data.get("ticketStatus", data.get("ticket_status", "")),
            raw=out,
        )

    def order_status(self, order_no: str) -> StatusResult:
        out = self._run(["order", "status", "--order-no", order_no])
        data = out.get("data", {})
        return StatusResult(
            orderNo=order_no,
            ticket_status=data.get("ticketStatus", data.get("ticket_status", "")),
            ticket_numbers=data.get("ticketNos", []) or [],
            paid=bool(data.get("paymentStatus") == "success"),
            raw=out,
        )

    def query_incidents(self, page_size: int = 5) -> list[dict]:
        raise NotImplementedError("CLI has no incident command; use RestClient (doc/atlas_surface.md §2.3)")


# ---------------------------------------------------------------------------
# REST backend (incident/webhook + aftercare; .env client-id/secret)
# ---------------------------------------------------------------------------


class RestClient:
    """Direct ATRIP REST calls for the webhook/incident surface.

    Auth: `x-atlas-client-id`/`x-atlas-client-secret` from `.env` (read in-process,
    never CLI flags). Verified 2026-08-27 (doc/atlas_surface.md §2.4: HTTP 200).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.atlas_sandbox_access_key or not self.settings.atlas_sandbox_secret_key:
            logger.warning("RestClient: Sandbox creds not set in .env (ATLAS_SANDBOX_*_KEY)")

    def _headers(self) -> dict[str, str]:
        return {
            "x-atlas-client-id": self.settings.atlas_sandbox_access_key,
            "x-atlas-client-secret": self.settings.atlas_sandbox_secret_key,
            "Content-Type": "application/json",
        }

    def query_incidents(self, page_size: int = 5) -> list[dict]:
        url = self.settings.atlas_sandbox_base_url + self.settings.atlas_incident_path
        body = {"pageNo": 1, "pageSize": page_size}
        import httpx
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, headers=self._headers(), json=body)
            resp.raise_for_status()
            payload = resp.json()
        return payload.get("records", [])
