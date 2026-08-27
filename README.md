# TripCascade

> An agentic AI that forecasts a flight disruption with machine learning on historical on-time data, models the trip as a dependency graph, cascades the forecast into re-planning every affected downstream leg via the Atlas API, and settles fare differences under bounded autonomy — auto-settling at or below a pre-authorized cap with an audit log while escalating above-cap changes for human approval.

**Hackathon:** Alibaba Cloud x Atlas Agentic AI Hackathon · Deadline 30 Aug 2026, 23:59 SGT.
**Build surface:** Qoder (>=80%). **Atlas environment:** Sandbox only.

## Architecture (components)

1. **Dependency Graph** (`src/tripcascade/graph/`) — itinerary as a DAG; nodes carry temporal/booking constraints and an evidence-based `actionable` flag (flights actionable; hotels/activities advisory). See `doc/atlas_surface.md`.
2. **Disruption Forecast** (`src/tripcascade/forecast/`) — XGBoost classifier on historical on-time data; outputs P(disruption) per leg. (Trained in `tasks/03-data_ml.md`.)
3. **Disruption Watcher** (`src/tripcascade/watcher/`) — scheduled forecast-poll (P0) + Atlas webhook/incident events (P1 stretch) -> emits `disruption_likely` events.
4. **Agent Orchestrator** (`src/tripcascade/agent/`) — receives disruption event -> computes cascade -> calls Atlas tools -> routes through the policy engine. Model-tier routing (cheap Qwen routine, Qwen3.8-Max hard, local fallback).
5. **Atlas Tool Layer** (`src/tripcascade/atlas_tools/`) — hybrid substrate: `atlas-flight` CLI (subprocess + `--json`) for the booking flow; REST (`x-atlas-client-id`/`secret` from `.env`) for webhook/incident + aftercare. See `doc/atlas_surface.md`.
6. **Experiential UI** (`src/tripcascade/ui/`) — trip graph, per-leg forecast, cascade, proposed re-plan, fare-difference summary, approve/reject, decision log.

**Settlement policy (FR-006):** every Commitment/Money/Aftercare Atlas action routes through a deterministic policy engine — auto-settle <= cap (default S$50 = 5000 cents) with audit log; human approval above cap. The LLM never generates transaction content free-form.

## Folder map

```
src/tripcascade/   package root
  graph/           dependency-graph DAG + cascade computation
  forecast/        ML disruption forecast (inference fn from task 03)
  agent/           orchestrator + policy engine + model routing
  atlas_tools/     Atlas CLI + REST wrappers (Discovery read-only; Commitment/Money/Aftercare policy-gated)
  ui/              experiential interface
  watcher/         disruption watcher (poll + webhook/incident)
doc/               PRD, SPECS, AIVPC, EBMC, atlas_surface (source of truth)
skills/           shared pi<->Qoder instruction packs
tests/            pytest acceptance + smoke tests
assets/           demo seed, plots, supporting files
scripts/          standalone scripts (training, eval, data)
```

## Setup

```bash
# Python deps (uv)
uv sync                       # creates .venv, installs locked deps
cp .env.example .env         # then fill in Sandbox creds (never commit .env)
uv run pytest -q             # smoke tests
```

## Atlas Sandbox credentials

Copy `.env.example` to `.env` and fill in your ATRIP Sandbox REST credentials (`ATLAS_SANDBOX_ACCESS_KEY` / `ATLAS_SANDBOX_SECRET_KEY`, generated in ATRIP -> My Profile). The `atlas-flight` CLI uses a separate OAuth flow (`atlas-flight auth login`). See `doc/atlas_surface.md` for the full auth + endpoint map.

## Limitations

- Sandbox only — no real money moves.
- Hotels/activities/transfers are advisory-only (Atlas is flights + ancillaries; see `doc/atlas_surface.md` §4).
- Forecast trained on public on-time data (BTS/Kaggle) with route-generalization validation; the Atlas curated dataset provides itineraries, not delay labels.
