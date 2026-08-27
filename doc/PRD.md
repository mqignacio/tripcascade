---
status: draft
created: 2026-08-27
product: TripCascade
---

# Product Requirements Document — TripCascade

**Hackathon:** Alibaba Cloud × Atlas Agentic AI Hackathon · Deadline 30 Aug 2026, 23:59 SGT.
**Author:** Mike (PhD AI student, UPD) — solo team. **Build surface:** Qoder (≥80% eligibility). **Atlas environment:** Sandbox only.

---

## 0. Product Identity (for the submission form)

**Product name:** TripCascade

**One-sentence description:** TripCascade is an agentic AI that forecasts a flight disruption with machine learning on historical on-time data, models the trip as a dependency graph, cascades the forecast into re-planning every affected downstream leg via the Atlas API, and settles fare differences under bounded autonomy — auto-settling at or below a pre-authorized cap with an audit log while escalating above-cap changes for human approval.

**Name rationale `[Inference]`:** "Trip" names the domain; "Cascade" names the core technical differentiator — the dependency-graph cascade that re-plans every downstream leg, which is the hackathon's own Level-4 benchmark ("autonomously re-plan every downstream leg and settle the fare difference in real time"). Domain and trademark clearance verified 27 Aug 2026: `tripcascade.com`, `.app`, `.ai` all unregistered; no active same-name travel product. (`tripguardian.app` was already taken; `TripHedge`, `WayGuard`, `TripRipple` all had active same-name products.)

---

## 1. Problem

Today's travel agents — human or chatbot — are **reactive**: they act only *after* a disruption lands. The traveler (or the seller who guaranteed the booking) absorbs the cost of a missed connection, a non-refundable hotel night, a forfeited activity, or a same-day re-book at peak fares.

Three gaps make this costly:

1. **No proactive forecast.** No consumer-facing travel agent forecasts a disruption *before* it is announced and pre-empts the cascade. `[Inference]` The 2026 agentic-travel landscape (Sabre/PayPal/MindTrip pipeline; Malaysia Airlines "Mavis") is reactive customer service and emerging end-to-end booking — none prominently does forecast-driven, dependency-graph cascade re-planning. [Source: OAG, "March 2026: The Month Agentic Travel Gets Real," https://www.oag.com/blog/march-2026-the-month-agentic-travel-gets-real]
2. **Trips are modeled as lists, not graphs.** A flight, a hotel, a return flight are stored as separate line items. When one leg breaks, the *downstream dependencies* (the hotel check-in window, the tight connection, the non-refundable activity) are not automatically identified or re-planned.
3. **Money steps are all-or-nothing.** Either a human approves every transaction (slow, doesn't scale, fails the Level-4 "autonomously settle" benchmark) or the AI free-forms transactions (unsafe — the rubric's ×0.5 "misuse" penalty targets free-form generation inside transactional flows).

TripCascade closes all three: an **ML forecast** makes the agent proactive; a **dependency graph** makes the cascade explicit and complete; and a **bounded-autonomy policy** (auto-settle ≤ cap with audit log, human approval above cap) lets the agent act safely at scale without ever free-forming transaction content.

---

## 2. Target User

**Primary (demo persona): the family/leisure traveler.** A parent managing a multi-leg leisure trip for the family — outbound flight, hotel, activities, return flight — who cannot babysit a trip in real time and whose non-refundable downstream commitments make a disruption expensive.

**Demo persona (concrete):** A parent traveling with family of 3 (2 adults + 1 child) Shanghai → Tokyo and back for a short leisure break. This persona is chosen because (a) a family has the most dependencies (child's schedule, non-refundable family-rate hotel, booked activities), (b) the problem statement explicitly names "with children," and (c) it makes the experiential UI emotionally legible in a 3-minute demo.

**Business customer (EBMC, not the demo surface):** travel sellers / OTAs who guarantee bookings and eat disruption costs today. See `doc/EBMC.md`.

---

## 3. Scope & Non-Goals

### In Scope (demoable core — one family trip, one disruption type, one cascade)
- One trip: Shanghai (PVG) → Tokyo (NRT) → Shanghai (PVG), family of 3, 4–6 Sep 2026.
- One disruption type: typhoon-induced flight delay/cancellation, forecast by ML.
- One cascade: Leg 1 disruption → re-plan Leg 1 (actionable, auto-settle ≤ cap) + advisory hotel notification + re-plan Leg 2 (actionable, human approval > cap).
- Bounded-autonomy settlement on every Commitment/Money/Aftercare Atlas action.
- A decision-learning log recording every auto-settlement and every above-cap human verdict.
- An experiential UI showing the trip, per-leg forecast, cascade, proposed re-plan, fare-difference summary, approve/reject, and the decision log.

### Non-Goals / Out of Scope (stretch — only after the core is green)
- Real-time Atlas webhooks as the *primary* Watcher trigger (scheduled forecast-poll is the guaranteed trigger; webhooks are a P1 stretch for `tasks/05-cloud_deploy.md`, pending `doc/atlas_surface.md` confirming Sandbox webhook support).
- Booking hotels / activities / transfers *through Atlas* (node classification is evidence-based — see §6; if `doc/atlas_surface.md` confirms hotels/activities are not Atlas-actionable, they are advisory-only: impact analysis + drafted notification, never a fake booking).
- Business-traveler persona, multi-trip management, group travel beyond the demo family of 3.
- Production payment rails — Sandbox only; no real money moves.
- Training the forecast model on Atlas-curated delay data `[Unverified]` — whether the curated Atlas dataset includes delay/OTP fields is unverified; the default training source is public historical on-time data (US DOT BTS/TranStats or Kaggle), decided in `tasks/03-data_ml.md`.
- Multi-agent orchestration (one orchestrator agent is sufficient for the demo).

---

## 4. User Stories

**US1 — Model my whole trip.** As a family traveler, I want the agent to load my booked itinerary as a connected dependency graph (not a flat list), so that when one leg is at risk I can see everything that depends on it.
**Trace:** FR-001 (graph construction), FR-008 (UI). Demo: the PVG→NRT→hotel→NRT→PVG trip renders as a graph in the UI.

**US2 — Know my disruption risk before it lands.** As a family traveler, I want the agent to forecast the probability that a flight will be disrupted (delayed/cancelled) using historical on-time data, so that I can act before the airline announces it.
**Trace:** FR-002 (ML forecast), FR-003 (watcher). Demo: Leg 1 shows a high P(disruption) driven by a typhoon signal.

**US3 — See what else breaks.** As a family traveler, when a leg is at risk I want the agent to show me every downstream commitment that is affected (hotel, return flight), so that I'm not surprised by a cascade I didn't see coming.
**Trace:** FR-004 (cascade computation), FR-008 (UI). Demo: the graph highlights the hotel node + Leg 2 as downstream of the at-risk Leg 1.

**US4 — Let the agent handle small fare differences.** As a family traveler, I want the agent to automatically re-book a downstream leg when the fare difference is within a cap I pre-authorized, so that I don't have to approve every trivial change.
**Trace:** FR-005 (Atlas re-planning), FR-006 (settlement), FR-007 (decision log). Demo: Leg 1 is re-booked for a S$30 fare difference (≤ S$50 cap) → auto-settled, recorded in the log.

**US5 — Approve the big changes myself.** As a family traveler, when a fare difference exceeds my cap, I want the agent to pause and show me the proposed re-plan and total cost, so that a human — not the AI — decides on a material cost.
**Trace:** FR-006 (settlement), FR-008 (UI). Demo: Leg 2 re-plan is S$120 (> S$50 cap) → human approval surfaced in the UI.

**US6 — Every decision becomes a learning.** As the operator/founder, I want every auto-settlement and every above-cap human verdict recorded as a structured, reusable record, so that today's human judgement becomes tomorrow's model intelligence (the bounded-autonomy loop learns over time).
**Trace:** FR-007 (decision-learning log). Demo: the UI shows the decision log; the above-cap Leg 2 verdict (approved/rejected) is captured as a reusable record.

---

## 5. Functional Requirements

Each FR carries a **priority** (P0 = demo-critical core; P1 = rubric-relevant infrastructure) and a **demo-scenario trace**. Priorities feed `doc/SPECS.md` ordering (P0 → P1 → P2).

| FR | Title | Priority | Demo-scenario trace |
|---|---|---|---|
| **FR-001** | Dependency-graph construction | P0 | The 3-leg family trip (PVG→NRT flight, Tokyo hotel, NRT→PVG flight) is loaded as a DAG; each node carries temporal + booking constraints and an `actionable` flag. |
| **FR-002** | Disruption forecast (ML) | P0 | An XGBoost classifier trained on historical on-time data outputs P(disruption) for Leg 1; the typhoon-season features drive a high score. |
| **FR-003** | Disruption Watcher (event detection) | P0 | A scheduled forecast-poll (P0) emits a "disruption likely" event for Leg 1; the agent is triggered. |
| **FR-004** | Cascade computation | P0 | The agent walks the DAG from the at-risk Leg 1 and marks the hotel node + Leg 2 as affected, with per-edge slack. |
| **FR-005** | Atlas re-planning (Discovery) | P0 | For actionable nodes the agent searches Atlas for alternatives (Leg 1 reroute/next-day; Leg 2 later return); for the advisory hotel node it drafts a notification, never a fake booking. |
| **FR-006** | Bounded-autonomy settlement | P0 | Leg 1 fare diff S$30 (≤ S$50 cap) → auto-settle + audit log; Leg 2 fare diff S$120 (> cap) → human approval. The policy engine is deterministic code; the LLM never free-forms transaction content. |
| **FR-007** | Decision-learning log | P0 | Every settlement (auto and human-gated) and every human verdict is written as a structured, reusable record; visible in the UI. |
| **FR-008** | Experiential UI | P0 | The UI shows the trip graph, per-leg forecast, cascade (affected nodes highlighted), proposed re-plan, fare-difference summary, approve/reject, and the decision log. |
| **FR-009** | Model-tier routing | P1 | Routine parse/format routes to a cheap Qwen tier; the hard cascade reasoning routes to Qwen3.8-Max; a local open-weight fallback keeps the core flow off paid-only tiers. |
| **FR-010** | Acceptance / eval harness | P1 | Given/When/Then tests per agent step assert real Atlas Sandbox outcomes (the cure for "false success"); run in `tasks/06-eval_harness.md`. |

> The money-changing Atlas actions — verify, book, payment, change/cancel/refund — are all **Commitment/Money/Aftercare** actions and route exclusively through the FR-006 settlement policy. Discovery (search/alternatives) is read-only and ungated. See §7.

---

## 6. Settlement Policy (bounded autonomy)

**Core rule.** Every Commitment/Money/Aftercare Atlas action is routed through a **deterministic policy engine** (code, never the LLM). The LLM proposes and explains; the policy engine decides and executes.

**Auto-settle (≤ cap).** When the computed fare difference for a proposed re-plan is **at or below the pre-authorized cap**, the policy engine auto-executes the Atlas action and writes an audit-log entry. No human in the loop. This is what satisfies the Level-4 benchmark ("autonomously … settle the fare difference in real time").

**Human approval (> cap).** When the fare difference is **above the cap**, the policy engine holds the action, surfaces the proposed re-plan + total cost to the human in the UI, and executes only on explicit human approval (or rejects). Every above-cap verdict is recorded.

**Default cap: S$50 (5000 cents), configurable.** Per TODO.md §11 Decision 1 (Mike-approved). Configurable in `doc/SPECS.md` and at runtime via the policy engine's config; the cap is read by the policy engine, not generated by the LLM.

**Why bounded, not blanket-gate and not free-form.** The kickoff deck's ×0.5 "misuse" penalty targets **free-form generation inside transactional flows** — bounded, audited autonomy is not that. The Level-4 benchmark and its ×2 "impossible without AI" multiplier reward autonomous money judgement; a blanket human-gate on every transaction would fail that benchmark. Bounded autonomy is the synthesis: autonomy within a pre-authorized, audited bound.

**Decision-learning loop.** The audit log is not a side effect — it is **FR-007**, the decision-learning log. Per `resources/founder_lessons.md`: "AI tools that start as copilots are in a judgement loop… the judgement of today is the intelligence of tomorrow." Every auto-settlement and every above-cap human verdict is a structured, reusable record; over time these records train the policy engine's thresholds. The narrative: *every decision becomes tomorrow's learning.*

**Demo cap arithmetic (verified 2026-08-27):** cap = S$50 = 5000 cents. Leg 1 fare diff S$30 (3000 cents) ≤ cap → auto-settle. Leg 2 fare diff S$120 (12000 cents) > cap → human approval. (`python3 -c "print(30<=50, 120>50, 50*100)"` → `True True 5000`.)

---

## 7. Atlas Action Classification

Atlas actions map to the four capability groups from the kickoff deck and `resources/external_research.md` §3:

| Atlas action | Group | Gating |
|---|---|---|
| search (fare/route/alternatives) | Discovery | Read-only, ungated — safe to hammer in Sandbox (cache results). |
| verify, order, payment, ticketing | Commitment/Money | **FR-006 policy-gated** (auto ≤ cap, audit log; human > cap). |
| reshop, change, cancel, refund | Aftercare | **FR-006 policy-gated** (auto ≤ cap, audit log; human > cap). |
| disruption alternatives | Aftercare | **FR-006 policy-gated** when it results in a re-book; advisory-only (draft notification) when it does not. |

**The LLM never generates transaction content free-form.** The policy engine constructs the exact Atlas call (offer_id, orderNo, payment_confirmation_id thread per `resources/external_research.md` §3) from structured data; the LLM only proposes which alternative and explains the rationale.

---

## 8. Decision-Learning Log (FR-007)

Every auto-settlement and every above-cap human verdict is written as a **structured, reusable record**:

- `record_id`, `timestamp`, `node_id`, `action` (re-book / change / cancel / refund / notify), `amount_cents`, `cap_cents`, `outcome` (auto_settled | human_approved | human_rejected), `human_verdict` (free text if above cap), `reasoning_trace` (LLM rationale), `model_tier_used`, `atlas_state_refs` (orderNo / payment_confirmation_id), `reusable` (bool — whether this record can train a future threshold).

**Why it matters (rubric + founder lens):** it is the evidence for the Agent Technology score's "bounded autonomy that learns" and the founder-lessons "judgement of today → intelligence of tomorrow" trajectory. It is also the **moat** in the EBMC (a growing corpus of labelled settlement decisions that competitors cannot copy).

---

## 9. Demo Scenario (one family trip, one disruption type, one cascade)

**Trip:** Family of 3 (2 adults + 1 child), leisure.
- **Leg 1 (actionable):** flight PVG → NRT, 4 Sep 2026.
- **Hotel (advisory `[Inference]`):** Tokyo hotel, check-in 4 Sep, check-out 6 Sep. Non-refundable family rate.
- **Leg 2 (actionable):** flight NRT → PVG, 6 Sep 2026 (return). Depends on Leg 1's timely arrival and the hotel checkout.

**Disruption type:** typhoon-induced delay/cancellation of Leg 1, forecast by the ML model (FR-002) from typhoon-season + carrier + route + scheduled-time features.

**Cascade (FR-004):**
1. Leg 1 at risk → agent searches Atlas alternatives (FR-005). Best alternative reroutes via a different carrier / next-day; fare difference **S$30 (≤ S$50 cap)** → **auto-settle** (FR-006) + audit log (FR-007).
2. Hotel node affected (missed check-in window) → agent **drafts a notification** to the hotel (advisory node — never a fake booking). The traveler can send it.
3. Leg 2 affected (return connection timing) → agent searches Atlas alternatives (FR-005). Best alternative is a later return; fare difference **S$120 (> S$50 cap)** → **human approval** surfaced in the UI (FR-008). The traveler approves; the verdict is recorded (FR-007).

**What the 3-minute demo shows:** trip graph → per-leg forecast (Leg 1 high) → cascade (hotel + Leg 2 highlighted) → Leg 1 auto-settled (≤ cap, audit log visible) → Leg 2 human-approved (> cap) → advisory hotel notification drafted → decision log populated → test ticketing confirmed in Atlas Sandbox.

**Node classification (evidence-based, per TODO.md §11 Decision 4):** the `actionable` flag per node is a **working assumption** here — `[Inference]` flights = actionable, hotels/activities = advisory. The authoritative source is `doc/atlas_surface.md` (produced by `tasks/02-setup.md`, running in parallel). **Reconciliation rule:** `doc/SPECS.md` is updated to match `doc/atlas_surface.md` before `tasks/04-agent_core.md` begins. If the audit finds hotels/activities *are* Atlas-actionable, their nodes flip to actionable (the demo scenario otherwise unchanged).

---

## 10. Acceptance Criteria (for this PRD)

- [x] Product name + one-sentence description present (§0).
- [x] ≥6 user stories (US1–US6) and 10 functional requirements (FR-001…FR-010), each with a priority and a demo-scenario trace (§4, §5).
- [x] Settlement policy stated with default cap S$50, configurable, auto ≤ cap with audit log, human approval above cap (§6).
- [x] Decision-learning log defined as a structured, reusable record (§8).
- [x] Demo scenario: one family trip, one disruption type, one cascade (§9).
- [x] Money-changing Atlas actions route through the settlement policy (§7).
- [x] Dependency-graph data model referenced with per-node `actionable` flag (evidence source `doc/atlas_surface.md`); full field-level definition in `doc/SPECS.md`.

*This PRD is the single source of product truth. `doc/SPECS.md` is derived from it and adds nothing beyond its scope.*
