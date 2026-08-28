# TripCascade Test Suite

> **Last updated:** 2026-08-28
> **Suite status:** 83 passed, 1 skipped (real Qwen needs DASHSCOPE_API_KEY)
> **Target:** All acceptance criteria per `doc/SPECS.md` (FR-001 through FR-010)

---

## Quick Start

```bash
# From the repo root:
uv sync                    # install deps + create .venv
cp .env.example .env       # then fill in Sandbox creds
uv run pytest              # run ALL tests
uv run pytest -q           # quiet mode (summary only)
uv run pytest -v           # verbose (each test name)
```

## Prerequisites

- **Python ≥3.11** (the project requires 3.11+)
- **uv** (package manager): `pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Atlas Sandbox credentials** (optional, for live tests): see §4 below
- **DashScope API key** (optional, for real Qwen tests): see §5 below

## Test Structure

```
tests/
├── test_smoke.py              # 3 smoke tests: imports, subpackages, cap consistency
├── test_forecast_inference.py  # 6 forecast tests: output range, variance, unseen carriers, load speed
├── test_agent_core.py         # 26 agent tests: cascade, policy gating, decision log, routing, E2E
├── test_watcher_fc.py         # ~20 watcher tests: FC dispatch, webhook, timer, WSGI, agent client
├── test_acceptance.py         # 28 acceptance tests: one per FR (FR-001 through FR-010)
└── test_e2e_scenario.py       # Standalone E2E scenario script (not pytest; run with `python`)
```

## Running the Tests

### All tests (recommended)

```bash
uv run pytest -v
```

### Acceptance tests only

```bash
uv run pytest tests/test_acceptance.py -v
```

### Agent core tests

```bash
uv run pytest tests/test_agent_core.py -v
```

### End-to-end scenario (standalone script)

```bash
uv run python tests/test_e2e_scenario.py
```

This runs the full demo flow: itinerary load → forecast → threshold breach → cascade → proposed re-plan → human approval → re-book → fare-difference settled → outcome asserted. Uses the deterministic `StubAtlasClient` (no Sandbox needed). Exits 0 = all pass.

### Watcher / FC tests

```bash
uv run pytest tests/test_watcher_fc.py -v
```

### Forecast tests

```bash
uv run pytest tests/test_forecast_inference.py -v
```

---

## 3. Acceptance Test Map (FR → Test)

Every FR in `doc/SPECS.md` maps to at least one test in `tests/test_acceptance.py`. The test `test_fr010_all_frs_have_corresponding_tests` validates this map automatically.

| FR | Spec | Acceptance Test(s) | What It Asserts |
|---|---|---|---|
| FR-001 | S-001 | `test_fr001_graph_construction` | 3 nodes, ≥2 edges, actionable flags, offer_id retained |
| FR-002 | S-002 | `test_fr002_forecast_output_range`, `test_fr002_forecast_heuristic_fallback` | P(disruption) ∈ [0,1]; heuristic fallback works |
| FR-003 | S-003 | `test_fr003_watcher_event_schema`, `test_fr003_make_scripted_event` | DisruptionEvent schema, populate_forecast writes node probs |
| FR-004 | S-004 | `test_fr004_cascade_marks_downstream_nodes` | Cascade from Leg1 → {hotel, Leg2}, slack_minutes computed |
| FR-005 | S-005 | `test_fr005_discovery_returns_offers`, `test_fr005_advisory_node_no_atlas_call` | Offers with offer_id+price; hotel = advisory, no Atlas write |
| FR-006 | S-006 | `test_fr006_auto_settle_under_cap`, `test_fr006_human_required_above_cap`, `test_fr006_human_rejection`, `test_fr006_no_llm_transaction_body` | Auto ≤ cap with audit log; human > cap; LLM never builds call body |
| FR-007 | S-007 | `test_fr007_log_schema_all_fields`, `test_fr007_log_auto_and_human_records` | All SPECS §4.3 fields present; query by node_id works |
| FR-008 | S-008 | `test_fr008_ui_graph_render`, `test_fr008_ui_decision_render`, `test_fr008_ui_decision_log_render`, `test_fr008_ui_scenario_roundtrip` | UI renders graph, forecast, cascade, verdicts, approve/reject, log |
| FR-009 | S-009 | `test_fr009_routing_routine_to_cheap`, `test_fr009_routing_hard_to_max`, `test_fr009_local_fallback` | Routine→cheap, hard→max, fallback exercised |
| FR-010 | S-010 | `test_fr010_harness_detects_failure`, `test_fr010_all_frs_have_corresponding_tests` | Harness detects failures; all FRs have tests |

**Additional cross-cutting tests** (also in `test_acceptance.py`):
- `test_reread_before_write_fare_drift` — StaleStateError when fare changes between proposal and execution
- `test_false_success_empty_orderno` — FalseSuccessError when orderNo is empty despite HTTP 200
- `test_e2e_full_scenario` — Complete E2E flow (auto + advisory + held + approved)

---

## 4. Atlas Sandbox Credentials

For integration tests that hit the **live Atlas Sandbox** (the `atlas-flight` CLI):

```bash
# CLI auth (one-time setup):
atlas-flight auth login
# This opens a browser for OAuth; the token is stored in the macOS keychain.
```

The `test_live_discovery_returns_real_fares` test in `test_agent_core.py` is **skipped** when the CLI is not installed/authed. It runs against the real Sandbox when available.

For REST API tests (webhook, aftercare), set these in `.env`:

```
ATLAS_SANDBOX_ACCESS_KEY=your_key_here
ATLAS_SANDBOX_SECRET_KEY=your_secret_here
ATLAS_SANDBOX_BASE_URL=https://sandbox.atriptech.com
```

See `doc/atlas_surface.md` for the full auth + endpoint map.

---

## 5. Real Qwen (DashScope) Tests

The `test_real_qwen_proposal_backend` test in `test_agent_core.py` is **skipped** by default. To exercise the real Qwen model:

```bash
# In .env:
DASHSCOPE_API_KEY=sk-...
TRIPCASCADE_LLM_BACKEND=dashscope
DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
```

**Important:** Use the international DashScope endpoint (`dashscope-intl.aliyuncs.com`), not the MaaS workspace endpoint (`ws-*.maas.aliyuncs.com`). The workspace endpoint requires per-workspace model deployment and returns `AccessDenied.Unpurchased` on inference. The intl endpoint uses the account-level free quota directly.

Model IDs (verified against the live model catalog):
- `Qwen3.8-Max` → `qwen3.8-max` (HARD tier)
- `Qwen3.7-Plus` / `Qwen-Plus` → `qwen3.7-plus` (ROUTINE tier)

---

## 6. Reproducibility

### From a clean clone

```bash
git clone <repo-url>
cd tripcascade
uv sync                    # installs all deps (pinned in uv.lock)
uv run pytest -q           # 83 passed, 1 skipped (needs key)
```

### Environment

- All Python dependencies are pinned in `pyproject.toml` + `uv.lock`
- `uv sync` produces a reproducible environment
- Tests use the deterministic `StubAtlasClient` by default — no Sandbox needed for the core acceptance suite
- Secrets (`ATLAS_SANDBOX_*`, `DASHSCOPE_API_KEY`) are read from `.env` (gitignored)

### Known skips

- `test_real_qwen_proposal_backend` — skipped unless `DASHSCOPE_API_KEY` is set and `TRIPCASCADE_LLM_BACKEND=dashscope`
- `test_live_discovery_returns_real_fares` — skipped unless `atlas-flight` CLI is installed and authed

---

## 7. Continuous Integration

No CI pipeline is currently configured. The project is hackathon-scoped and built for a single demo.

**To add CI** (recommended post-hackathon):
1. Add a `.github/workflows/ci.yml` that runs `uv run pytest -q` on push/PR
2. Set repository secrets for `DASHSCOPE_API_KEY` if real-Qwen tests are desired
3. The `StubAtlasClient` means no Sandbox credentials are needed for CI

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `uv sync` fails | Python <3.11 | `python3 --version`; install 3.11+ |
| `pytest` not found | `.venv` not activated | `uv run pytest` (auto-activates) |
| Tests fail: "no module named tripcascade" | PYTHONPATH | `uv run` sets it from `pyproject.toml` |
| `test_real_qwen_proposal_backend` fails 403 | Wrong endpoint | Use `dashscope-intl.aliyuncs.com` not `ws-*.maas.aliyuncs.com` |
| Live Sandbox tests skipped | CLI not authed | Run `atlas-flight auth login` once |
| Decision log tests fail | Stale `logs/decision_log.jsonl` | Delete the file; tests create fresh logs via `tmp_path` |