"""Runtime configuration for the TripCascade agent.

Reads `.env` (gitignored) via a tiny stdlib loader — no extra dep required so the
module imports cleanly even before `qwen-agent`/`python-dotenv` are installed.
Secrets are read from `os.environ` and **never** echoed or passed as CLI flags
(see `skills/atlas_tool_protocol.md` §5, `skills/coding_standards.md` §5).

Source of truth for the cap: `doc/PRD.md` §6 (default S$50 = 5000 cents) and
`doc/SPECS.md` §1. Source of truth for model names: `resources/qoder-model.md`
(the Qoder model list — `Qwen3.7-Plus` 0.1x routine, `Qwen3.8-Max` 0.5x hard).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Repo root = 4 levels up from this file: .../src/tripcascade/agent/config.py
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DECISION_LOG = REPO_ROOT / "logs" / "decision_log.jsonl"
DEFAULT_AUDIT_LOG = REPO_ROOT / "logs" / "audit_log.jsonl"


def load_env_file(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ (does not overwrite).

    Minimal stdlib parser: skips blanks/comments, strips quotes. Called once at
    import of :func:`get_settings`. Never raises — a missing .env just means
    environment variables must already be set.
    """
    env_path = path or (REPO_ROOT / ".env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    """Resolved settings for one process. Construct via :func:`get_settings`."""

    # --- Bounded-autonomy settlement policy (FR-006) ---
    settlement_cap_cents: int = 5000  # S$50 = 5000 cents (verified 50*100)

    # --- Model-tier routing (FR-009). Names from resources/qoder-model.md ---
    routine_model: str = "Qwen3.7-Plus"  # 0.1x; PRD's "Qwen-Plus" -> this model
    hard_model: str = "Qwen3.8-Max"       # 0.5x
    local_fallback_model: str = "local-open-weight"

    # --- Atlas Sandbox REST creds (webhook/incident + aftercare; .env, never CLI) ---
    atlas_sandbox_access_key: str = ""
    atlas_sandbox_secret_key: str = ""
    atlas_sandbox_base_url: str = "https://sandbox.atriptech.com"

    # --- Disruption Watcher (FR-003) ---
    watcher_poll_interval_seconds: int = 900
    atlas_incident_path: str = "/event/getPageList.do"
    alert_threshold: float = 0.35  # from forecast artifacts (tasks/03-data_ml)

    # --- LLM backend selection ---
    dashscope_api_key: str = ""  # optional; enables real Qwen calls via qwen-agent
    llm_backend: str = "stub"    # "stub" (default/demo/tests) | "dashscope" | "local"

    # --- Orchestrator loop safety (cure for infinite-loop) ---
    step_budget: int = 12        # max agent steps per disruption event
    give_up_after: int = 12      # hard stop; emit give_up event + decision record

    # --- Paths (runtime state; gitignored) ---
    decision_log_path: Path = field(default_factory=lambda: DEFAULT_DECISION_LOG)
    audit_log_path: Path = field(default_factory=lambda: DEFAULT_AUDIT_LOG)

    @property
    def cap_is_sgd_50(self) -> bool:
        """Sanity: the documented default cap. (50 SGD == 5000 cents.)"""
        return self.settlement_cap_cents == 50 * 100


_LOADED: Settings | None = None


def get_settings() -> Settings:
    """Return cached settings, loading .env first. Idempotent."""
    global _LOADED
    if _LOADED is not None:
        return _LOADED
    load_env_file()

    def _env_int(key: str, default: int) -> int:
        raw = os.environ.get(key, "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            logger.warning("Invalid int for %s=%r; using default %d", key, raw, default)
            return default

    def _env_float(key: str, default: float) -> float:
        raw = os.environ.get(key, "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            logger.warning("Invalid float for %s=%r; using default %f", key, raw, default)
            return default

    _LOADED = Settings(
        settlement_cap_cents=_env_int("SETTLEMENT_CAP_CENTS", 5000),
        routine_model=os.environ.get("ROUTINE_MODEL", "Qwen3.7-Plus") or "Qwen3.7-Plus",
        hard_model=os.environ.get("HARD_MODEL", "Qwen3.8-Max") or "Qwen3.8-Max",
        local_fallback_model=os.environ.get("LOCAL_FALLBACK_MODEL", "local-open-weight")
        or "local-open-weight",
        atlas_sandbox_access_key=os.environ.get("ATLAS_SANDBOX_ACCESS_KEY", ""),
        atlas_sandbox_secret_key=os.environ.get("ATLAS_SANDBOX_SECRET_KEY", ""),
        atlas_sandbox_base_url=os.environ.get(
            "ATLAS_SANDBOX_BASE_URL", "https://sandbox.atriptech.com"
        ),
        watcher_poll_interval_seconds=_env_int("WATCHER_POLL_INTERVAL_SECONDS", 900),
        atlas_incident_path=os.environ.get("ATLAS_INCIDENT_PATH", "/event/getPageList.do"),
        alert_threshold=_env_float("ALERT_THRESHOLD", 0.35),
        dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        llm_backend=os.environ.get("TRIPCASCADE_LLM_BACKEND", "stub") or "stub",
        step_budget=_env_int("TRIPCASCADE_STEP_BUDGET", 12),
        give_up_after=_env_int("TRIPCASCADE_GIVE_UP_AFTER", 12),
        decision_log_path=Path(os.environ.get("DECISION_LOG_PATH", str(DEFAULT_DECISION_LOG))),
        audit_log_path=Path(os.environ.get("AUDIT_LOG_PATH", str(DEFAULT_AUDIT_LOG))),
    )
    return _LOADED
