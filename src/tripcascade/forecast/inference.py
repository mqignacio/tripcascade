"""Inference API for the TripCascade disruption-forecast model.

Exposes:
    predict_disruption_prob(itinerary_leg: dict) -> float
    get_alert_threshold() -> float
    get_feature_schema() -> dict

The model artifact + feature pipeline are loaded lazily (cached) so that
subsequent calls are <1ms. First load targets <2s (acceptance criterion).

Heuristic fallback: if the model cannot be loaded or a feature is missing,
returns a base-rate-informed float (documented, logged — no silent failure).
Satisfies SPECS S-002: "honest heuristic base-rate fallback returns a
documented float (no silent failure)."
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"

# --- Cached state (loaded once per process) ---
_model = None
_pipeline = None
_base_rate_table: list[dict] | None = None
_schema: dict | None = None


def _load_artifacts() -> None:
    """Load model + pipeline + schema from disk (cached after first call)."""
    global _model, _pipeline, _base_rate_table, _schema

    if _model is not None:
        return

    logger.info("Loading forecast artifacts from %s", ARTIFACTS_DIR)
    _model = joblib.load(ARTIFACTS_DIR / "forecast_model.joblib")
    _pipeline = joblib.load(ARTIFACTS_DIR / "feature_pipeline.joblib")
    _base_rate_table = joblib.load(ARTIFACTS_DIR / "base_rate_table.joblib")
    with open(ARTIFACTS_DIR / "feature_schema.json") as f:
        _schema = json.load(f)
    logger.info("Artifacts loaded: model=%s, pipeline base_rate=%.4f",
                type(_model).__name__, _pipeline.global_base_rate)


def _heuristic_fallback(leg: dict[str, Any]) -> float:
    """Return a base-rate-informed probability using the heuristic table.

    Uses (month, day_of_week) base rates from training data.
    If table is unavailable, returns the global base rate.
    """
    from datetime import datetime

    try:
        dep_ts = leg.get("scheduled_dep_ts") or leg.get("departure_time", "")
        if "T" in dep_ts or " " in dep_ts:
            dt = datetime.fromisoformat(str(dep_ts).replace("Z", ""))
        else:
            dt = datetime.strptime(str(dep_ts).zfill(12), "%Y%m%d%H%M")
        month = dt.month
        dow = dt.isoweekday()
    except Exception:
        # Cannot parse time → return global base rate
        return _pipeline.global_base_rate if _pipeline else 0.15

    # Look up base rate for (month, dow) from the table
    if _base_rate_table:
        for row in _base_rate_table:
            if row.get("month") == month and row.get("day_of_week") == dow:
                return float(row.get("base_rate", 0.15))

    # Fall back to global base rate
    return _pipeline.global_base_rate if _pipeline else 0.15


def predict_disruption_prob(itinerary_leg: dict[str, Any]) -> float:
    """Predict P(disruption) for a single Atlas itinerary leg.

    Args:
        itinerary_leg: dict with keys matching Atlas search offer JSON:
            - carrier: str (IATA code, e.g. "QF", "ZH")
            - origin: str (airport code, e.g. "PVG")
            - destination: str (airport code, e.g. "NRT")
            - scheduled_dep_ts: str (ISO 8601) OR departure_time: str (YYYYMMDDHHMM)
            - duration_minutes: int (flight block time)

    Returns:
        float in [0, 1] representing P(disruption).

    Raises:
        Never raises — on any failure, returns heuristic fallback.
    """
    try:
        _load_artifacts()
    except Exception as e:
        logger.warning("Failed to load model artifacts: %s. Using heuristic fallback.", e)
        # No pipeline available → return a conservative base rate
        return 0.15

    try:
        features = _pipeline.transform_dict(itinerary_leg)
        import pandas as pd
        X = pd.DataFrame([features], columns=_pipeline.feature_names)
        proba = float(_model.predict_proba(X)[0, 1])
        return max(0.0, min(1.0, proba))
    except Exception as e:
        logger.warning("Inference failed (%s). Using heuristic fallback.", e)
        return _heuristic_fallback(itinerary_leg)


def get_alert_threshold() -> float:
    """Return the configured alert threshold (from training)."""
    _load_artifacts()
    return float(_schema["alert_threshold"])


def get_feature_schema() -> dict:
    """Return the feature schema (for UI/agent to display)."""
    _load_artifacts()
    return dict(_schema)
