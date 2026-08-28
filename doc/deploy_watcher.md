# TripCascade Disruption Watcher — Deploy SOP

> **Target:** Alibaba Cloud Function Compute (serverless, Python 3.12, HTTP + Timer triggers)
> **Product:** TripCascade · **Sprint:** 05-cloud_deploy · **Hackathon:** Alibaba Cloud × Atlas Agentic AI

**TL;DR:** one FC function (two triggers — Timer P0 + HTTP P1), Python 3.12, xgboost+sklearn forecast packaged in, HTTP POSTs disruption events to the agent. 4 steps: build package → configure → deploy → verify.

---

## 1. Prerequisites

### 1.1 You need

| Resource | How to get it | Notes |
|---|---|---|
| **Alibaba Cloud account** with Function Compute | Alibaba Cloud console → Function Compute → activate service | Free tier available; quota note in §6.1 |
| **Alibaba Cloud AK/SK** (Access Key) | RAM console → create a RAM user with `AliyunFCFullAccess` policy → generate AK/SK | Never commit AK/SK — set via `s config` or console env vars. The agent does NOT have these. |
| **Serverless Devs (`s`) CLI** OR console access | `npm i -g @serverless-devs/s` (recommended) **or** deploy via the console web UI (§3.2) | The `s.yaml` in this repo assumes `s`. Console path = manual upload + config. |
| **Atlas Sandbox REST creds** (for P1 webhook ingest + incident poll) | ATRIP → My Profile → Sandbox credentials | Already in `.env` as `ATLAS_SANDBOX_ACCESS_KEY` / `ATLAS_SANDBOX_SECRET_KEY`. Set as FC env vars. |
| **Agent HTTP service URL** | Deployed as a second FC function (Option A, recommended; §5.1) OR a local Mac mini + tunnel (§5.2) | The smoke test (§4) does NOT need this — it runs the agent locally. The live deploy needs a reachable URL for the `AGENT_ENDPOINT_URL` env var. |
| **Tripcascade repo** | `git clone git@github.com:mqignacio/tripcascade.git` | The watcher code is in this repo. |

### 1.2 RACI (Roles)

| Role | Who | Responsibility |
|---|---|---|
| **Accountable** — live deploy, env vars, webhook registration, quota verification, demo recording | **Mike** | Owns the Alibaba Cloud account; must provide AK/SK + run `s deploy` + verify |
| **Responsible** — function code, packaging, SOP doc, local smoke test | **Agent (pi)** | Built `src/tripcascade/watcher/` + `deploy/fc_watcher/` + `scripts/smoke_test_cloud.py`; wrote this SOP |
| **Consulted** — FC runtime specifics, free-tier quotas, deploy config validation | Alibaba Cloud docs + FC console | [Inference] until Mike verifies in the console (§6.1) |
| **Informed** — demo recording, Qoder eligibility, eval harness | Mike + tasks/07 + tasks/06 | This task only covers the Watcher deploy; the full demo is task 07 |

### 1.3 Process map

```
┌─────────────────────────────────────────────────────────┐
│                TRIPCASCADE WATCHER                      │
│           Alibaba Cloud Function Compute               │
│                                                        │
│  ┌──────────────┐      ┌──────────────────┐           │
│  │ Timer trigger│      │  HTTP trigger    │           │
│  │ (every 15m) │      │  GET /health     │           │
│  │             │      │  POST /webhook   │           │
│  └──────┬──────┘      └───────┬──────────┘           │
│         │                     │                        │
│         v                     v                        │
│  ┌───────────────────────────────────────┐             │
│  │  dispatch(trigger, payload)           │             │
│  │  - Timer: load demo itinerary       │             │
│  │  - run predict_disruption_prob()    │             │
│  │  - if P >= threshold → event        │             │
│  │  - POST /disruption to agent        │             │
│  │  - Webhook: validate + translate     │             │
│  └──────────────────────┬──────────────┘             │
│                         │                            │
└─────────────────────────┼────────────────────────────┘
                          │ HTTP POST
                          v
┌─────────────────────────────────────────┐
│        AGENT HTTP SERVICE                │
│  (second FC function OR local+tunnel)    │
│                                         │
│  POST /disruption                        │
│  Orchestrator.handle_disruption()        │
│  → cascade → discovery → propose         │
│  → policy: auto (≤ cap) or hold (> cap) │
│  → return re-plan JSON                  │
└─────────────────────────────────────────┘
```

---

## 2. Configure

### 2.1 Environment variables

Set these in the FC console (Function Compute → Services → `tripcascade-watcher` → Functions → `watcher` → Environment variables) OR in `s.yaml` under `function.environmentVariables`. **Never commit real values.**

| Variable | Required | Default | Notes |
|---|---|---|---|
| `WATCHER_DEMO_MODE` | yes (demo) | `"1"` | `"1"` injects the scripted leg1 event (P=0.82). Set `"0"` for production. |
| `AGENT_ENDPOINT_URL` | yes | — | The agent HTTP service URL (e.g., `https://tripcascade-agent-<id>.fc.aliyuncs.com`). |
| `ATLAS_SANDBOX_ACCESS_KEY` | yes (P1 webhook) | — | From `.env` → `ATLAS_SANDBOX_ACCESS_KEY`. For webhook validation + incident poll. |
| `ATLAS_SANDBOX_SECRET_KEY` | yes (P1 webhook) | — | From `.env` → `ATLAS_SANDBOX_SECRET_KEY`. |
| `ATLAS_SANDBOX_BASE_URL` | no | `https://sandbox.atriptech.com` | ATRIP Sandbox REST base URL. |
| `ATLAS_INCIDENT_PATH` | no | `/event/getPageList.do` | Incident poll endpoint. |
| `ALERT_THRESHOLD` | no | `0.35` | From forecast artifacts (`forecast/metrics.json`). |

### 2.2 Serverless Devs (`s`) credentials

```bash
# Install (one-time):
npm i -g @serverless-devs/s

# Configure credentials (one-time):
s config add --AccountID <alibaba-cloud-account-id> \
            --AccessKeyID <ak> \
            --AccessKeySecret <sk>
```

The `s.yaml` in `deploy/fc_watcher/` references `access: default` — uses the `default` credential profile.

---

## 3. Deploy

### 3.1 via Serverless Devs CLI (recommended)

```bash
# 1. Build the deploy package (copies src/tripcascade + assets)
cd /path/to/tripcascade
bash deploy/fc_watcher/build_package.sh

# 2. Deploy
s deploy -t deploy/fc_watcher/s.yaml

# 3. Set env vars (if not in s.yaml)
# FC console → Functions → watcher → Environment variables
```

### 3.2 via Alibaba Cloud Console (fallback)

If `s` CLI is unavailable:

1. Console → **Function Compute** → **Services** → **Create Service** → name: `tripcascade-watcher`.
2. Inside the service, **Create Function** → **Python 3.12** → **Upload Code** (zip the `deploy/fc_watcher/` directory).
3. **Handler:** `tripcascade.watcher.fc_function.handler` (Event handler type) for the Timer trigger.
4. **Triggers:** add a **Timer trigger** (cron: `0 */15 * * * *`) + an **HTTP trigger** (Auth: Anonymous, methods: GET+POST). For the HTTP trigger, create a **separate function version** pointing to the WSGI handler (or use the same function with FC's dual-mode support — verify in console).
5. **Environment variables:** per §2.1.
6. **Memory:** 512 MB (forecast model load ~100MB; inference <1s). **Timeout:** 120s (cold start + first forecast load).

`[Inference]` FC console UI may vary by version; exact field names may differ. Adapt per the console's labels. The code + dependencies are the same either way.

---

## 4. Verify (Local Smoke Test)

Before live deploy, run the local smoke test. This starts the agent HTTP service locally and invokes the watcher dispatch in-process — **no Alibaba Cloud account needed**.

```bash
cd /path/to/tripcascade
uv run python scripts/smoke_test_cloud.py
```

**Expected output:**
```
=== TripCascade Cloud Smoke Test ===
health test: 200
webhook test: status=202
timer test: status=200 events_emitted=2
  result: node=leg1_pvg_nrt status=dispatched cascade_affected=[...] decisions=3
    auto_settled=1 held=1 advisory=1
PASS: full re-plan chain: auto-settled + advisory + held-for-approval
=== All checks passed ===
EXIT: SUCCESS
```

**What the smoke test proves:**
1. The Watcher dispatch logic works end-to-end: health, webhook, timer.
2. The forecast model loads + runs (real P per leg logged).
3. The demo-mode scripted event (P=0.82) is emitted.
4. The agent receives the disruption event and returns a full re-plan:
   - Leg1 (PVG→NRT): **auto-settled** (S$30 ≤ S$50 cap) with audit log.
   - Hotel (Tokyo): **advisory** — impact analysis + drafted notification (no Atlas call).
   - Leg2 (NRT→PVG): **held** (S$120 > S$50 cap) — awaiting human approval.

### 4.1 After live deploy

```bash
# Verify the live HTTP endpoint
curl -i <fc-https-url>/health
# HTTP/1.1 200
# {"status":"ok","product":"TripCascade"}

# Trigger the Timer manually (FC console → Functions → watcher → Invoke) and check logs.
# Register the webhook URL with Atlas (P1 stretch, §5.3).
# Send a test webhook:
curl -X POST <fc-https-url>/webhook \
  -H "Content-Type: application/json" \
  -d '{"eventType":"abnormal.cancelled","orderNo":"TESTA20260827202428852"}'
```

---

## 5. Agent Endpoint — Reachability Options

The live Watcher (Alibaba Cloud SG) must reach the agent endpoint to POST `disruption_likely` events. Three options — pick one.

### 5.1 Option A: second FC function (recommended)

Deploy the agent HTTP service as a **second FC function** in the same Alibaba Cloud account + region. The Watcher POSTs to its FC HTTPS URL. Cloud-to-cloud, no tunnel, reliable.

**Setup:** uncomment the `fc_agent` service block in `s.yaml` and re-deploy. The agent function uses the same codebase (same `codeUri: ./` — the full `src/tripcascade/` is available). Set `AGENT_ENDPOINT_URL` in the Watcher's env vars to the agent function's HTTPS URL (found in the FC console after deploy).

**Pros:** cloud-to-cloud, no external tunnel, no uptime risk. **Cons:** slightly extends "one cloud component" — but the Watcher is still the one watcher; the agent function is the invoked surface.

### 5.2 Option B: local Mac mini + tunnel

Run the agent HTTP service on the Mac mini and expose it via Cloudflare Tunnel / Tailscale Funnel / ngrok. Set `AGENT_ENDPOINT_URL` to the public tunnel URL.

**Setup:**
```bash
# On Mac mini (the agent host):
uv run python -m tripcascade.agent.http_service --port 8088
# Then in another terminal:
cloudflared tunnel --url http://127.0.0.1:8088
# or: tailscale funnel 8088
# Use the resulting https://...trycloudflare.com URL as AGENT_ENDPOINT_URL.
```

**Pros:** keeps "one cloud function." **Cons:** tunnel uptime risk during the demo; extra config step.

### 5.3 Option C: smoke test only

The Watcher's live deploy proves Operating Scale (FC function runs, forecast polls, events logged); the agent re-plan is demonstrated via the local smoke test only (the acceptance evidence). The live Watcher POSTs to a mock/echo agent endpoint that returns a dummy 200, OR logs the attempt and moves on.

**Pros:** minimal. **Cons:** live path doesn't show agent invocation end-to-end.

---

## 6. Cost / Quota Note

`[Inference]` based on public Alibaba Cloud FC pricing (not verified in Mike's console):

- **Free tier:** `[Inference]` 1M requests/month + 400K CU-seconds/month. A single poll every 15 minutes = **~2,880 invocations/month**. Cold-start forecast load + inference + agent POST takes `[Inference]` 2–5 CU-seconds per invocation → **~6K–14K CU-seconds/month**. Both well within any reasonable free tier.
- **Webhook traffic:** demo-only; negligible.
- **Agent FC function (Option A):** same order-of-magnitude — few hundred KB memory, 100ms per call.

**Action:** Mike, confirm in the FC console that your account's free-tier quota covers the above, and note any overage in the event of quota exhaustion. The demo is NOT at risk — even pay-as-you-go pricing is `[Inference]` fractions of a cent per call.

---

## 7. Webhook Registration (P1 Stretch)

Atlas webhook support confirmed (`doc/atlas_surface.md` §3). Register the live Watcher HTTPS endpoint:

### 7.1 Register the webhook URL

```bash
# Use curl (creds from .env, never echo values):
curl -X POST https://sandbox.atriptech.com/updateWebhookURL.do \
  -H "x-atlas-client-id: $ATLAS_SANDBOX_ACCESS_KEY" \
  -H "x-atlas-client-secret: $ATLAS_SANDBOX_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "<watcher-fc-https-url>/webhook"}'
```

Expected: HTTP 200 with success response. **Note:** this registers ONE URL for ALL webhook event types. Only one registration is needed.

### 7.2 Event types of interest

| Event type | Signal | Watcher action |
|---|---|---|
| `abnormal.cancelled` | Unaccounted Cancellation | POST `disruption_likely` (P=1.0, confirmed) to agent |
| `order.schedulechange` | Schedule Change (API) | POST `disruption_likely` to agent (leg-level re-plan) |
| `email.schedulechange` | Schedule Change (email) | POST `disruption_likely` to agent |

### 7.3 Incident query (complementary)

The Watcher can also **poll** incidents via `POST /event/getPageList.do` (already implemented in `atlas_tools/client.py:RestClient.query_incidents()`). This is a complementary signal — the poll runs alongside the webhook for the best-effort delivery gap.

### 7.4 Verification

```bash
# Query incidents manually (no webhook needed):
curl -X POST https://sandbox.atriptech.com/event/getPageList.do \
  -H "x-atlas-client-id: $ATLAS_SANDBOX_ACCESS_KEY" \
  -H "x-atlas-client-secret: $ATLAS_SANDBOX_SECRET_KEY" \
  -d '{"pageNo":1,"pageSize":5}'
```

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `s deploy` fails with 403 `fc:CreateService` | RAM user lacks FC permissions | Attach `AliyunFCFullAccess` policy to the RAM user (console → RAM → Users → Permissions) |
| `Runtime is set to an invalid value ... actual: 'python3.12'` | FC ap-southeast-1 max runtime is python3.10 | Set `runtime: python3.10` in s.yaml (both functions) |
| `trigger type 'http' and 'timer' are exclusive in a function` | FC forbids mixing HTTP + Timer triggers | Split into 2 functions under one service (watcher-poll Timer + watcher-http HTTP); the s.yaml already does this |
| `ModuleNotFoundError: No module named 'joblib'` (import time) | FC 3.0 fcapp.run doesn't auto-install requirements.txt | (a) health path is stdlib-only (works regardless); (b) bundle pydantic via `build_package.sh` (manylinux wheels); (c) forecast degrades to heuristic fallback (disclosed) if joblib absent |
| `cannot import name 'StrEnum' from 'enum'` | StrEnum added in Python 3.11; FC is 3.10 | Use `class X(str, Enum)` not `StrEnum` (already fixed in graph/models.py + agent/router.py) |
| POST /disruption returns health response | FC HTTP trigger passes WSGI environ, not event schema | Parser handles WSGI (`REQUEST_METHOD`/`PATH_INFO`/`wsgi.input`); see `_parse_fc_http_event` |
| POST /disruption returns `missing body` / body is empty | FC WSGI strips request body (CONTENT_LENGTH=0) | Watcher sends event as base64 query param `?event=<b64>`; agent reads it if wsgi.input is empty |
| `FileNotFoundError: '/assets/demo_itinerary.json'` | Code at `/code/` on FC; `parents[3]` resolves to `/` | `builder.py` searches upward for `assets/` dir (handles both dev + FC paths) |
| Timer doesn't fire | Cron syntax, timezone, or trigger disabled | Check FC console → Triggers → Timer → Enable; use UTC cron |
| Webhook POST returns 403 | Missing/invalid `x-atlas-client-id`/`x-atlas-client-secret` | Verify env vars set in FC console; check Atlas Sandbox creds are valid |
| Webhook POST returns 502 | Agent endpoint unreachable | Check `AGENT_ENDPOINT_URL` env var; verify agent service is healthy |
| Cold start > 30s | First forecast load | Expected: ~2s load + ~0.5s inference. Set timeout ≥ 120s. Heuristic fallback if model absent. |
| Agent returns no decisions | StubAtlasClient catalog mismatch or orchestrator error | Check FC logs; run the smoke test locally to reproduce |
| Quota exceeded | Too many invocations | Check FC console → Quota; demo is well within limits — if not, disable Timer between demo takes |

### 8.1 FC 3.0 fcapp.run platform notes (verified 2026-08-28)

These are **live-deploy-verified** findings about Alibaba Cloud FC 3.0 `fcapp.run` (the default HTTP-trigger mode):

1. **Max runtime: python3.10** (not 3.12). `StrEnum` (3.11+) must be avoided.
2. **HTTP + Timer triggers are exclusive** per function. Split into separate functions.
3. **No auto-install of requirements.txt.** Bundle deps as manylinux x86_64 wheels (via `build_package.sh`) or use FC layers. The build script bundles pydantic; joblib/httpx are lazy-imported (stdlib-only health path).
4. **HTTP trigger passes a WSGI environ** (`REQUEST_METHOD`, `PATH_INFO`, `wsgi.input`, `QUERY_STRING`), NOT an event-function schema (`method`/`httpMethod`/`requestContext.http`). The `_parse_fc_http_event` parser detects + handles both.
5. **WSGI HTTP triggers strip the request body** (`CONTENT_LENGTH=0`, `wsgi.input` empty even when a body is POSTed). Workaround: the watcher sends the disruption event as a base64-encoded `event` query param; the agent reads it if `wsgi.input` is empty.
6. **Code lives at `/code/`** on FC, not the dev repo root. Path resolution must search upward (the `builder._find_seed()` function does this).
7. **Return value served verbatim**: FC serves the function's return value directly as the HTTP body. Return a JSON string (not a dict — a dict gets `"".join(dict)` = keys concatenated).

**Deployed architecture (3 FC functions, ap-southeast-1):**
- `watcher-poll` (tripcascade-watcher service) — Timer trigger → forecast poll + scripted event → POST to agent
- `watcher-http` (tripcascade-watcher service) — HTTP trigger → `GET /health` + `POST /webhook`
- `agent` (tripcascade-agent service) — HTTP trigger → `GET /health` + `POST /disruption` → re-plan JSON

---

## 9. Rollback

```bash
# Serverless Devs:
s remove -t deploy/fc_watcher/s.yaml

# Console: Function Compute → Services → tripcascade-watcher → Delete.
# This removes both the watcher function + its triggers. Re-deploy:
bash deploy/fc_watcher/build_package.sh && s deploy -t deploy/fc_watcher/s.yaml
```

---

## 10. Deliverable Checklist (this task)

- [x] `src/tripcascade/watcher/fc_function.py` + `agent_client.py`
- [x] `src/tripcascade/agent/http_service.py` (incl. `fc_http_handler` for FC)
- [x] `deploy/fc_watcher/` (requirements.txt, s.yaml, build_package.sh)
- [x] `tests/test_watcher_fc.py` — 30 tests green (55 total)
- [x] `scripts/smoke_test_cloud.py` — exit 0, full re-plan chain
- [x] `.env.example` updated with cloud vars
- [x] **[Mike]** `s deploy` + env vars set (AGENT_ENDPOINT_URL wired)
- [x] **[Mike]** `curl <fc-url>/health` → 200 ✓ (watcher-http + agent)
- [x] **[Mike]** Timer trigger fires → event in FC logs ✓ (events_emitted=1)
- [x] **[Mike]** Live endpoint URLs recorded in `TODO.md`
- [x] **[Mike]** Watcher→Agent cloud-to-cloud re-plan ✓ (auto+advisory+held)
- [ ] **[Mike]** Free-tier quota confirmed in console (optional; demo well within limits)
- [ ] **[Mike]** Atlas webhook registered (P1 stretch; ingest code works, needs `updateWebhookURL.do`)

---

*Generated by pi agent · 2026-08-28 · tasks/05-cloud_deploy.md · live-deploy verified*