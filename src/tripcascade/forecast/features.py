"""Feature engineering for the disruption-forecast model.

Design principles (task 03):
- Every feature must be derivable from an Atlas itinerary at inference time.
- Transferable features (time-of-day, day-of-week, season, block-time) are
  geography-agnostic and transfer from BTS training to Atlas inference.
- Carrier and route are included via target encoding with a global base-rate
  fallback for unseen categories (simulates Atlas LCC inference).
- No real-time weather (not available at inference).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# --- Constants ---

SEASON_MAP: dict[int, int] = {
    12: 0, 1: 0, 2: 0,  # Winter
    3: 1, 4: 1, 5: 1,  # Spring
    6: 2, 7: 2, 8: 2,  # Summer
    9: 3, 10: 3, 11: 3,  # Autumn
}

BLOCK_TIME_BINS = [0, 60, 120, 180, 300, 999]
BLOCK_TIME_LABELS = ["short", "medium", "long", "xl", "trans"]


@dataclass
class FeaturePipeline:
    """Holds the fitted encoders/parameters needed to transform raw rows.

    At inference time, unseen carriers/routes fall back to global mean
    (the base-rate), mimicking the Atlas condition.
    """

    # Fitted parameters (set during .fit())
    global_base_rate: float = 0.0
    carrier_means: dict[str, float] = field(default_factory=dict)
    route_means: dict[str, float] = field(default_factory=dict)
    dep_hour_bins: list[float] = field(default_factory=list)

    def fit(self, df: pd.DataFrame, label_col: str = "disrupted") -> None:
        """Fit target encoders on training data only."""
        self.global_base_rate = float(df[label_col].mean())

        # Carrier target encoding
        carrier_stats = df.groupby("IATA_CODE_Reporting_Airline")[label_col].mean()
        self.carrier_means = carrier_stats.to_dict()

        # Route target encoding
        df = df.copy()
        df["route"] = df["Origin"] + "-" + df["Dest"]
        route_stats = df.groupby("route")[label_col].mean()
        self.route_means = route_stats.to_dict()

        # Dep-hour bins (use 3-hour blocks)
        self.dep_hour_bins = list(range(0, 25, 3))

        logger.info(
            "Fitted pipeline: base_rate=%.4f, %d carriers, %d routes",
            self.global_base_rate,
            len(self.carrier_means),
            len(self.route_means),
        )

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform a DataFrame of raw BTS/Atlas rows into model features."""
        out = pd.DataFrame(index=df.index)

        # --- Temporal features (from CRSDepTime / Month / DayOfWeek) ---
        dep_time = df["CRSDepTime"].astype(str).str.zfill(4)
        out["dep_hour"] = dep_time.str[:2].astype(int)
        out["dep_hour_bucket"] = pd.cut(
            out["dep_hour"], bins=self.dep_hour_bins or [0, 6, 12, 18, 24], labels=False
        )
        out["day_of_week"] = df["DayOfWeek"].astype(int)
        out["month"] = df["Month"].astype(int)
        out["season"] = df["Month"].map(SEASON_MAP).astype(int)
        out["is_weekend"] = (df["DayOfWeek"].astype(int) >= 6).astype(int)

        # --- Block-time feature (distance proxy) ---
        elapsed = pd.to_numeric(df["CRSElapsedTime"], errors="coerce")
        median_bt = elapsed.median() if elapsed.notna().any() else 0.0
        out["block_time"] = elapsed.fillna(median_bt)
        out["block_time_bucket"] = pd.cut(
            out["block_time"], bins=BLOCK_TIME_BINS, labels=list(range(len(BLOCK_TIME_BINS) - 1))
        ).cat.codes
        out["block_time_bucket"] = out["block_time_bucket"].clip(lower=0)

        # --- Carrier target encoding (unseen → global base rate) ---
        out["carrier_te"] = df["IATA_CODE_Reporting_Airline"].map(self.carrier_means).fillna(
            self.global_base_rate
        )

        # --- Route target encoding (unseen → global base rate) ---
        route = df["Origin"] + "-" + df["Dest"]
        out["route_te"] = route.map(self.route_means).fillna(self.global_base_rate)

        return out

    def transform_dict(self, leg: dict[str, Any]) -> list[float]:
        """Transform a single Atlas itinerary leg (dict) into a feature vector.

        Expected keys (matching Atlas search offer JSON):
            carrier: str (IATA code)
            origin: str (airport code)
            destination: str
            scheduled_dep_ts: str (ISO 8601) OR departure_time: str (YYYYMMDDHHMM)
            duration_minutes: int (flight block time in minutes)

        Returns a list of floats matching the feature order:
            [dep_hour, dep_hour_bucket, day_of_week, month, season,
             is_weekend, block_time, block_time_bucket, carrier_te, route_te]
        """
        from datetime import datetime

        # Parse departure time
        dep_ts = leg.get("scheduled_dep_ts") or leg.get("departure_time", "")
        if "T" in dep_ts or " " in dep_ts:
            # ISO 8601
            dt = datetime.fromisoformat(dep_ts.replace("Z", ""))
        else:
            # YYYYMMDDHHMM format
            dep_ts = str(dep_ts).strip().zfill(12)
            dt = datetime.strptime(dep_ts, "%Y%m%d%H%M")

        dep_hour = dt.hour
        dep_hour_bucket = int(np.digitize(dep_hour, self.dep_hour_bins or [6, 12, 18, 24]))
        day_of_week = dt.isoweekday()  # 1=Mon..7=Sun (matches BTS)
        month = dt.month
        season = SEASON_MAP[month]
        is_weekend = 1 if day_of_week >= 6 else 0

        # Block time
        block_time = float(leg.get("duration_minutes", 0))
        if block_time > 0:
            # Use np.searchsorted to avoid pandas version quirks with single-element cut
            block_time_bucket = int(np.searchsorted(BLOCK_TIME_BINS[1:-1], block_time))
            block_time_bucket = max(0, min(block_time_bucket, len(BLOCK_TIME_BINS) - 2))
        else:
            block_time_bucket = 0

        # Target encodings with fallback
        carrier = str(leg.get("carrier", ""))
        carrier_te = self.carrier_means.get(carrier, self.global_base_rate)
        route = f"{leg.get('origin', '')}-{leg.get('destination', '')}"
        route_te = self.route_means.get(route, self.global_base_rate)

        return [
            float(dep_hour),
            float(dep_hour_bucket),
            float(day_of_week),
            float(month),
            float(season),
            float(is_weekend),
            block_time,
            float(block_time_bucket),
            carrier_te,
            route_te,
        ]

    @property
    def feature_names(self) -> list[str]:
        return [
            "dep_hour",
            "dep_hour_bucket",
            "day_of_week",
            "month",
            "season",
            "is_weekend",
            "block_time",
            "block_time_bucket",
            "carrier_te",
            "route_te",
        ]


def build_label(df: pd.DataFrame) -> pd.Series:
    """Build the binary disruption label.

    Disrupted = 1 if DepDelay >= 15 OR Cancelled == 1 OR Diverted == 1.
    """
    dep_delay = pd.to_numeric(df["DepDelay"], errors="coerce").fillna(0)
    cancelled = pd.to_numeric(df["Cancelled"], errors="coerce").fillna(0).astype(int)
    diverted = pd.to_numeric(df["Diverted"], errors="coerce").fillna(0).astype(int)

    label = ((dep_delay >= 15) | (cancelled == 1) | (diverted == 1)).astype(int)
    logger.info("Label distribution: disrupted=%d (%.1f%%), on_time=%d",
                label.sum(), 100 * label.mean(), len(label) - label.sum())
    return label
