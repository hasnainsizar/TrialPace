from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from trialpace.db import read_table

TABLE_DESCRIPTIONS = {
    "dim_trial": "one row per trial from the latest snapshot",
    "dim_sponsor": "one row per canonical sponsor",
    "dim_date": "daily calendar spanning every trial and forecast date",
    "fact_site": "one row per trial per site per snapshot",
    "fact_forecast": "one row per active trial with a forecast",
    "fact_benchmark": "one row per completed benchmark trial",
}


def _date_str(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.strftime("%Y-%m-%d")


def build_dim_sponsor(trials: pd.DataFrame, sponsor_cfg: dict[str, Any]) -> pd.DataFrame:
    names = list(sponsor_cfg.get("mapping", {}).keys()) + [str(sponsor_cfg.get("default", "Other"))]
    extra = sorted(set(trials["sponsor"]) - set(names)) if not trials.empty else []
    rows = [{"sponsor_key": i + 1, "sponsor": name, "is_edwards": int("edwards" in name.lower())} for i, name in enumerate(names + extra)]
    return pd.DataFrame(rows, columns=["sponsor_key", "sponsor", "is_edwards"])


def build_dim_date(frames: list[pd.DataFrame], today: date) -> pd.DataFrame:
    values: list[pd.Series] = []
    for frame in frames:
        for column in frame.columns:
            if pd.api.types.is_datetime64_any_dtype(frame[column]):
                values.append(frame[column].dropna())
    if not values:
        start = end = pd.Timestamp(today)
    else:
        combined = pd.concat(values)
        start, end = combined.min().normalize(), combined.max().normalize()
    calendar = pd.date_range(min(start, pd.Timestamp(today)), max(end, pd.Timestamp(today)), freq="D")
    return pd.DataFrame(
        {
            "date": calendar.strftime("%Y-%m-%d"),
            "year": calendar.year,
            "quarter": calendar.quarter,
            "month": calendar.month,
            "month_name": calendar.strftime("%b"),
            "year_month": calendar.strftime("%Y-%m"),
            "year_quarter": calendar.year.astype(str) + "-Q" + calendar.quarter.astype(str),
        }
    )


def export_powerbi(conn: sqlite3.Connection, snapshot: date, config: dict[str, Any], out_dir: Path) -> dict[str, int]:
    """Write the star schema CSVs. Returns row counts per table."""
    out_dir.mkdir(parents=True, exist_ok=True)
    trials = read_table(conn, "trials", snapshot)
    sites_all = read_table(conn, "sites")
    forecasts = read_table(conn, "forecasts", snapshot)
    benchmarks = read_table(conn, "benchmarks", snapshot)
    dim_sponsor = build_dim_sponsor(trials, config["sponsors"])
    sponsor_keys = dict(zip(dim_sponsor["sponsor"], dim_sponsor["sponsor_key"]))

    dim_trial = trials.drop(columns=["snapshot_date"]).rename(columns={"lead_sponsor_raw": "sponsor_name"}).copy()
    dim_trial.insert(2, "sponsor_key", dim_trial["sponsor"].map(sponsor_keys))
    leading = ["nct_id", "title", "sponsor_key", "sponsor", "sponsor_name", "lead_sponsor_class"]
    dim_trial = dim_trial[leading + [c for c in dim_trial.columns if c not in leading]]
    for column in ("start_date", "primary_completion_date", "completion_date", "last_update_date"):
        dim_trial[column] = _date_str(dim_trial[column])

    fact_site = sites_all.copy()
    trial_sponsor = trials.set_index("nct_id")["sponsor"] if not trials.empty else pd.Series(dtype=str)
    fact_site["sponsor_key"] = fact_site["nct_id"].map(trial_sponsor).map(sponsor_keys)
    fact_site["site_count"] = 1

    fact_forecast = forecasts.drop(columns=["snapshot_date"]).copy()
    if not fact_forecast.empty:
        fact_forecast.insert(2, "sponsor_key", fact_forecast["sponsor"].map(sponsor_keys))
    for column in ("start_date", "date_p25", "date_median", "date_p75", "posted_primary_completion_date", "last_update_posted"):
        if column in fact_forecast.columns:
            fact_forecast[column] = _date_str(fact_forecast[column])

    fact_benchmark = benchmarks.drop(columns=["snapshot_date"]).copy()
    if not fact_benchmark.empty:
        fact_benchmark.insert(2, "sponsor_key", fact_benchmark["sponsor"].map(sponsor_keys))
    for column in ("start_date", "primary_completion_date"):
        if column in fact_benchmark.columns:
            fact_benchmark[column] = _date_str(fact_benchmark[column])

    dim_date = build_dim_date([trials, forecasts, benchmarks], snapshot)

    tables = {
        "dim_trial": dim_trial,
        "dim_sponsor": dim_sponsor,
        "dim_date": dim_date,
        "fact_site": fact_site,
        "fact_forecast": fact_forecast,
        "fact_benchmark": fact_benchmark,
    }
    counts: dict[str, int] = {}
    for name, frame in tables.items():
        frame.to_csv(out_dir / f"{name}.csv", index=False)
        counts[name] = len(frame)
    return counts
