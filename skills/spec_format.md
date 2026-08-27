# Spec Format — TripCascade

Shared by **pi** and **Qoder**. The spec-driven loop the deck rewards ("Example of Specs-Driven Development"): **PRD -> SPEC -> impl -> verify**. Source of truth: `doc/PRD.md` (product truth) and `doc/SPECS.md` (derived, testable specs).

## 1. The flow

1. **PRD** (`doc/PRD.md`) — problem, target user, scope/non-goals, user stories (US1-US6), functional requirements (FR-001..FR-010) with priority + demo trace, settlement policy, demo scenario.
2. **SPEC** (`doc/SPECS.md`) — every spec item **testable**, derived from a PRD FR, ordered P0 -> P1. Structure: Overview -> Scope & Non-Goals -> Numbered Specs (S-NNN / FR-NNN) -> Data Model -> Interfaces -> Open Questions.
3. **Impl** — write code against the spec; one concern per commit.
4. **Verify** — assert the spec's "Then" against a **real outcome** (Atlas Sandbox post-state, not HTTP 200).

## 2. Spec item anatomy

Every spec item carries, verbatim:

- **ID:** `S-NNN / FR-NNN` + **Priority** (P0 demo-critical; P1 rubric-relevant) + **User Story** cross-ref.
- **Given** — the starting state (e.g., "a booked itinerary with P(disruption) per leg").
- **When** — the trigger (e.g., "a scheduled forecast-poll runs and a leg's P(disruption) exceeds the threshold").
- **Then** — the observable post-state (e.g., "the Watcher emits a `disruption_likely` event carrying `{node_id, p_disruption, threshold, ts}`").
- **Verification** — how the "Then" is asserted against a real outcome.

## 3. Rules

- **Nothing beyond the PRD's scope.** SPECS adds testability, not features.
- **Every Commitment/Money/Aftercare Atlas action spec routes through the settlement policy** (FR-006: auto <= cap + audit log; human > cap). Discovery (search) is ungated.
- **Cross-reference everything:** FR ID, user story, and (for Atlas actions) the `doc/atlas_surface.md` evidence section.
- **Open Questions** are tracked in `doc/SPECS.md` §6 with an owner/next-task. When answered, mark RESOLVED with a date + pointer to the evidence doc (see how #1/#2/#3 were resolved 2026-08-27).
- **Reconciliation:** if a parallel evidence doc (e.g., `doc/atlas_surface.md`) disagrees with a SPECS assumption, update SPECS **before** the next implementation task begins (per TODO.md §11 Decision 4).

## 4. Given/When/Then example (from S-006 / FR-006)

> **Given** a proposed re-plan with `fare_difference_cents` and the configured cap (default 5000 cents)
> **When** the deterministic policy engine evaluates the settlement
> **Then** if `fare_difference_cents <= cap_cents` -> auto-execute + audit-log (`outcome=auto_settled`); if `>` -> hold, surface to UI, on verdict write (`outcome=human_approved|human_rejected`). The LLM never builds the Atlas call body.
> **Verification:** Leg 1 diff 3000 -> `auto_settle=True`; Leg 2 diff 12000 -> `human_gate=True`. Assert no LLM-generated transaction body reaches the Atlas tool layer.
