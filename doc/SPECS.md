---
status: draft
created: 2026-08-27
product: TripCascade
source_of_truth: doc/PRD.md
---

# Specifications — TripCascade

This document is **derived from `doc/PRD.md`**. Every spec is testable, cross-referenced to its FR ID and user story, carries verbatim **Given/When/Then** acceptance criteria and a **verification** method, and is ordered by priority (P0 → P1). It adds **nothing** beyond the PRD's scope. Structure: Overview → Scope & Non-Goals → Numbered Specs → Data Model → Interfaces → Open Questions.

---

## 1. Overview

TripCascade is an agentic AI that forecasts a flight disruption with ML, models the trip as a dependency graph, cascades the forecast into re-planning every affected downstream leg via the Atlas API, and settles fare differences under bounded autonomy (auto-settle ≤ a pre-authorized cap with an audit log; human approval above the cap). This document specifies the demoable core: one family trip, one disruption type, one cascade.

**Authoritative state thread (per `resources/external_research.md` §3):** `routingIdentifier` (search) → `offer_id` → `sessionId` (verify) → `orderNo` (order/payment) → `payment_confirmation_id` (payment) → ticket number (ticketing). These identifiers are preserved on graph nodes and decision records.

**Default settlement cap:** S$50 = **5000 cents** (verified `python3 -c "print(50*100)"` → `5000`), configurable.

---

## 2. Scope & Non-Goals

**In Scope (demoable core):** one trip (PVG→NRT→hotel→NRT→PVG, family of 3, 4–6 Sep 2026); one disruption type (typhoon-induced delay/cancellation, ML-forecast); one cascade (Leg 1 re-plan auto-settled ≤ cap + advisory hotel notification + Leg 2 re-plan human-approved > cap); bounded-autonomy settlement on every Commitment/Money/Aftercare Atlas action; a decision-learning log; an experiential UI.

**Non-Goals / Out of Scope:** real-time webhooks as the *primary* Watcher trigger (scheduled poll is P0; webhooks are P1 stretch, pending `doc/atlas_surface.md`); booking hotels/activities/transfers through Atlas if the surface audit classifies them advisory; business-traveler persona; multi-trip management; production payment rails (Sandbox only); training the forecast on Atlas-curated delay data (default = public historical on-time data, decided in `tasks/03-data_ml.md`); multi-agent orchestration.

---

## 3. Numbered Specs

Legend: **Priority** P0 = demo-critical core; P1 = rubric-relevant infrastructure. Each spec cross-references its **FR** and **User Story**.

---

### S-001 / FR-001 — Dependency-graph construction — P0 — US1

**Given** a booked itinerary (Leg 1 flight PVG→NRT, Tokyo hotel, Leg 2 flight NRT→PVG) sourced from the demo seed `assets/demo_itinerary.json`
**When** the graph builder loads the itinerary
**Then** a DAG is produced with one node per leg/commitment, edges of type `depends_on`/`temporal`, and every node carries an `actionable` flag (flights `true` `[Inference]`, hotel `false` `[Inference]`), scheduled times, booking constraints, a null `disruption_probability` (until FR-002), and the ATRIP state refs (`offer_id`/`orderNo`) preserved on flight nodes

**Verification:** unit test asserts `node_count == 3`, `edge_count >= 2`, every node has a non-null `actionable` flag, and flight nodes retain their `offer_id`. **Evidence source for `actionable`:** `doc/atlas_surface.md` (reconciliation rule in §4).

---

### S-002 / FR-002 — Disruption forecast (ML) — P0 — US2

**Given** a trained XGBoost classifier artifact (from `tasks/03-data_ml.md`) and an Atlas itinerary leg with features {carrier, origin, destination, scheduled_dep_ts, season}
**When** the forecast inference function `predict_disruption(leg_features)` is called for a leg
**Then** it returns a float P(disruption) ∈ [0,1] that is written to the node's `disruption_probability` field

**Verification:** call the inference fn on Leg 1 → returns a float in [0,1]; in the demo scenario the typhoon-season features produce a score above the alert threshold. If the model is unavailable, an honest heuristic base-rate fallback returns a documented float (no silent failure).

---

### S-003 / FR-003 — Disruption Watcher (event detection) — P0 — US2

**Given** an itinerary with P(disruption) per leg (from FR-002) and a configurable alert threshold
**When** a scheduled forecast-poll runs (P0 trigger) and a leg's P(disruption) exceeds the threshold
**Then** the Watcher emits a `disruption_likely` event carrying `{node_id, p_disruption, threshold, ts}` that triggers the orchestrator

**Verification:** scripted test sets Leg 1's P(disruption) above threshold → a `disruption_likely` event is emitted with the correct `node_id`; the orchestrator receives and acts on it. (Webhook trigger is P1 stretch — see Open Questions §6.)

---

### S-004 / FR-004 — Cascade computation — P0 — US3

**Given** the dependency graph and an at-risk node (Leg 1) from FR-003
**When** the cascade computation walks the DAG from the at-risk node
**Then** every downstream node reachable via `depends_on`/`temporal` edges is marked `affected`, with per-edge `slack_minutes` computed (hotel check-in window slack, Leg 2 connection slack)

**Verification:** from at-risk Leg 1, the cascade marks the hotel node + Leg 2 as `affected`; the affected set equals the expected set {hotel, Leg2}; the UI highlights them.

---

### S-005 / FR-005 — Atlas re-planning (Discovery) — P0 — US4

**Given** an affected actionable node (Leg 1 / Leg 2) and an affected advisory node (hotel)
**When** the agent re-plans
**Then** for **actionable** nodes it calls Atlas `search` (Discovery, read-only, ungated) and returns ≥1 candidate with fare + schedule; for the **advisory** hotel node it drafts a notification (impact analysis + draft text) and makes **no** Atlas booking call

**Verification:** Atlas Sandbox `search` returns candidate flights for Leg 1 and Leg 2 (real `offer_id` thread); the hotel node produces a draft notification and no Commitment/Money/Aftercare call is issued for it.

---

### S-006 / FR-006 — Bounded-autonomy settlement — P0 — US4, US5

**Given** a proposed re-plan for an actionable node with a computed `fare_difference_cents` and the configured cap (default **5000 cents**)
**When** the deterministic policy engine evaluates the settlement
**Then**:
- if `fare_difference_cents <= cap_cents` → auto-execute the Atlas Commitment/Money/Aftercare action + write an audit-log record (`outcome = auto_settled`);
- if `fare_difference_cents > cap_cents` → hold, surface to the UI for human approval, and on verdict write a record (`outcome = human_approved | human_rejected`);
- the LLM **never** constructs the Atlas call body free-form — the policy engine builds it from structured data.

**Verification:**
- Unit test: `cap_cents = 5000`; Leg 1 diff `3000` → `auto_settle = True` (verified `python3 -c "print(30*100, 30*100<=50*100)"` → `3000 True`); Leg 2 diff `12000` → `human_gate = True` (verified `python3 -c "print(120*100, 120*100>50*100)"` → `12000 True`).
- Integration test: Leg 1 auto-settles + audit record written; Leg 2 is held until UI approval; a scripted test asserts no LLM-generated transaction body reaches the Atlas tool layer (the call body is assembled by the policy engine from `offer_id`/`orderNo`/`amount_cents`).

---

### S-007 / FR-007 — Decision-learning log — P0 — US6

**Given** any settlement (auto or human-gated) completes
**When** the record is written
**Then** a structured, reusable record exists with fields {`record_id`, `timestamp`, `node_id`, `action`, `amount_cents`, `cap_cents`, `outcome`, `human_verdict`, `reasoning_trace`, `model_tier_used`, `atlas_state_refs`, `reusable`} and is retrievable by `node_id`

**Verification:** after the demo cascade, query the log by Leg 1 `node_id` → one `auto_settled` record; by Leg 2 `node_id` → one `human_approved`/`human_rejected` record; all fields non-null where applicable; the record is marked `reusable = true` so it can train a future threshold.

---

### S-008 / FR-008 — Experiential UI — P0 — US1, US3, US4, US5

**Given** a trip graph, per-leg forecast, cascade, proposed re-plans, and the decision log
**When** the UI renders
**Then** it displays: (a) the trip graph; (b) per-leg P(disruption); (c) affected nodes highlighted; (d) proposed re-plan + fare-difference summary per node; (e) approve/reject controls for above-cap settlements; (f) the decision log

**Verification:** a recorded walk-through shows all six elements; the approve action on Leg 2 unblocks the held settlement and writes the decision record; the auto-settled Leg 1 shows its audit-log entry inline.

---

### S-009 / FR-009 — Model-tier routing — P1

**Given** a task labeled routine (parse/format/entity-extraction) vs hard (cascade reasoning, fare-difference logic)
**When** the router selects a model
**Then** routine tasks route to a cheap Qwen tier (`Qwen-Plus` or a locally-served open-weight Qwen on the Mac mini M4 Pro) and hard tasks route to `Qwen3.8-Max`, with a local open-weight fallback available so the core flow is not solely on a paid top-tier model

**Verification:** logs show `model_tier_used` per call; a local-fallback path exists and is exercised at least once in testing (the Cost Controllability evidence).

---

### S-010 / FR-010 — Acceptance / eval harness — P1

**Given** the Given/When/Then specs in this document
**When** the eval harness runs
**Then** every spec's "Then" is asserted against a real Atlas Sandbox outcome (or a clearly-labelled scripted stub where Sandbox is unavailable), and a pass/fail report is produced that asserts the **post-state** (e.g., a new `orderNo` exists) not just an HTTP 200 — the cure for "false success"

**Verification:** the harness runs green on the demo scenario end-to-end in `tasks/06-eval_harness.md`; a failing/stubbed call is correctly reported as fail (no false success).

---

## 4. Data Model

The dependency graph is a DAG of **nodes** (legs/commitments) connected by **edges** (dependencies). Node classification (`actionable`) is **evidence-based**.

### 4.1 Node (leg / commitment)

| Field | Type | Notes |
|---|---|---|
| `node_id` | str | Unique. |
| `node_type` | enum {`flight`, `hotel`, `activity`, `transfer`} | |
| `actionable` | bool | `true` = bookable via Atlas; `false` = advisory-only (impact analysis + drafted notification, never a fake booking). **Confirmed by `doc/atlas_surface.md` §4 (2026-08-27):** flight = `true`; hotel/activity/transfer = `false` (Atlas CLI + REST are flights + ancillaries only — no hotel/activity/transfer endpoints). |
| `atlas_entity_ref` | object \| null | `{offer_id, booking_id, orderNo}` for actionable; `null` for advisory. |
| `scheduled_start` | ISO8601 | |
| `scheduled_end` | ISO8601 | |
| `location_origin` | str \| null | Airport/city. |
| `location_destination` | str \| null | Airport/city. |
| `booking_constraints` | object | `{cancel_by: ISO8601, no_show_penalty_cents: int, fare_class: str, refundable: bool}`. |
| `disruption_probability` | float \| null | ∈ [0,1]; set by FR-002; `null` until forecast runs. |
| `status` | enum | {`planned`, `at_risk`, `affected`, `re_planned`, `settled`, `held_for_approval`, `completed`}. |
| `depends_on` | [node_id] | Upstream nodes (edge references). |
| `temporal_constraint` | object \| null | `{min_gap_minutes: int, max_gap_minutes: int}`. |
| `passengers` | [object] | `{name: str, type: adult\|child, age: int}`. |
| `fare_difference_cents` | int \| null | Set during re-planning (FR-005). |
| `settlement` | object \| null | `{cap_cents: int, auto_settle_eligible: bool, decision_log_id: str \| null}`. |
| `evidence_source` | str | e.g., `"doc/atlas_surface.md v1"` — provenance for the `actionable` flag. |

### 4.2 Edge

| Field | Type | Notes |
|---|---|---|
| `edge_id` | str | Unique. |
| `from_node` | node_id | Upstream. |
| `to_node` | node_id | Downstream (the dependent). |
| `edge_type` | enum {`depends_on`, `temporal`, `booking`} | |
| `constraint` | object | `{slack_minutes: int, hard: bool}`. |
| `slack_minutes` | int | Computed buffer (e.g., connection slack). |

### 4.3 Decision-learning record (FR-007)

| Field | Type | Notes |
|---|---|---|
| `record_id` | str | Unique. |
| `timestamp` | ISO8601 | |
| `node_id` | node_id | The node the decision concerned. |
| `action` | enum {`re_book`, `change`, `cancel`, `refund`, `notify`} | |
| `amount_cents` | int | Fare difference / refund amount. |
| `cap_cents` | int | The cap in force at decision time. |
| `outcome` | enum {`auto_settled`, `human_approved`, `human_rejected`} | |
| `human_verdict` | str \| null | Free text when above cap. |
| `reasoning_trace` | str | LLM rationale (the proposal, not the execution). |
| `model_tier_used` | str | e.g., `Qwen3.8-Max` / `Qwen-Plus` / `local-open-weight`. |
| `atlas_state_refs` | object | `{orderNo: str \| null, payment_confirmation_id: str \| null}`. |
| `reusable` | bool | Whether this record can train a future threshold (the learning loop). |

### 4.4 Reconciliation rule (actionable flag)

**Reconciled 2026-08-27** against `doc/atlas_surface.md` §4 (per TODO.md §11 Decision 4): the audit **confirms the assumption** — Atlas (CLI + REST) acts on flights + ancillaries only; hotels/activities/transfers are advisory. No change to §4.1's classification. The `[Inference]` tags on flight/hotel in `doc/PRD.md` §9 and §4.1 above are upgraded to evidence-backed. Open Questions #1, #2, #3 (§6) are resolved.

---

## 5. Interfaces

The authoritative Atlas tool-layer substrate (CLI vs REST vs hybrid) is decided in `doc/atlas_surface.md`. The **interface contract** below is substrate-agnostic; the wrapper exposes the same signatures either way.

### 5.1 Atlas tool layer (cross-ref `doc/atlas_surface.md`)
- `search(origin, destination, date, passengers) -> [Offer]` — Discovery, read-only, ungated.
- `verify(offer_id) -> Session{session_id}` — Commitment.
- `order(session_id, passengers) -> {orderNo}` — Commitment.
- `payment(orderNo, amount_cents) -> {payment_confirmation_id}` — Money.
- `ticketing(orderNo) -> {ticket_number}` — Aftercare.
- `change(orderNo, new_offer_id) -> status` / `cancel(orderNo) -> status` / `refund(orderNo) -> status` — Aftercare.
- **Policy gate:** `verify`, `order`, `payment`, `ticketing`, `change`, `cancel`, `refund` route through the FR-006 policy engine. `search` does not.

### 5.2 Forecast inference (from `tasks/03-data_ml.md`)
- `predict_disruption(leg_features: LegFeatures) -> float` where `LegFeatures = {carrier, origin, destination, scheduled_dep_ts, season, ...}`. Returns P(disruption) ∈ [0,1]. Trained artifact + inference fn exported by task 03.

### 5.3 Policy engine (FR-006)
- `evaluate_settlement(node_id, proposed_replan) -> SettlementDecision{auto_settle: bool, amount_cents, cap_cents, held: bool, decision_id}`.
- `execute_approved(decision_id) -> AtlasResult` — invoked by the UI's approve action for above-cap settlements; invoked internally for auto-settle.

### 5.4 Disruption Watcher event (FR-003)
- Event schema: `{event_type: "disruption_likely", node_id: str, p_disruption: float, threshold: float, ts: ISO8601}`. Consumed by the orchestrator.

### 5.5 UI ↔ agent API (FR-008)
- `GET /trip/{id}/graph` — the DAG.
- `GET /trip/{id}/forecast` — per-leg P(disruption).
- `POST /trip/{id}/replan/{node_id}/approve` — human approval for above-cap settlements.
- `GET /trip/{id}/decisions` — the decision-learning log.

---

## 6. Open Questions

| # | Question | Owner / Next task |
|---|---|---|
| 1 | ~~Does the curated Atlas dataset include delay/OTP fields?~~ **RESOLVED (2026-08-27):** No — the "curated dataset" is Atlas API content (140+ airlines, O&D pairs), not delay/OTP labels. Use BTS/Kaggle + route-generalization. See `doc/atlas_surface.md` §5. | ✅ `doc/atlas_surface.md` → `tasks/03-data_ml.md` |
| 2 | ~~Are hotels/activities/transfers Atlas-actionable?~~ **RESOLVED (2026-08-27):** flights + ancillaries only; hotels/activities/transfers advisory. See `doc/atlas_surface.md` §4. | ✅ `doc/atlas_surface.md` |
| 3 | ~~ATRIP Sandbox webhook support + event types?~~ **RESOLVED (2026-08-27):** YES — `updateWebhookURL.do` + `POST /event/getPageList.do`; events `abnormal.cancelled`, `order.schedulechange`, `email.schedulechange`; delivery best-effort → scheduled poll stays P0. P1 webhook stretch viable. See `doc/atlas_surface.md` §3. | ✅ `doc/atlas_surface.md` → `tasks/05-cloud_deploy.md` |
| 4 | Atlas Sandbox rate limits / stability? | `tasks/04-agent_core.md` / `tasks/05-cloud_deploy.md` — cache Discovery results; rehearse the scripted scenario |
| 5 | Exact ML feature alignment between training data and Atlas itinerary fields? | `tasks/03-data_ml.md` — keep features minimal and generalizable (carrier, route, scheduled-time, season) |

*Every spec above routes Commitment/Money/Aftercare Atlas actions through the settlement policy (auto ≤ cap with audit log; explicit human approval above cap). Nothing in this document exceeds the PRD's scope.*
