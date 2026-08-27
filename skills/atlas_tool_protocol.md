# Atlas Tool Protocol — TripCascade

Shared by **pi** and **Qoder**. Load before writing any Atlas call. Evidence base: `doc/atlas_surface.md`. This protocol is the operationalization of `doc/PRD.md` §7 (Atlas Action Classification) and `doc/SPECS.md` §5.1.

## 1. The four capability groups

| Group | Atlas actions | Gating |
|---|---|---|
| **Discovery** | search, offer list/verify, price confirm, baggage/seat list | **Read-only, ungated** — safe to hammer in Sandbox (cache results). |
| **Commitment** | order create, baggage/seat select | **FR-006 policy-gated** (auto <= cap + audit log; human > cap). |
| **Money** | order pay | **FR-006 policy-gated.** |
| **Aftercare** | order status (ticket query), void, refund, cancel, schedule-change refund | **FR-006 policy-gated** when it results in a re-book; advisory-only (draft notification) when it does not. |

## 2. The substrate (hybrid — see `doc/atlas_surface.md` §6)

- **CLI (booking flow):** `atlas-flight search | offer verify | order create | order pay | order status` — all emit `--json`; call via `subprocess` + `json.loads`. Fastest path; no HTTP/JWT management (the CLI handles OAuth -> JWT -> secure store).
- **REST (webhook/incident + aftercare):** `POST /event/getPageList.do`, `updateWebhookURL.do`, void/refund/cancel — auth via `x-atlas-client-id`/`x-atlas-client-secret` from `.env` (read in-process, **never** as CLI flags).

## 3. The state thread (preserve on graph nodes + decision records)

`search_id` -> `offer_id` -> `booking_id` (verify) -> `orderNo` (order) -> `confirmation_id` (pay) -> `ticketNos` (order status query). Never lose this thread; it is the evidence the eval harness asserts.

## 4. Operational rules

1. **Discovery is read-only — hammer freely, but cache.** Re-running `search` for the same O&D/date within the offer `expire_time` is wasteful. Cache by `(origin, destination, depart, adults, children)`.
2. **Re-read the world before every write.** Before `order create`, re-`verify` the offer (price may have changed -> `priceChange` array in the verify response). Before `order pay`, confirm the order is unpaid (`order status`). Never act on stale state.
3. **The policy engine builds the Atlas call body, never the LLM.** The LLM proposes *which* alternative and explains the rationale; the deterministic policy engine constructs the exact call from `offer_id`/`orderNo`/`amount_cents` and decides auto-settle vs. human-gate. (The rubric's x0.5 "misuse" penalty targets free-form generation in transactional flows; bounded, audited autonomy is not that.)
4. **Assert real outcomes, not HTTP 200.** After `order create` -> assert non-empty `orderNo`. After `order pay` -> assert `confirmation_id`. After ticketing -> assert `ticketNos` non-empty. A 200 with an empty/error body is a **fail**.
5. **Money steps are bounded.** `fare_difference_cents <= SETTLEMENT_CAP_CENTS` (default 5000) -> auto-execute + audit-log record (`outcome=auto_settled`). `>` -> hold, surface to UI, execute only on explicit human approval; record `outcome=human_approved|human_rejected`. Every record is `reusable=true` (the decision-learning log, FR-007).
6. **Hotels/activities/transfers are advisory-only.** Atlas is flights + ancillaries (`doc/atlas_surface.md` §4). For advisory nodes: draft a notification + impact analysis; **never** issue a Commitment/Money/Aftercare call.
7. **Webhook delivery is best-effort.** The scheduled forecast-poll is the guaranteed P0 Watcher trigger; webhook/incident events (`abnormal.cancelled`, `order.schedulechange`, `email.schedulechange`) are a complementary P1 signal. Always reconcile via `order status` for final confirmation.

## 5. Secrets

`ATLAS_SANDBOX_ACCESS_KEY` / `ATLAS_SANDBOX_SECRET_KEY` (REST client-id/secret) live in `.env`, read via `os.environ`. Production keys stay blank in dev (Sandbox only). Never echo, never CLI-flag.
