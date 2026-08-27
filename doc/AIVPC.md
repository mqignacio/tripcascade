---
status: draft
created: 2026-08-27
product: TripCascade
canvas: AI-enabled Value Proposition Canvas (AIVPC)
customer: family/leisure traveler (demo persona)
---

# AI-enabled Value Proposition Canvas — TripCascade

The AIVPC is built **sequentially**: Customer Jobs → Pains → Gains → Products & Services → Pain Relievers → Gain Creators. Every block connects to the next; the story flows from the family traveler (this canvas) to the OTA/seller who pays for the outcome (see `doc/EBMC.md`). Trigger questions are from `resources/systems_thinking/aivpc.md`.

**Customer (demo persona):** A parent managing a multi-leg leisure trip for a family of 3 (2 adults + 1 child) — Shanghai → Tokyo and back, with a non-refundable hotel and a return flight that depends on the outbound's timely arrival.

---

## 1. Customer Jobs

*The functional, social, and emotional jobs the customer needs done.*

- **(Functional) Get the family there and back with the trip intact.** The one thing the parent couldn't live without accomplishing: the family departs, stays, and returns on the itinerary they paid for — connections, hotel, and return flight all holding together. *(Trigger Q1, Q4)*
- **(Functional) Protect the non-refundable downstream commitments.** The hotel is a family-rate, non-refundable booking; the return flight is a separate ticket. A disruption to the outbound leg puts both at financial risk. *(Trigger Q2, Q4)*
- **(Functional) Re-plan under pressure when something breaks.** Find an alternative flight, weigh the fare difference, decide fast — a job that surfaces mid-trip, often with a tired child in tow. *(Trigger Q4, Q9 — supporting job across the trip lifespan)*
- **(Social) Be the parent who handled it.** The parent wants to be perceived by their family (and by themselves) as competent and in control of the trip, not stranded and scrambling. *(Trigger Q7)*
- **(Emotional) Travel without low-grade anxiety.** The parent wants to feel that someone competent is watching the trip so they can be present with their family instead of monitoring flight status. *(Trigger Q6, Q8)*

*→ These jobs surface a set of pains (§2) and a set of desired gains (§3).*

---

## 2. Customer Pains

*Negative experiences, emotions, and risks before/during/after the job.*

- **(Cost) Disruptions are expensive.** A missed connection can mean a same-day re-book at peak fares, a forfeited hotel night, a lost activity booking — "too costly in money and effort." *(Trigger Q1)*
- **(Frustration) Reactive tools.** Current travel apps and chatbots act only *after* the airline announces a delay; by then the cheap alternatives are gone. The parent feels one step behind. *(Trigger Q3 — under-performing value propositions)*
- **(Cognitive load) Trips are modeled as lists, not graphs.** When the outbound breaks, the parent has to mentally compute everything downstream that breaks — hotel check-in window, return connection — under time pressure. *(Trigger Q4 — difficulties/challenges)*
- **(Risk) Financial and social risk.** Fear of a big unexpected fare charge, and fear of "losing face" with the family for booking a tight connection that didn't hold. *(Trigger Q5, Q6)*
- **(Sleep) What keeps them awake the night before a trip:** "What if the outbound is cancelled — do I lose the hotel? Do I miss the return?" *(Trigger Q7)*
- **(Mistakes) Deciding wrong under pressure.** Common mistake: panic-rebooking the first expensive option without seeing the full cascade of what else needs to change. *(Trigger Q8)*
- **(Barrier) Trust.** The parent fears handing money decisions to an AI — "what if it books something wrong or expensive without asking me?" *(Trigger Q9)*

*→ The pains define what a great product must relieve (§5) and what gains would delight (§3).*

---

## 3. Customer Gains

*Positive outcomes and benefits the customer expects, needs, or would be delighted by.*

- **(Savings) Pay only the fair fare difference, never a panic premium.** Time, money, and effort saved by re-booking at the right alternative, not the first one found at peak. *(Trigger Q1)*
- **(Quality) A complete re-plan, not a single fix.** The parent expects that if the outbound moves, the hotel and return are handled together — a coherent new plan. *(Trigger Q3)*
- **(Ease) Not having to babysit the trip.** A flatter curve: the agent watches and acts within bounds the parent set, so the parent can be present with the family. *(Trigger Q4)*
- **(Social) Looking like the parent who had it handled.** The trip adjusts smoothly; the family perceives competence. *(Trigger Q5)*
- **(Relief) Sleeping the night before.** Knowing someone competent is watching the forecast and will act — or wake the parent only when it matters. *(Trigger Q7)*
- **(Control) The parent sets the spend bound.** They want a guarantee that small fare diffs are handled automatically and big ones come back to them — adoption is easier when the risk is bounded. *(Trigger Q9)*

*→ These gains are what the product's gain creators must produce (§6).*

---

## 4. Products and Services

*The AI-enabled bundle that creates gains, relieves pains, and gets the job done.*

- **A forecast-driven trip agent** that, for the family's itinerary, runs an ML model on historical on-time data to output P(disruption) per leg *before* the airline announces anything — the proactive differentiator. *(Trigger Q1, Q7)*
- **A dependency-graph model of the trip** (flight legs + hotel + return, as a DAG) that makes every downstream commitment explicit and re-plannable — addressing the "trips are lists" pain. *(Trigger Q2, Q3)*
- **A bounded-autonomy settlement engine** that auto-settles fare differences at or below a parent-set cap (default S$50) with an audit log, and escalates above-cap changes for human approval — the trust/control gain. *(Trigger Q6)*
- **An experiential UI** that shows the trip graph, per-leg forecast, the cascade of what else breaks, the proposed re-plan, the fare-difference summary, and an approve/reject control — making the re-plan-under-pressure job radically easier. *(Trigger Q7)*
- **A decision-learning log** that records every auto-settlement and every human verdict as a reusable record — so the agent gets better over time at the parent's judgement. *(Trigger Q6)*

*→ Each product/service maps to a pain reliever (§5) and a gain creator (§6).*

---

## 5. Pain Relievers

*How the products/services alleviate the specific pains in §2.*

- **(Cost)** Forecast-driven re-planning books the right alternative *before* peak fares hit; the parent pays the fair fare difference, not a panic premium. *(Relieves P1)*
- **(Frustration)** Proactive forecast beats the airline's announcement — the parent is one step *ahead*. *(Relieves P2)*
- **(Cognitive load)** The dependency graph computes the full cascade automatically — the parent sees "here's everything that breaks," not a mental puzzle. *(Relieves P3)*
- **(Risk)** Bounded autonomy with an audit log bounds the financial risk to the cap; big charges always come back to the human. *(Relieves P4, P6)*
- **(Sleep)** A scheduled forecast-poll watches the trip so the parent doesn't have to; it escalates only above-cap changes. *(Relieves P5)*
- **(Mistakes)** The agent presents the complete re-plan + total cost, not the first panic option — limiting reactive mistakes. *(Relieves P7)*
- **(Barrier/Trust)** The LLM never free-forms transaction content; a deterministic policy engine builds every Atlas call from structured data — removing the "what if it books something wrong" fear. *(Relieves P8)*

*→ The same capabilities also create the gains (§6).*

---

## 6. Gain Creators

*How the products/services produce the outcomes in §3.*

- **(Savings)** Auto-settling within the cap at the right alternative produces the fair-fare-difference outcome the parent expects. *(Creates G1)*
- **(Quality)** The cascade re-plans every affected downstream leg together — a coherent new plan, not a patch. *(Creates G2)*
- **(Ease)** The agent watches and acts within bounds; the parent is present with the family, not on hold with the airline. *(Creates G3)*
- **(Social)** A smooth, bounded adjustment makes the parent look — and feel — in control. *(Creates G4)*
- **(Relief)** Pre-trip, the parent sees a low-risk forecast and knows the watcher is on; they sleep. *(Creates G5)*
- **(Control)** The configurable cap (default S$50) is the parent's guarantee: small = handled, big = asked. *(Creates G6)*
- **(Surprise/delight)** The decision-learning log means the agent improves at the parent's own judgement over repeated trips — "it learns how I decide." *(Trigger Q7 — fulfilling a desire)*

---

## Connection to the Business Model (EBMC)

The traveler's pains (§2) — especially the cost pains (P1, P4) — are the **same costs travel sellers/OTAs absorb today** when a guaranteed booking breaks. The EBMC (`doc/EBMC.md`) prices that protected-booking **outcome**, not the tool: OTAs pay a per-protected-booking fee, and the traveler is the protected end-user. The decision-learning log (§4) is the **moat** — a growing corpus of labelled settlement decisions that makes TripCascade cheaper and better over time, hard to copy.
