"""Tests for the TripCascade disruption-forecast inference module.

Run: uv run pytest tests/test_forecast_inference.py -v
"""

from __future__ import annotations

import time

import pytest

from tripcascade.forecast.inference import (
    get_alert_threshold,
    get_feature_schema,
    predict_disruption_prob,
)

# --- Example Atlas itinerary legs (different carriers/routes/times) ---

# Demo itinerary: PVG→NRT (Shanghai→Tokyo), typhoon season (Sep), evening departure
LEG_TYPOPHOON = {
    "carrier": "NH",  # ANA (unseen in BTS)
    "origin": "PVG",
    "destination": "NRT",
    "scheduled_dep_ts": "2026-09-04T19:30:00",
    "duration_minutes": 185,
}

# Off-season (Jan), morning departure, different route
LEG_OFFSEASON = {
    "carrier": "QF",  # Qantas (unseen in BTS)
    "origin": "SYD",
    "destination": "BKK",
    "scheduled_dep_ts": "2026-01-15T07:00:00",
    "duration_minutes": 350,
}

# LCC carrier, mid-day, short flight
LEG_LCC = {
    "carrier": "AK",  # AirAsia (unseen in BTS)
    "origin": "SIN",
    "destination": "KUL",
    "scheduled_dep_ts": "2026-06-20T12:15:00",
    "duration_minutes": 90,
}


def test_output_in_range():
    """predict_disruption_prob returns a float in [0, 1]."""
    p = predict_disruption_prob(LEG_TYPOPHOON)
    assert isinstance(p, float), f"Expected float, got {type(p)}"
    assert 0.0 <= p <= 1.0, f"Probability {p} outside [0, 1]"


def test_varies_with_inputs():
    """Different legs produce different probabilities.

    Typhoon-season evening departure should score HIGHER than
    off-season morning departure (per SPECS S-002 verification).
    """
    p_typhoon = predict_disruption_prob(LEG_TYPOPHOON)
    p_offseason = predict_disruption_prob(LEG_OFFSEASON)
    p_lcc = predict_disruption_prob(LEG_LCC)

    # They should not all be identical (model is sensitive to inputs)
    probs = {p_typhoon, p_offseason, p_lcc}
    assert len(probs) > 1, f"All probabilities identical: {probs}"

    # Typhoon-season evening should be higher than off-season morning
    # (September is autumn = typhoon season in West Pacific)
    assert p_typhoon > p_offseason, (
        f"Expected typhoon-season ({p_typhoon:.4f}) > off-season ({p_offseason:.4f})"
    )


def test_unseen_carrier_graceful():
    """Unseen carriers (not in BTS) produce valid outputs without error."""
    p = predict_disruption_prob(LEG_LCC)
    assert isinstance(p, float)
    assert 0.0 <= p <= 1.0
    # Should be a meaningful probability (not exactly 0 or 1)
    assert 0.01 < p < 0.99, f"Probability {p} suspiciously extreme for unseen carrier"


def test_model_loads_fast():
    """Model artifact loads in <2s (acceptance criterion)."""
    t0 = time.time()
    predict_disruption_prob(LEG_TYPOPHOON)  # triggers lazy load
    load_time = time.time() - t0
    assert load_time < 2.0, f"Model load took {load_time:.2f}s (limit: 2.0s)"


def test_threshold_in_valid_range():
    """Alert threshold is a float in (0, 1)."""
    threshold = get_alert_threshold()
    assert isinstance(threshold, float)
    assert 0.0 < threshold < 1.0


def test_feature_schema_complete():
    """Feature schema contains expected fields."""
    schema = get_feature_schema()
    assert "feature_names" in schema
    assert "alert_threshold" in schema
    assert "disruption_definition" in schema
    assert len(schema["feature_names"]) == 10
