"""Train the XGBoost disruption-forecast classifier.

Usage:
    uv run python -m tripcascade.forecast.train

Workflow:
1. Load BTS data (Jan-Jun 2024).
2. Build label (dep_delay >= 15 OR cancelled OR diverted).
3. Temporal split: train=Jan-Apr, val=May, test=Jun.
4. Fit feature pipeline on train only.
5. Train XGBoost classifier.
6. Select precision-favoring threshold on val.
7. Route-generalization validation (hold out entire carriers).
8. Save artifacts + metrics JSON.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score
from xgboost import XGBClassifier

from tripcascade.forecast.data_loader import load_local
from tripcascade.forecast.features import FeaturePipeline, build_label

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# --- Config ---
YEAR = 2024
TRAIN_MONTHS = [1, 2, 3, 4]
VAL_MONTHS = [5]
TEST_MONTHS = [6]
ARTIFACTS_DIR = Path(__file__).parent / "artifacts"

# Route-generalization: hold out these carriers (largest US carriers by volume)
HELD_OUT_CARRIERS = ["WN", "DL", "AA"]  # Southwest, Delta, American

# XGBoost hyperparameters (lightweight for 2-day build)
XGB_PARAMS = {
    "n_estimators": 200,
    "max_depth": 6,
    "learning_rate": 0.1,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "objective": "binary:logistic",
    "eval_metric": "auc",
    "n_jobs": -1,
    "random_state": 42,
}


def _compute_metrics(y_true: np.ndarray, y_proba: np.ndarray, threshold: float) -> dict:
    """Compute precision/recall/F1/AUC at a given threshold."""
    y_pred = (y_proba >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", zero_division=0
    )
    auc = roc_auc_score(y_true, y_proba)
    return {
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
        "roc_auc": round(float(auc), 4),
        "threshold": round(float(threshold), 4),
    }


def _select_threshold(val_proba: np.ndarray, val_label: np.ndarray) -> float:
    """Select a precision-favoring threshold.

    Strategy: maximize precision subject to recall >= 0.2.
    Rationale: false alarms erode traveler trust (AIVPC pains).
    """
    best_threshold = 0.5
    best_precision = 0.0

    for t in np.arange(0.3, 0.85, 0.01):
        y_pred = (val_proba >= t).astype(int)
        precision, recall, _, _ = precision_recall_fscore_support(
            val_label, y_pred, average="binary", zero_division=0
        )
        if recall >= 0.2 and precision > best_precision:
            best_precision = precision
            best_threshold = t

    logger.info("Selected threshold=%.2f (precision=%.3f at recall>=%.2f)",
                best_threshold, best_precision, 0.2)
    return float(best_threshold)


def main() -> None:
    t0 = time.time()
    logger.info("=== Training TripCascade disruption-forecast model ===")

    # 1. Load data
    logger.info("Loading BTS data for %d months 1-6 %d...", 6, YEAR)
    df = load_local(YEAR, [1, 2, 3, 4, 5, 6])

    # 2. Build label
    df["disrupted"] = build_label(df)

    # 3. Temporal split
    train_df = df[df["Month"].isin(TRAIN_MONTHS)].copy()
    val_df = df[df["Month"].isin(VAL_MONTHS)].copy()
    test_df = df[df["Month"].isin(TEST_MONTHS)].copy()
    logger.info("Split: train=%d, val=%d, test=%d", len(train_df), len(val_df), len(test_df))

    # 4. Fit feature pipeline on TRAIN only (no leakage)
    pipeline = FeaturePipeline()
    pipeline.fit(train_df)

    # Transform
    X_train = pipeline.transform(train_df)
    X_val = pipeline.transform(val_df)
    X_test = pipeline.transform(test_df)
    y_train = train_df["disrupted"].values
    y_val = val_df["disrupted"].values
    y_test = test_df["disrupted"].values

    feature_names = pipeline.feature_names
    logger.info("Features: %s", feature_names)

    # 5. Train XGBoost
    logger.info("Training XGBoost (%d trees, depth=%d)...", XGB_PARAMS["n_estimators"], XGB_PARAMS["max_depth"])
    model = XGBClassifier(**XGB_PARAMS)
    model.fit(X_train[feature_names], y_train)

    # 6. Evaluate + select threshold
    val_proba = model.predict_proba(X_val[feature_names])[:, 1]
    threshold = _select_threshold(val_proba, y_val)

    # Test set metrics
    test_proba = model.predict_proba(X_test[feature_names])[:, 1]
    test_metrics = _compute_metrics(y_test, test_proba, threshold)
    logger.info("TEST METRICS: %s", test_metrics)

    # Val metrics for reference
    val_metrics = _compute_metrics(y_val, val_proba, threshold)
    logger.info("VAL METRICS:  %s", val_metrics)

    # Baseline comparison: base-rate predictor
    base_rate = float(y_test.mean())
    base_precision = base_rate  # predicting "all disrupted" at base rate
    logger.info("Base rate (test): %.4f → a heuristic that always predicts base-rate")

    # 7. Route-generalization validation
    logger.info("Route-generalization validation (held out: %s)...", HELD_OUT_CARRIERS)
    train_no_heldout = train_df[~train_df["IATA_CODE_Reporting_Airline"].isin(HELD_OUT_CARRIERS)].copy()
    test_heldout = test_df[test_df["IATA_CODE_Reporting_Airline"].isin(HELD_OUT_CARRIERS)].copy()

    # Re-fit pipeline on reduced training set (held-out carriers now unseen)
    pipeline_gen = FeaturePipeline()
    pipeline_gen.fit(train_no_heldout)
    X_train_gen = pipeline_gen.transform(train_no_heldout)
    X_test_gen = pipeline_gen.transform(test_heldout)
    y_train_gen = train_no_heldout["disrupted"].values
    y_test_gen = test_heldout["disrupted"].values

    model_gen = XGBClassifier(**XGB_PARAMS)
    model_gen.fit(X_train_gen[feature_names], y_train_gen)
    gen_proba = model_gen.predict_proba(X_test_gen[feature_names])[:, 1]
    gen_metrics = _compute_metrics(y_test_gen, gen_proba, threshold)
    logger.info("GEN METRICS (held-out carriers): %s", gen_metrics)

    # 8. Build base-rate table for heuristic fallback
    # Compute base rates by (season, dep_hour_bucket, day_of_week)
    train_df["dep_hour"] = train_df["CRSDepTime"].astype(str).str.zfill(4).str[:2].astype(int)
    base_rate_df = train_df.groupby(["Month", "DayOfWeek"])[["disrupted"]].mean().reset_index()
    base_rate_df.columns = ["month", "day_of_week", "base_rate"]

    # 9. Save artifacts
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, ARTIFACTS_DIR / "forecast_model.joblib")
    joblib.dump(pipeline, ARTIFACTS_DIR / "feature_pipeline.joblib")
    joblib.dump(base_rate_df.to_dict(orient="records"), ARTIFACTS_DIR / "base_rate_table.joblib")

    schema = {
        "feature_names": feature_names,
        "disruption_definition": "DepDelay >= 15 OR Cancelled == 1 OR Diverted == 1",
        "alert_threshold": threshold,
        "training_source": f"US DOT BTS On-Time Performance, {YEAR} Jan-Jun",
        "license": "Public domain (US Government work)",
        "held_out_carriers": HELD_OUT_CARRIERS,
        "xgb_params": XGB_PARAMS,
    }
    with open(ARTIFACTS_DIR / "feature_schema.json", "w") as f:
        json.dump(schema, f, indent=2)

    # 10. Save metrics
    metrics = {
        "model": "XGBoost binary classifier",
        "training_data": f"BTS On-Time Performance {YEAR} Jan-Jun (~{len(df):,} rows)",
        "temporal_split": {
            "train": f"months {TRAIN_MONTHS}",
            "val": f"months {VAL_MONTHS}",
            "test": f"months {TEST_MONTHS}",
        },
        "features": feature_names,
        "val_metrics": val_metrics,
        "test_metrics": test_metrics,
        "route_generalization": {
            "held_out_carriers": HELD_OUT_CARRIERS,
            "n_test_rows": len(test_heldout),
            "metrics": gen_metrics,
            "in_distribution_delta": {
                "precision": round(test_metrics["precision"] - gen_metrics["precision"], 4),
                "recall": round(test_metrics["recall"] - gen_metrics["recall"], 4),
                "f1": round(test_metrics["f1"] - gen_metrics["f1"], 4),
                "roc_auc": round(test_metrics["roc_auc"] - gen_metrics["roc_auc"], 4),
            },
        },
        "base_rate": round(base_rate, 4),
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    with open(ARTIFACTS_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    logger.info("Artifacts saved to %s", ARTIFACTS_DIR)
    logger.info("Total time: %.1fs", time.time() - t0)
    logger.info("=== Training complete ===")


if __name__ == "__main__":
    main()
