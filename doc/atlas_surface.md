---
status: draft
created: 2026-08-27
product: TripCascade
source_of_truth: tasks/02-setup.md (Goal 4)
evidence_date: 2026-08-27
---

# Atlas Surface Audit — TripCascade

This document is the evidence base for the Atlas tool layer (`doc/SPECS.md` §5.1, Open Questions #2/#3) and resolves the dependency-graph `actionable` node classification (`doc/SPECS.md` §4.4) before `tasks/04-agent_core.md` begins. Every claim is backed by a command output, a REST response, or a quoted ATRIP doc page; inferences are labelled `[Inference]`.

**TL;DR (the four answers):**
1. **CLI scriptable:** `search`, `offer list`, `offer verify`, `order create`, `order pay`, `order status`, `booking confirm-price`, `booking baggage/seat {list,select,remove}` — all emit `--json`. **Gaps:** no ticketing / reshop / change / cancel / refund / void / disruption-alternatives commands (ticketing surfaces via `order status`).
2. **REST scriptable:** `/search.do`, `/verify.do`, `/order.do`, `/pay.do`, `/queryOrderDetails.do`, `/getLuggage.do`, `/seatAvailability.do`, `/event/getPageList.do`, `updateWebhookURL.do`. **Directly exercised** the Sandbox incident endpoint with `.env` creds → HTTP 200.
3. **Actionable entities:** flights + ancillaries (baggage/seat) **only**. Hotels/activities/transfers are NOT Atlas-actionable → **confirms the `doc/PRD.md` / `doc/SPECS.md` §4.1 assumption** (flight = `actionable: true`; hotel/activity/transfer = `actionable: false`, advisory-only). No SPECS reconciliation change required.
4. **Webhooks:** **YES** — `updateWebhookURL.do` (register one URL) + `POST /event/getPageList.do` (incident query). Event types include disruption-relevant signals (`abnormal.cancelled`, `order.schedulechange`, `email.schedulechange`). **Caveat:** delivery is best-effort → scheduled poll stays the P0 Watcher trigger; webhooks are the P1 stretch (matches `doc/SPECS.md` §6 Open Q#3).

**Recommended substrate: HYBRID** — CLI-primary for the booking flow (search→verify→order→pay + ancillaries, all `--json`, fastest integration); REST for the webhook/incident Watcher (FR-003) and aftercare capabilities the CLI lacks.

---

## 1. CLI Surface Audit

**Tool:** `atlas-flight` v0.3.12 (installed via `uv tool` at `~/.local/share/uv/tools/atlas-flight-booking/`, binary `~/.local/bin/atlas-flight`). Source: `atlas_cli` package (Python 3.12).

**Readiness (verified):**
```
$ atlas-flight auth status  →  Authorization active
$ atlas-flight doctor --json
{"schema_version":"1","status":"success","code":"DOCTOR_OK","message":"Atlas Flight Booking CLI readiness checks passed","data":{"checks":{"cli_version":true,"config_directory":true,"secure_store":true,"api_reachable":true,"authenticated":true}}}
```

### 1.1 Command tree + `--json` support

| Command | Sub-commands / flags | `--json` | Capability group |
|---|---|:---:|---|
| `search` | `--origin --destination --depart --adults --children --infants --return-date --airline --currency --multiple-fare-families` | ✅ | Discovery (read-only) |
| `offer list` | `--search-id` | ✅ | Discovery |
| `offer verify` | `--offer-id` | ✅ | Commitment (price confirm) |
| `booking confirm-price` | `--booking-id` | ✅ | Commitment (price re-confirm) |
| `booking baggage` | `list / select / remove` | (per leaf) | Ancillary (Commitment) |
| `booking seat` | `list / select / remove` | (per leaf) | Ancillary (Commitment) |
| `order create` | `--booking-id --passengers-file --passengers-stdin --seat-policy` | ✅ | Commitment |
| `order pay` | `--confirmation-id` | ✅ | Money |
| `order status` | `--order-no` | ✅ | Aftercare (order/ticket query) |
| `auth` | `login / status / poll --timeout` | ✅ | Auth |
| `doctor` | `--json` | ✅ | Health |

### 1.2 Live `search --json` evidence (PRD Leg 1: PVG→NRT 2026-09-04, 2 adults + 1 child)

Response shape (truncated to key fields):
```
schema_version: "1" | status: "success" | code: "FLIGHT_SEARCHED" | request_id: "17878330588063748309a"
data:
  search_id: "srch_09469ba11fb445cbde401d93"
  offer_count: 2
  offers: [
    { offer_id: "off_c40a320c84a6e92673eed3ca",
      currency: "USD", total_price: 486.68, transaction_fee_total: 0.0, bookable: true,
      price_status: "current", refresh_time: "...", expire_time: "...",
      passenger_prices: [{passenger_type:"adult",count:2,base_fare_per_passenger:104.56,tax_per_passenger:62.13,subtotal:333.38},
                         {passenger_type:"child",count:1,base_fare_per_passenger:104.56,tax_per_passenger:48.74,subtotal:153.3}],
      segments: [{departure_airport:"PVG",arrival_airport:"NRT",departure_time:"202609041735",arrival_time:"202609042135",
                  carrier:"IJ",operating_carrier:null,flight_number:"IJ004",duration_minutes:180,cabin_class:1,direction:"outbound"}],
      ancillary_supported: [...] },
    { offer_id: "off_c06e66f5cc5be48917ce32d0", currency:"USD", total_price:364.79, ... } ]
```
**Forecast-feature availability (`[Inference]`, aligns with `doc/SPECS.md` §5.2):** the search offer exposes `carrier`, `departure_airport`/`arrival_airport` (route), `departure_time` (scheduled time, `YYYYMMDDHHMM`), `cabin_class`, `duration_minutes` — the minimal, generalizable feature set the forecast model needs (carrier, route, scheduled-time, season derivable from date). No historical delay field is present (confirms the dataset finding in §5).

### 1.3 CLI gaps vs the 8 capability groups

| Capability | CLI support | Note |
|---|---|---|
| search | ✅ | `search --json` |
| verify | ✅ | `offer verify --offer-id --json` |
| order | ✅ | `order create --booking-id --json` |
| payment | ✅ | `order pay --confirmation-id --json` |
| ticketing | ⚠️ indirect | No dedicated command; `order status --order-no` returns `ticketStatus` + `ticketNos` per passenger (see `atlas_cli/ticketing.py` → `/queryOrderDetails.do`). Ticketing is a **query**, not an issue action. |
| reshop | ❌ | No CLI command. |
| change / cancel / refund / void | ❌ | No CLI commands. REST/ATRIP-portal only (§2.3). |
| disruption-alternatives | ❌ | No CLI command. Re-discovery = a new `search` call. |
| ancillaries (baggage/seat) | ✅ | `booking baggage/seat {list,select,remove}` |

---

## 2. REST Surface Audit

**Source:** ATRIP public docs at `https://resources.atriptech.com/api-document/...` (extracted via Tavily, 2026-08-27) + the `atlas_cli` package source (`config.py`, `endpoints.py`, `ticketing.py`, `api_client.py`).

### 2.1 Base URLs (`atlas_cli/config.py`, verified)

| Setting | URL | Purpose |
|---|---|---|
| `sandbox_api_base_url` | `https://sandbox.atriptech.com` | Sandbox booking + transaction APIs |
| `prod_api_base_url` | `https://api-sg.atriptech.com` | Production (SG region) |
| `control_api_base_url` | `https://atrip-api.atriptech.com` | Auth/control (JWT issuance, portal) |
| `authorization_page_url` | `https://www.atriptech.com/#/login` | OAuth login page (CLI `auth login`) |

> The ATRIP docs state sandbox uses base URLs for the examples; production uses "one base URL for search and another for all transaction APIs" (`resources/external_research.md` §3). The sandbox uses a single host (`sandbox.atriptech.com`).

### 2.2 Endpoint map (`atlas_cli/endpoints.py`, verified)

| Capability | Endpoint | Auth |
|---|---|---|
| search | `/search.do` (also `/priceCompareSearch.do`) | JWT `Token` header |
| verify | `/verify.do` | JWT |
| baggage | `/getLuggage.do` | JWT |
| seat | `/seatAvailability.do` | JWT |
| order | `/order.do` | JWT |
| pay | `/pay.do` | JWT |
| order/ticket query | `/queryOrderDetails.do` | JWT |
| **webhook register** | `updateWebhookURL.do` | `x-atlas-client-id` + `x-atlas-client-secret` |
| **incident query** | `POST /event/getPageList.do` | `x-atlas-client-id` + `x-atlas-client-secret` |

### 2.3 Auth model (two paths — `[Inference]` on the mapping, verified by direct exercise)

- **Booking-flow APIs** (`/search.do`, `/verify.do`, `/order.do`, `/pay.do`, `/queryOrderDetails.do`, `/getLuggage.do`, `/seatAvailability.do`): authenticated with a **JWT `Token` header**, obtained via the OAuth browser flow (`atlas-flight auth login`) and stored in the OS secure store. The CLI uses this path (`atlas_cli/api_client.py`: `headers={"Token": jwt}`).
- **Webhook/Incident APIs** (`updateWebhookURL.do`, `/event/getPageList.do`): authenticated with **`x-atlas-client-id` + `x-atlas-client-secret` headers** — the Sandbox REST credentials Mike generated in ATRIP (`.env` keys `ATLAS_SANDBOX_ACCESS_KEY` / `ATLAS_SANDBOX_SECRET_KEY`).

### 2.4 Direct REST exercise (verified 2026-08-27)

A read-only incident query was made directly against the Sandbox REST API, reading credentials from `.env` **in-process** (no CLI flags, values never echoed):

```python
# POST https://sandbox.atriptech.com/event/getPageList.do
# headers: x-atlas-client-id, x-atlas-client-secret, Content-Type: application/json
# body: {"pageNo":1,"pageSize":5}
```
**Result:** `HTTP 200`; response keys `['records','pageIndex','pageSize','total','status','msg','requestId','clientRequestId']`; `status: 0` (success); `records: []` (0 incidents — expected, no bookings yet to generate events).

**Conclusion:** the Sandbox REST credentials in `.env` are **valid** for the webhook/incident surface. The booking-flow REST endpoints are reachable (the CLI — a thin REST wrapper — proved `api_reachable: true`), but a direct booking-flow REST call requires the JWT path and is deferred to `tasks/04-agent_core.md` (`atlas_tools/` wrapper). The CLI is the faster path for the booking flow and is used for the rehearsal (§4).

### 2.5 Aftercare via REST (verified from ATRIP docs)

From the ATRIP "Post-booking" FAQ + "API Documentation Updates" page:
- **Void:** "Expanded VOID airline coverage" / "Expanded Void workflow and webhook guidance" — void is a REST/ATRIP capability.
- **Refund / cancel:** "refunds and cancellations" via REST; "involuntary changes (schedule changes) → use the refund flow in ATRIP, free of charge."
- **Post-ticketing baggage:** "post-ticketing baggage and refund functionality via API as well as in ATRIP."
- **Seat after ticketing:** "Seat selection after ticketing is **not** supported."
- **Change to a different flight:** no dedicated "reshop/change-flight" API endpoint surfaced; the ATRIP FAQ refers "service requests for changes" to the ATRIP portal (Eva). **`[Inference]`** a flight change = a new search→verify→order→pay cycle (which the CLI supports) plus void/refund of the original — to be confirmed in `tasks/04-agent_core.md`.

---

## 3. Webhook Support (Open Question #3)

**YES — supported, with disruption-relevant event types.** Source: ATRIP page `api-reference/webhook-and-incident-apis/webhook-registration-and-incidents`.

- **Registration:** register one webhook URL via `updateWebhookURL.do`. "Atlas uses that URL for all supported webhook event types."
- **Incident query:** `POST /event/getPageList.do` — queryable by `eventId`, `orderNo`, `eventType`, `pnr`, `paxName`, `paxEmail`, `airline`, `eventStatus` (`0`=Unconfirmed, `1`=Confirmed), `eventTimeStart`. (Directly exercised in §2.4 → HTTP 200.)
- **Event/incident types (the disruption signals the Watcher needs):**
  - `email.schedulechange` — Schedule Change–Email Notification
  - `abnormal.cancelled` — Unaccounted Cancellation
  - `order.schedulechange` — Schedule Change–API Notification
- **Delivery caveat (critical):** "Does Atlas guarantee webhook delivery? **No.** Webhook delivery is best effort. Use airline emails, incident flows, and order queries for final confirmation."

**Implication for the build:**
- The scheduled forecast-poll remains the **guaranteed P0** Disruption Watcher trigger (`doc/SPECS.md` S-003). ✅ unchanged.
- Webhook registration + the incident-poll API are a **viable P1 stretch** for `tasks/05-cloud_deploy.md`: the Watcher can register a webhook URL and/or poll `/event/getPageList.do` for `abnormal.cancelled` / `order.schedulechange` events as a complementary, lower-latency signal. Open Question #3 → **resolved (yes, best-effort, disruption events available).**

---

## 4. Actionable Entity Types (Open Question #2)

**Finding: Atlas (CLI and REST) is flights + ancillaries only. Hotels, activities, and transfers are NOT Atlas-actionable.**

Evidence:
1. **CLI:** the `atlas-flight` command tree contains only flight + baggage/seat commands. No `hotel`, `activity`, `transfer`, `car`, `rail`, or `accommodation` command exists.
2. **REST:** the endpoint map (`endpoints.py`) lists only `/search.do`, `/verify.do`, `/order.do`, `/pay.do`, `/queryOrderDetails.do`, `/getLuggage.do`, `/seatAvailability.do`, and the webhook/incident endpoints. No hotel/activity/transfer endpoint.
3. **Docs:** a targeted search of `resources.atriptech.com` for "hotel / activity / transfer / accommodation" returned **zero Atlas results** — every hit was a third-party provider (Hotelbeds, Trawex, Tripgic, Flightslogic, Altexsoft), not ATRIP.
4. **ATRIP FAQ:** "all the available APIs are listed in ATRIP" — the public docs surface only the flight booking flow + post-booking aftercare.

**Reconciliation with `doc/SPECS.md` §4.4:** the working assumption holds —
- `flight` nodes → `actionable: true` (bookable via Atlas search→verify→order→pay→ticketing).
- `hotel` / `activity` / `transfer` nodes → `actionable: false` (advisory-only: impact analysis + drafted notification, never a fake booking).

**No change to `doc/SPECS.md` §4.1/§4.4 is required.** The `[Inference]` tags on flight/hotel classification in `doc/PRD.md` §9 and `doc/SPECS.md` §4.1 can be upgraded to evidence-backed (this document). Open Question #2 → **resolved.**

---

## 5. Curated Atlas Dataset (for `tasks/03-data_ml.md`)

**Finding: the "curated travel datasets" promised on the Luma/AISEA page are the Atlas API content itself (140+ airlines, tens of thousands of O&D pairs) — NOT a downloadable historical delay/on-time-performance dataset.**

Evidence (Tavily search, 2026-08-27):
- AISEA event page: "APIs and curated travel datasets—unlocking content and insights from **140+ airlines across tens of thousands of origin-[destination] pairs**."
- createwith.com: "access to Atlas travel APIs and curated datasets, and content covering more [airlines]…"

**Implication for the forecast model (FR-002, `tasks/03-data_ml.md`):** the Atlas dataset provides **inference-time itineraries** (carrier, route, scheduled time, fare) — not **training labels** (historical delay/cancellation outcomes). Therefore:
- Train the XGBoost classifier on a **public historical on-time dataset** (US DOT BTS/TranStats or Kaggle flight-delay), per `resources/external_research.md` §3.
- Apply **route-generalization validation** (held-out carriers) since US-carrier/route training does not transfer to Atlas LCC itineraries.
- Keep the feature set minimal and generalizable (carrier, route, scheduled-time, season) — all available in the `search` offer JSON (§1.2).
- Honest heuristic base-rate fallback if the public dataset transfer fails.

This resolves `doc/SPECS.md` §6 Open Question #1 (dataset does NOT include delay/OTP fields).

---

## 6. Substrate Recommendation: HYBRID

| Layer | Use | Why |
|---|---|---|
| **CLI (primary, booking flow)** | `search`, `offer verify`, `order create`, `order pay`, `order status`, `booking confirm-price`, `baggage/seat` | All emit `--json`; scriptable via `subprocess` + `json.loads`; no HTTP/header/JWT management; `doctor` proves reachability; fastest path to a working demo booking (FR-005/006). |
| **REST (incident/webhook)** | `updateWebhookURL.do`, `POST /event/getPageList.do` | CLI has no incident/webhook command; these are the Disruption Watcher's complementary signal (FR-003, task 05). Auth = `.env` client-id/secret (verified). |
| **REST (aftercare, deferred)** | void / refund / cancel / schedule-change refund | CLI has no aftercare commands; REST/ATRIP-portal only. Built in `tasks/04-agent_core.md` `atlas_tools/` wrapper (JWT path). The demo's auto-settled re-book uses a new CLI search→verify→order→pay cycle (not a "change" endpoint). |

**Auth strategy:** the `atlas_tools/` wrapper (task 04) will (a) shell out to the CLI for the booking flow (reusing its OAuth JWT), and (b) make direct REST calls with `x-atlas-client-id`/`x-atlas-client-secret` (from `.env`, never CLI flags) for the incident/webhook surface. Both credential paths are verified working on 2026-08-27.

**Why not REST-only?** The CLI already solves auth (OAuth → JWT → secure store), request signing, pagination, and JSON normalization; reimplementing that in Python for 7 booking endpoints is needless scope for a 10-day hackathon. The CLI is a thin, auditable wrapper over the same REST endpoints (confirmed by reading `endpoints.py`).

**Why not CLI-only?** The CLI cannot register webhooks, query incidents, or perform aftercare (void/refund/cancel) — all required for the Watcher (FR-003) and the bounded-autonomy settlement's aftercare arm (FR-006).

---

## 7. Open Items Handed to `tasks/04-agent_core.md` / `tasks/05-cloud_deploy.md`

| # | Item | Owner |
|---|---|---|
| 1 | Build `atlas_tools/` wrapper: CLI subprocess for booking flow + REST (`requests`/`urllib`) for incident/webhook; read creds from `.env` via `os.environ`, never CLI flags. | 04 |
| 2 | Confirm the "flight change" path: new search→verify→order→pay + void/refund of original (no dedicated change endpoint found). | 04 |
| 3 | Direct booking-flow REST call (JWT path) — optional; CLI is the demo path. | 04 |
| 4 | Watcher webhook registration (`updateWebhookURL.do`) + incident poll (`/event/getPageList.do`) on Alibaba Cloud Function Compute; best-effort delivery → keep scheduled poll as P0. | 05 |
| 5 | Sandbox rate limits (QPS/QPM) — ATRIP docs mention `429` + `retryAfter` governance; cache Discovery (`search`) results. | 04/05 |

---

## 8. Evidence Index (sources)

| Claim | Source |
|---|---|
| CLI command tree, `--json`, flags | `atlas-flight <cmd> --help` (2026-08-27) |
| CLI readiness | `atlas-flight doctor --json` → `DOCTOR_OK`, `api_reachable:true`, `authenticated:true` |
| Search JSON shape, offer_id, segments, prices | `atlas-flight search --origin PVG --destination NRT --depart 2026-09-04 --adults 2 --children 1 --json` |
| REST base URLs | `atlas_cli/config.py` (`sandbox_api_base_url`, `prod_api_base_url`, `control_api_base_url`) |
| REST endpoint map | `atlas_cli/endpoints.py` (`/search.do`, `/verify.do`, `/order.do`, `/pay.do`, `/queryOrderDetails.do`, `/getLuggage.do`, `/seatAvailability.do`) |
| JWT auth (booking APIs) | `atlas_cli/api_client.py` (`headers={"Token": jwt}`) |
| Webhook + incident endpoints, event types | ATRIP `api-reference/webhook-and-incident-apis/webhook-registration-and-incidents` (Tavily extract) |
| Webhook best-effort delivery, void/refund/cancel | ATRIP "Post-booking" FAQ + "API Documentation Updates" (Tavily extract) |
| Hotels/activities not in Atlas | Targeted Tavily search "atriptech API hotel activity transfer accommodation" → 0 Atlas hits |
| Curated dataset = API content | AISEA event page + createwith.com (Tavily extract, 2026-08-27) |
| **Direct REST exercise (creds valid)** | `POST https://sandbox.atriptech.com/event/getPageList.do` → HTTP 200, `status:0`, `records:[]` (2026-08-27) |

*This audit is the evidence source for `doc/SPECS.md` §4.4 (`actionable` flag) and §5.1 (tool-layer interfaces). It resolves Open Questions #1, #2, and #3.*
