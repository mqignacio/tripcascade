# Atlas Sandbox Rehearsal Log

**Date:** 2026-08-27 · **Environment:** ATRIP Sandbox (no real money) · **Tool:** `atlas-flight` CLI v0.3.12 (`atlas-flight auth status` = Authorization active; `doctor --json` = DOCTOR_OK, api_reachable:true, authenticated:true).
**Passengers:** synthetic (ZHANG/SAN, LI/SI, ZHANG/MING) — clearly fake, per coding skill §5.
**Purpose:** end-to-end booking rehearsal (search -> verify -> order -> payment -> ticketing) to confirm Atlas access and seed `assets/demo_itinerary.json`. Authorized per `tasks/02-setup.md` Goal 7 + Q3 (Option C: CLI now, Qoder GUI rehearsal later).

## State thread captured (the FR-005/006 evidence)

| Step | CLI command | Result | Key identifier |
|---|---|---|---|
| 1. Search | `atlas-flight search --origin PVG --destination NRT --depart 2026-09-04 --adults 2 --children 1 --json` | `FLIGHT_SEARCHED` (1.3s) | `offer_id=off_319604c13a009b0177820444`, `search_id=srch_...` |
| 2. Verify | `atlas-flight offer verify --offer-id off_319604c13a009b0177820444 --json` | `OFFER_VERIFIED` (1.4s), price_change=unchanged | `booking_id=book_661b9f9ff49253871f8df153` |
| 3. Order create | `atlas-flight order create --booking-id book_... --passengers-file /tmp/passengers.json --json` | `PAYMENT_CONFIRMATION_REQUIRED` (8.3s) — "Review the current payment summary before paying" | `orderNo=TESTA20260827202428852`, `payment_confirmation_id=paycfm_93833be3f3255ff75a661783` |
| 4. Pay | `atlas-flight order pay --confirmation-id paycfm_... --json` | `success` -> `TICKETING_PENDING` | payment confirmed |
| 5. Order status | `atlas-flight order status --order-no TESTA20260827202428852 --json` | `TICKETING_PENDING` (polled 3x over 36s) | `orderNo=TESTA20260827202428852` |

## Outcome

- **A real Sandbox order exists and is paid:** `orderNo=TESTA20260827202428852`, `payment_confirmation_id=paycfm_93833be3f3255ff75a661783`.
- **Ticketing status = pending.** Per the ATRIP "Sandbox Development" doc: "It validates Search, Verify, Order, and Pay. If the final retrieve step times out, treat that as expected during ticketing polling." The Sandbox does not always issue ticket numbers; this is documented ATRIP behavior, not a failure. The CLI's `ticketing.py` module confirms ticketing is a read-only order-status query (`/queryOrderDetails.do`) returning `ticketStatus` + `ticketNos` when issued.
- **Leg 1 (PVG->NRT, the disrupted/re-booked leg) is fully booked.** This matches `doc/PRD.md` §9 demo scenario Leg 1.
- **Leg 2 (NRT->PVG return) original offer identified** (`off_723f848650cfaff1cb184f70`, IJ003, 13:55->16:20, $481.43); booking deferred — same proven flow, to be completed in the Qoder GUI rehearsal (Q3 Option C) or `tasks/04-agent_core.md`.

## Passenger schema learned (for `tasks/04-agent_core.md` atlas_tools wrapper)

- `order create --passengers-file` expects JSON `{"passengers":[...], "contact":{...}}`.
- `Passenger`: `{traveler_id, name ("SURNAME/GIVEN" uppercase), passenger_type ("adult"|"child"|"infant"), gender ("M"|"F"), birthday (YYYY-MM-DD), nationality (2-letter), document:{type ("PP"|"GA"|"TW"|"TB"|"HY"), number, issuing_country, expires}}`.
- **`traveler_id` must match the slot IDs returned by `offer verify`** (`data.travelers[].traveler_id`, e.g. `trav_...`) — not arbitrary. Bind dynamically.
- `Contact`: `{name, email, mobile ("00<cc>-<number>")}`.
- `order create` returns `order_no` + `payment_confirmation_id` (status `PAYMENT_CONFIRMATION_REQUIRED`); `order pay` takes `--confirmation-id <payment_confirmation_id>` (NOT the orderNo).

## Raw evidence

Step JSON saved to `/tmp/rehearsal_{01_search,02_verify,03_order_create,04_pay,05_status}.json` (ephemeral; not committed — contains synthetic passenger data). The distilled state thread is in `assets/demo_itinerary.json`.
