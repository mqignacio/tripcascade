"""Download and load US DOT BTS On-Time Performance data.

Source: https://transtats.bts.gov/PREZIP/
License: Public domain (US Government work).
Columns of interest:
    Year, Month, DayOfWeek, CRSDepTime, IATA_CODE_Reporting_Airline,
    Origin, Dest, DepDelay, Cancelled, Diverted, CRSElapsedTime, Distance,
    FlightDate
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

BTS_BASE_URL = "https://transtats.bts.gov/PREZIP/"
DATA_DIR = Path(__file__).resolve().parents[3] / "data"

# Columns we actually need (avoids loading all 110, skips trailing unnamed col)
USE_COLS = [
    "Year",
    "Month",
    "DayOfWeek",
    "FlightDate",
    "IATA_CODE_Reporting_Airline",
    "Origin",
    "Dest",
    "CRSDepTime",
    "DepDelay",
    "Cancelled",
    "Diverted",
    "CRSElapsedTime",
    "Distance",
]


def bts_url(year: int, month: int) -> str:
    """Return the BTS download URL for a given year and month (1-12)."""
    return f"{BTS_BASE_URL}On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip"


def _find_csv(year: int, month: int) -> Path:
    """Find the unzipped CSV file for a given year/month."""
    suffix = f"_{year}_{month}.csv"
    candidates = [f for f in DATA_DIR.iterdir() if f.suffix == ".csv" and f.name.endswith(suffix)]
    if not candidates:
        raise FileNotFoundError(f"No CSV found for {year}-{month:02d} in {DATA_DIR}")
    return candidates[0]


def download_bts(year: int, month: int) -> Path:
    """Download a single month of BTS On-Time data.

    Returns the path to the extracted CSV.
    """
    import subprocess

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = DATA_DIR / f"otp_{year}_{month:02d}.zip"
    url = bts_url(year, month)

    if not zip_path.exists():
        logger.info("Downloading %s → %s", url, zip_path.name)
        subprocess.run(
            ["curl", "-sS", "-m", "300", "-o", str(zip_path), url],
            check=True,
        )

    # Unzip if not already
    csv_path = _find_csv(year, month)
    if not csv_path.exists():
        logger.info("Extracting %s", zip_path.name)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(DATA_DIR)
        csv_path = _find_csv(year, month)

    return csv_path


def load_months(year: int, months: list[int]) -> pd.DataFrame:
    """Load multiple months of BTS data into a single DataFrame.

    Args:
        year: 4-digit year (e.g. 2024).
        months: list of month numbers (1-12).

    Returns:
        DataFrame with the columns from USE_COLS, one row per flight.
    """
    frames = []
    for m in months:
        path = download_bts(year, m)
        logger.info("Loading %s (%.1f MB)", path.name, path.stat().st_size / 1e6)
        df = pd.read_csv(path, usecols=USE_COLS)
        frames.append(df)

    data = pd.concat(frames, ignore_index=True)
    logger.info("Loaded %d rows from %d months of %d", len(data), len(months), year)
    return data


def load_local(year: int, months: list[int]) -> pd.DataFrame:
    """Load from already-downloaded CSVs (no network).

    Use this in tests / repeated runs where data is cached on disk.
    """
    frames = []
    for m in months:
        path = _find_csv(year, m)
        df = pd.read_csv(path, usecols=USE_COLS)
        frames.append(df)

    data = pd.concat(frames, ignore_index=True)
    logger.info("Loaded %d rows from local %d months of %d", len(data), len(months), year)
    return data
