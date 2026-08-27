---
status: draft
created: 2026-08-27
product: TripCascade
canvas: Exponential Business Model Canvas (EBMC)
lens: founder_lessons.md — price the outcome, not the tool
---

# Exponential Business Model Canvas — TripCascade

The EBMC is built **sequentially**: Customer Segment → Value Proposition → Channel → Customer Relationships → Revenue Streams → Key Activities → Key Resources → Key Partners → Cost Structure. Every block connects to the next. Trigger structure from `resources/systems_thinking/ebmc.md`; **pricing lens from `resources/founder_lessons.md`**: TripCascade prices the **outcome** (a protected booking), not the tool — a **per-protected-booking fee paid by travel sellers/OTAs** who eat disruption costs today, not a traveler subscription. The 1:6 tool-vs-outcome ratio is the frame.

---

## 1. Customer Segment

**Type: Multi-sided platform (Producers + Users).**

- **Paying side — travel sellers / OTAs** who guarantee bookings and absorb disruption costs today (re-book fees, forfeited hotel commissions, customer-service load, chargebacks). They are the ones who eat the $6-outcome cost and will pay to not. *(Exponential idea: solve a problem for the masses — the mass of leisure bookings that break.)*
- **Protected side — family/leisure travelers** (the demo persona in `doc/AIVPC.md`). They are the end-users whose trips are protected; they do not pay TripCascade directly. Their pains (cost, frustration, cognitive load) are the seller's cost.
- **Niche → mass:** start with the LCC leisure-trip segment (Atlas's 140+ LCC content), which has the highest disruption rate and the thinnest margins — the segment where the outcome is most expensive for the seller.

*→ The value proposition (§2) is the protected-booking outcome for both sides.*

---

## 2. Value Proposition

**Type: Performance + Price (outcome-priced).**

- **For the OTA/seller:** "Every booking you sell is protected against disruption cascades — we forecast, cascade, and re-plan every downstream leg, settling fare differences within a bound and escalating above it. You pay per protected booking, not per tool seat." This is the **outcome** the seller currently staffs humans to handle (the $6) — TripCascade sells the closed-loop result. *(Founder lesson: sell the outcome, not the tool; software-like margins masquerading as a service.)*
- **For the traveler (protected side):** the AIVPC bundle (`doc/AIVPC.md` §4) — a forecast-driven agent, dependency-graph cascade, bounded-autonomy settlement, experiential UI, decision-learning log. The traveler gets a trip that holds together; the seller gets a protected booking.

*→ The value prop reaches both sides via the channels (§3).*

---

## 3. Channel

**Types: Web/App-store + Partners' stores. Multi-modal and social.**

- **B2B API into the OTA booking flow** (primary): TripCascade embeds at checkout — "add disruption protection" — as a per-booking fee line item. This is the partner's store. The OTA surfaces TripCascade where the booking is made.
- **Traveler-facing experiential app** (demo surface / protected side): the UI from `doc/PRD.md` FR-008 — shows the trip graph, forecast, cascade, approve/reject. This is the web/app-store channel that delivers the protected outcome to the traveler.
- **Social/multi-modal:** the traveler shares a protected-trip card (the experiential UI is shareable), seeding organic demand on the protected side that pulls sellers on the paying side.

*→ The channel carries the relationship type (§4).*

---

## 4. Customer Relationships

**Types: Automated services + Self-service.**

- **Automated services** for the paying seller: per-booking protection runs without seller intervention — forecast, cascade, auto-settle within cap, escalate above. The seller sees a dashboard of protected bookings and the decision log. *(Exponential idea: use automated and self-service methods.)*
- **Self-service** for the traveler: the experiential UI lets the traveler approve/reject above-cap changes and view their decision history — no human agent required for the routine 80%.
- **Human-in-the-loop (shrinking):** above-cap settlements still route to a human verdict (the traveler, or the seller's agent). Per the founder lesson, "you start with lots of humans, little AI; you end with lots of AI, little humans" — the decision-learning log (§7) is the mechanism that shifts the bottleneck over time. Judgement of today → intelligence of tomorrow.

*→ The relationship defines what we charge for (§5).*

---

## 5. Revenue Streams

**Type: Usage fee — per-protected-booking.**

- **Per-protected-booking fee paid by the seller/OTA**, added at checkout as a line item (mirrors how travel insurance is sold, but priced as an outcome, not a policy). This is the **outcome pricing** the founder lesson prescribes: the seller pays for the protected result, not for a tool subscription.
- **Not a traveler subscription.** The traveler never pays TripCascade directly; the fee is embedded in the booking (seller-funded, like how sellers absorb disruption costs today — now bounded and predictable).
- **Recurring/predictable:** because the fee attaches to every booking, revenue scales with booking volume without per-customer acquisition cost — "revenues and customer base that can easily grow and scale without a lot of additional resources." *(EBMC Important Lessons.)*
- **Stretch (not in demo scope):** a premium tier for sellers wanting lower caps / broader autonomy, and a revenue-share on the decision-learning log as a data asset.

*→ The revenue funds the key activities (§6).*

---

## 6. Key Activities

**Types: Problem solving + Platform/network. Automated and scalable.**

- **ML disruption forecasting** — train and serve the XGBoost model on historical on-time data (`tasks/03-data_ml.md`); feature alignment with Atlas itineraries.
- **Dependency-graph cascade re-planning** — the core technical differentiator (the Level-4 benchmark): model the trip as a DAG, compute the cascade, re-plan every affected downstream leg via Atlas.
- **Bounded-autonomy policy engine** — deterministic settlement (auto ≤ cap, audit log; human > cap); the LLM proposes, the engine executes.
- **Decision-learning loop** — capture every settlement and human verdict as a reusable record; retrain thresholds over time. *(This is the activity that turns the service into a compounding asset.)*
- **Atlas tool-layer integration** — Discovery (read-only) + policy-gated Commitment/Money/Aftercare, in Sandbox for the demo.
- **Experiential UI** — the protected-side delivery surface.

*→ These activities require the key resources (§7).*

---

## 7. Key Resources

**Types: Intellectual + Human.**

- **The decision-learning log — the moat (intellectual).** A growing corpus of labelled settlement decisions (amount, cap, outcome, human verdict, reasoning). Per the founder lesson, "judgement of today is the intelligence of tomorrow" — this corpus is what competitors cannot copy and what shifts the human/AI ratio over time. It is hard to emulate for the next couple of years. *(EBMC Important Lessons: key resources that can't easily be copied.)*
- **The ML forecast model (intellectual):** trained on historical on-time data; improves as the decision log grows.
- **Atlas/ATRIP integration (intellectual):** the verified Sandbox surface (`doc/atlas_surface.md`) and the `routingIdentifier→offer_id→sessionId→orderNo→payment_confirmation_id` state thread.
- **Brand (intellectual):** "TripCascade" — the protected-booking outcome brand.
- **Human judgement (human, shrinking):** above-cap verdicts from travelers and seller agents — the labelled data source for the log.
- **Compute (physical/financial):** Alibaba Cloud Function Compute (Operating-Scale evidence) + Qwen model tiers.

*→ Resources are sustained by the key partners (§8).*

---

## 8. Key Partners

**Types: Acquisition of particular resources + Reduction of risk.**

- **Atlas / ATRIP** — the flight content + transactional substrate (140+ LCCs); the action layer. Sandbox for dev/test. *(Reduction of risk: the canonical booking flow.)*
- **Alibaba Cloud** — compute (Function Compute for the Watcher; Model Studio/Bailian for Qwen). *(The Operating-Scale rubric evidence.)*
- **Qwen (open-weight)** — the model backbone; open weights enable a local fallback so the core flow is not solely on paid top-tier (Cost Controllability) and aligns with Mike's open-weight mission.
- **Qoder** — the build surface (≥80% eligibility gate) and the spec-driven Quest loop.
- **OTAs / travel sellers (distribution)** — the paying-side channel; they embed TripCascade at checkout and supply the booking volume that scales revenue.

*→ Partners and resources define the cost structure (§9).*

---

## 9. Cost Structure

**Types: Variable costs (with a fixed R&D base). Significantly more effective than competitors'.**

- **Model inference (variable, tiered):** routine work on cheap Qwen / local open-weight; hard reasoning (cascade, fare logic) on Qwen3.8-Max. Tiered routing keeps the cost per protected booking low — the Cost Controllability evidence.
- **Atlas API usage (variable):** Discovery is read-only and cacheable; Commitment/Money/Aftercare calls are bounded by the policy (only auto-settle ≤ cap executes without humans).
- **Cloud compute (low fixed):** Function Compute serverless — pay-per-invocation for the Watcher; scales with booking volume.
- **Human review (variable, shrinking):** above-cap verdicts require human time today; the decision-learning log reduces this share over time (lots of humans, little AI → lots of AI, little humans).
- **Target:** a cost structure "significantly more effective than competitors by a factor of two" *(EBMC Important Lessons)* — because the forecast prevents the expensive cascade (the $6 outcome cost) rather than staffing humans to react to it.

---

## Story / Flow (one paragraph)

Leisure travelers (protected side) have trips that break in cascades — the same cascades OTAs/sellers (paying side) absorb as cost today (**§1 Customer Segment**). TripCascade's value proposition is the **protected booking outcome**: forecast, cascade-re-plan, and settle within a bound (**§2 Value Prop**), delivered through a B2B checkout API + a traveler-facing app (**§3 Channel**) as automated/self-service with a shrinking human loop (**§4 Relationships**). Sellers pay a **per-protected-booking fee** — outcome, not tool (**§5 Revenue**) — funding the forecast, cascade, policy engine, and decision-learning activities (**§6 Key Activities**). The compounding asset is the **decision-learning log** — today's human judgement becoming tomorrow's model intelligence, a moat competitors can't copy (**§7 Key Resources**) — sustained by Atlas, Alibaba Cloud, Qwen, Qoder, and OTA partners (**§8 Key Partners**) at a cost structure that is cheaper than staffing humans to react (**§9 Cost Structure**). The AIVPC (`doc/AIVPC.md`) traveler pains are the EBMC seller costs; the EBMC outcome pricing is the AIVPC products brought to market.
