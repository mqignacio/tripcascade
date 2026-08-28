# TripCascade

> An agentic AI that **forecasts flight disruption with machine learning**, models your trip as a **dependency graph**, **cascades** the forecast into re-planning every affected downstream leg via the Atlas API, and **settles fare differences under bounded autonomy** — auto-settling at or below a pre-authorized cap with an audit log while escalating above-cap changes for human approval.

**Hackathon:** [Alibaba Cloud × Atlas Agentic AI Hackathon](https://www.alibabacloud.com/en/solutions/agentic-ai-hackathon) · Deadline 30 Aug 2026, 23:59 SGT.
**Team:** Solo (Mike). **Build surface:** Qoder (≥88% of core functionality). **Atlas environment:** Sandbox only.

---

## The Problem

A family flying PVG→NRT→PVG with a Tokyo hotel stopover faces a typhoon-induced flight disruption. Today, they scramble: call the airline, re-book the return, re-book the hotel, pray the fare difference isn't ruinous. TripCascade does this **proactively** — before the airline notifies you — and **autonomously** within a policy you set.

## The Solution — One Demo Scenario

1. **Forecast** disruption risk per leg (XGBoost on 3.46M historical flights).
2. **Detect** a threshold breach — the model flags PVG→NRT at elevated risk (typhoon season).
3. **Cascade** — the dependency graph propagates: Leg 1 disrupted → hotel affected → Leg 2 affected.
4. **Re-plan** — Discovery searches alternatives; the LLM proposes the best option.
5. **Settle** — the policy engine auto-executes the re-book (≤ S$50 cap with audit log) for Leg 1, and holds Leg 2 for human approval (S$120 > cap).
6. **Learn** — every decision is logged as a structured, reusable record in the **decision-learning log** — today's human judgement becomes tomorrow's threshold.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        TripCascade Agent                           │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────────────┐   │
│  │ Forecast  │  │    Graph     │  │     Orchestrator          │   │
│  │  (XGBoost)│  │   (DAG)     │  │  ┌───────────────────┐   │   │
│  │          │  │              │  │  │  Policy Engine      │   │   │
│  │ P(0.82) │──▶│ leg1→hotel→│──▶│  │  auto ≤ cap        │   │   │
│  │          │  │      leg2    │  │  │  human > cap        │   │   │
│  └──────────┘  └──────────────┘  │  │  re-read before    │   │   │
│                                   │  │    write            │   │   │
│  ┌──────────┐  ┌──────────────┐  │  │  assert post-state  │   │   │
│  │  Router  │  │    LLM       │  │  └───────────────────┘   │   │
│  │routine→  │  │  (Qwen3.8-Max)│  │  ┌───────────────────┐   │   │
│  │  cheap   │  │  proposes    │──▶│  │ Decision Log      │   │   │
│  │hard→max  │  │  alternative │  │  │ (auto_settled,     │   │   │
│  └──────────┘  └──────────────┘  │  │  human_approved)   │   │   │
│                                   │  └───────────────────┘   │   │
│  ┌──────────┐  ┌──────────────┐  └───────────────────────────┘   │
│  │   UI     │  │  Atlas Tool  │                                    │
│  │ (Gradio) │──│  Layer       │──▶ Atlas Sandbox                   │
│  │          │  │ (CLI+REST)   │    (search→verify→order→pay)      │
│  └──────────┘  └──────────────┘                                    │
└─────────────────────────────────────────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │  Watcher     │ (Alibaba Cloud Function Compute)
                    │  (poll +     │
                    │   webhook)   │
                    └─────────────┘
```

---

## What Makes TripCascade Different

| Feature | This | Typical |
|---|---|---|
| **Trigger** | ML forecast *before* the airline notifies | Reactive: airline calls you |
| **Cascade** | DAG propagation (hotel, return leg) | Single-leg re-book only |
| **Settlement** | Bounded autonomy (auto ≤ cap, audit-logged; human > cap) | Manual phone call |
| **Learning** | Every decision → reusable training record | No feedback loop |
| **Model routing** | Cheap Qwen for routine, Qwen3.8-Max for hard reasoning | One model for everything |

---

## Screenshots

> *(Add UI screenshots here before submission. The Gradio UI shows: trip graph, per-leg P(disruption), affected nodes highlighted, re-plan + fare-difference summary, Approve/Reject controls, decision-learning log.)*

---

## Test Suite

83 passing tests (1 skipped without API key). Every FR in `doc/SPECS.md` has a corresponding acceptance test asserting real-world outcomes, not just HTTP status codes.

```bash
uv sync              # install deps
uv run pytest -q     # run all tests
uv run python tests/test_e2e_scenario.py  # standalone E2E demo flow
```

See **[`doc/README.md`](doc/README.md)** for the full test suite documentation: FR-to-test map, Sandbox credentials, troubleshooting.

---

## Folder Map

```
src/tripcascade/         package root
  graph/                 dependency-graph DAG + cascade propagation
  forecast/              ML disruption forecast (inference from task 03)
  agent/                 orchestrator + policy engine + model routing
  atlas_tools/           Atlas CLI + REST wrappers
  ui/                    experiential Gradio interface
  watcher/               disruption watcher (poll + webhook)
doc/                     PRD, SPECS, AIVPC, EBMC, atlas_surface, test docs, deploy SOP
tests/                   pytest acceptance + smoke tests
assets/                  demo seed (real Sandbox rehearsal data)
scripts/                standalone scripts (demo, smoke test)
deploy/                 Alibaba Cloud Function Compute packaging
```

---

## Setup

```bash
git clone <repo-url>
cd tripcascade
uv sync
cp .env.example .env        # fill in credentials (see doc/atlas_surface.md)
uv run pytest -q            # 83 passed, 1 skipped
uv run python -m tripcascade.ui.app  # launch the UI (http://127.0.0.1:7860)
```

---

## Built With

- **Qoder** — 88.3% of core functionality (graph, forecast, agent, UI, cloud deploy)
- **Qwen3.8-Max** / **Qwen3.7-Plus** — model-tier routing (DashScope)
- **Atlas Flight Booking Skill** / **ATRIP REST** — Sandbox booking flow
- **XGBoost** — disruption forecast on US DOT BTS (3.46M flights)
- **Alibaba Cloud Function Compute** — serverless watcher (ap-southeast-1)
- **Gradio** — experiential UI
- **Pydantic v2** — data models and schema validation

## Limitations

- Sandbox only — no real money moves
- Hotels/activities/transfers are advisory-only (Atlas = flights + ancillaries)
- Forecast trained on public on-time data with route-generalization validation
- Single trip, single disruption type, single cascade (demoable core)

---

*Alibaba Cloud × Atlas Agentic AI Hackathon · Built by Mike · Singapore, August 2026*