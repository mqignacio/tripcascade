# Coding Standards — TripCascade

Shared by **pi** and **Qoder**. Load before writing any Python in this repo. Source: pi coding skill; this file is the TripCascade-specific application.

## 1. Folder structure (src layout)

```
src/tripcascade/         package root (installed editable via uv)
  graph/                 dependency DAG + cascade
  forecast/              ML disruption forecast
  agent/                 orchestrator + policy engine + model routing
  atlas_tools/           Atlas CLI + REST wrappers
  ui/                    experiential interface
  watcher/               disruption watcher (poll + webhook)
scripts/                 standalone scripts (train, eval, data)
tests/                   pytest (testpaths=["tests"], pythonpath=["src"])
doc/                     PRD/SPECS/atlas_surface (source of truth — do not duplicate logic in code)
skills/                  this pack
assets/                  demo seed, plots, supporting files
```

## 2. Style

- **Python 3.11+.** PEP 8, line length **120**.
- **Naming:** lowercase + underscores for files/folders/functions/vars (`predict_disruption`, `fare_difference_cents`). Hyphens only for prefixes/suffixes (dates, versions). No whitespace/special chars.
- **Docstrings:** Google-style, every module + public function.
- **Type hints** on all function signatures. Use `pydantic` models for the graph nodes, decision records, and Atlas payloads (see `doc/SPECS.md` §4 Data Model).
- **Constants over magic numbers.** `SETTLEMENT_CAP_CENTS = 5000` (not `5000` inline). Cap arithmetic: `50 * 100 == 5000`; verify with a script, never mentally.
- **Logging, not `print()`**, in scripts/utilities. Reserve `print()` for notebook cells.

## 3. Environment (uv, never bare pip)

```bash
uv sync                       # create/refresh .venv from locked deps
uv add <pkg>                  # add a dep (check PyPI name vs import path; prefer wheels)
uv add --dev pytest ruff
uv run pytest -q              # run tests inside the env
uv run python scripts/...     # run a script
```

- One env per project. Commit `pyproject.toml` + `uv.lock`; never commit `.venv/`.
- Add large packages (>30 MB: torch, xgboost) individually with `--timeout 300`.

## 4. Testing

- `pytest`, smoke tests at minimum, coverage target 80%.
- **Assert post-state, not HTTP 200** (the "false success" cure): after `order create`, assert a non-empty `orderNo` exists; after `order pay`, assert `payment_confirmation_id`; after ticketing, assert `ticketNos` non-empty.
- Run before committing: `uv run pytest -q`.

## 5. Secrets

- Read credentials from `.env` via `os.environ` (or a `Settings` pydantic model). **Never** pass secrets as CLI flags (they persist in shell history / process listings).
- `.env` is gitignored. `.env.example` carries keys only.
- The Atlas booking-flow APIs use a JWT (`atlas-flight auth login`); the webhook/incident APIs use `x-atlas-client-id`/`x-atlas-client-secret` from `.env`. See `atlas_tool_protocol.md`.

## 6. Verification rule (always-on)

Never trust your own computation for numerical output. Verify cap arithmetic, fare differences, and node/edge counts with `python3 -c "..."` or a script. Document the check.
