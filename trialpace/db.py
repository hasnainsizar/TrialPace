from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from trialpace.models import TrialRecord
from trialpace.scope import FilterStep

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_date TEXT PRIMARY KEY,
    loaded_at TEXT NOT NULL,
    trial_count INTEGER NOT NULL,
    site_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS trials (
    snapshot_date TEXT NOT NULL,
    nct_id TEXT NOT NULL,
    title TEXT,
    lead_sponsor_raw TEXT,
    lead_sponsor_class TEXT,
    sponsor TEXT NOT NULL,
    overall_status TEXT,
    phase TEXT,
    conditions TEXT,
    interventions TEXT,
    intervention_types TEXT,
    enrollment_count INTEGER,
    enrollment_type TEXT,
    start_date TEXT,
    primary_completion_date TEXT,
    primary_completion_type TEXT,
    completion_date TEXT,
    last_update_date TEXT,
    valve_type TEXT NOT NULL,
    site_count INTEGER NOT NULL,
    PRIMARY KEY (snapshot_date, nct_id)
);
CREATE TABLE IF NOT EXISTS sites (
    snapshot_date TEXT NOT NULL,
    nct_id TEXT NOT NULL,
    site_index INTEGER NOT NULL,
    facility TEXT,
    city TEXT,
    state TEXT,
    country TEXT,
    location_status TEXT,
    PRIMARY KEY (snapshot_date, nct_id, site_index)
);
CREATE TABLE IF NOT EXISTS scope_exclusions (
    snapshot_date TEXT NOT NULL,
    nct_id TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS filter_log (
    snapshot_date TEXT NOT NULL,
    step_order INTEGER NOT NULL,
    step TEXT NOT NULL,
    removed INTEGER NOT NULL,
    remaining INTEGER NOT NULL,
    PRIMARY KEY (snapshot_date, step_order)
);
CREATE TABLE IF NOT EXISTS data_quality (
    snapshot_date TEXT NOT NULL,
    nct_id TEXT NOT NULL,
    field TEXT NOT NULL,
    issue TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS benchmarks (
    snapshot_date TEXT NOT NULL,
    nct_id TEXT NOT NULL,
    sponsor TEXT NOT NULL,
    valve_type TEXT NOT NULL,
    size_band TEXT NOT NULL,
    enrollment_count INTEGER NOT NULL,
    site_count INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    primary_completion_date TEXT NOT NULL,
    months REAL NOT NULL,
    rate_per_site_month REAL NOT NULL,
    PRIMARY KEY (snapshot_date, nct_id)
);
CREATE TABLE IF NOT EXISTS segment_rates (
    snapshot_date TEXT NOT NULL,
    valve_type TEXT NOT NULL,
    size_band TEXT NOT NULL,
    n INTEGER NOT NULL,
    rate_p25 REAL NOT NULL,
    rate_p50 REAL NOT NULL,
    rate_p75 REAL NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, valve_type, size_band)
);
CREATE TABLE IF NOT EXISTS forecasts (
    snapshot_date TEXT NOT NULL,
    nct_id TEXT NOT NULL,
    sponsor TEXT NOT NULL,
    overall_status TEXT,
    valve_type TEXT NOT NULL,
    size_band TEXT NOT NULL,
    target_enrollment INTEGER NOT NULL,
    site_count INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    model TEXT NOT NULL,
    basis TEXT NOT NULL,
    months_p25 REAL NOT NULL,
    months_median REAL NOT NULL,
    months_p75 REAL NOT NULL,
    date_p25 TEXT NOT NULL,
    date_median TEXT NOT NULL,
    date_p75 TEXT NOT NULL,
    posted_primary_completion_date TEXT,
    posted_primary_completion_type TEXT,
    gap_days INTEGER,
    status_label TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, nct_id)
);
CREATE TABLE IF NOT EXISTS forecast_exclusions (
    snapshot_date TEXT NOT NULL,
    nct_id TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS horizon_checks (
    snapshot_date TEXT NOT NULL,
    model TEXT NOT NULL,
    fitted INTEGER NOT NULL,
    excluded_by_horizon INTEGER NOT NULL,
    PRIMARY KEY (snapshot_date, model)
);
CREATE TABLE IF NOT EXISTS backtest_results (
    snapshot_date TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (snapshot_date, metric)
);
CREATE TABLE IF NOT EXISTS model_comparison (
    snapshot_date TEXT NOT NULL,
    model TEXT NOT NULL,
    holdout_n INTEGER NOT NULL,
    median_ape_pct REAL,
    mape_pct REAL,
    coverage_p25_p75_pct REAL,
    selected INTEGER NOT NULL,
    PRIMARY KEY (snapshot_date, model)
);
CREATE TABLE IF NOT EXISTS backtest_predictions (
    snapshot_date TEXT NOT NULL,
    model TEXT NOT NULL,
    nct_id TEXT NOT NULL,
    valve_type TEXT NOT NULL,
    size_band TEXT NOT NULL,
    actual_months REAL NOT NULL,
    pred_months_p25 REAL NOT NULL,
    pred_months_median REAL NOT NULL,
    pred_months_p75 REAL NOT NULL,
    abs_pct_error REAL NOT NULL,
    within_range INTEGER NOT NULL,
    PRIMARY KEY (snapshot_date, model, nct_id)
);
"""

SNAPSHOT_TABLES = [
    "trials", "sites", "scope_exclusions", "filter_log", "data_quality", "benchmarks", "segment_rates",
    "forecasts", "forecast_exclusions", "horizon_checks", "model_comparison", "backtest_results", "backtest_predictions",
]


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def replace_snapshot(
    conn: sqlite3.Connection,
    snapshot: date,
    records: Iterable[TrialRecord],
    scope_exclusions: Iterable[tuple[str, str]] = (),
    filter_log: Iterable[FilterStep] = (),
) -> tuple[int, int, int]:
    """Replace one day's snapshot. Returns (trials, sites, issues) written."""
    day = snapshot.isoformat()
    records = list(records)
    with conn:
        for table in SNAPSHOT_TABLES:
            conn.execute(f"DELETE FROM {table} WHERE snapshot_date = ?", (day,))
        conn.execute("DELETE FROM snapshots WHERE snapshot_date = ?", (day,))
        trial_rows = [
            (
                day, r.nct_id, r.title, r.lead_sponsor_raw, r.lead_sponsor_class, r.sponsor, r.overall_status, r.phase,
                r.conditions, r.interventions, r.intervention_types, r.enrollment_count, r.enrollment_type,
                _iso(r.start_date), _iso(r.primary_completion_date), r.primary_completion_type,
                _iso(r.completion_date), _iso(r.last_update_date), r.valve_type, r.site_count,
            )
            for r in records
        ]
        conn.executemany(f"INSERT INTO trials VALUES ({','.join('?' * 20)})", trial_rows)
        conn.executemany("INSERT INTO scope_exclusions VALUES (?,?,?)", [(day, n, reason) for n, reason in scope_exclusions])
        conn.executemany(
            "INSERT INTO filter_log VALUES (?,?,?,?,?)",
            [(day, i, f.step, f.removed, f.remaining) for i, f in enumerate(filter_log)],
        )
        site_rows = [
            (day, s.nct_id, s.site_index, s.facility, s.city, s.state, s.country, s.location_status)
            for r in records for s in r.sites
        ]
        conn.executemany("INSERT INTO sites VALUES (?,?,?,?,?,?,?,?)", site_rows)
        issue_rows = [(day, i.nct_id, i.field, i.issue) for r in records for i in r.issues]
        conn.executemany("INSERT INTO data_quality VALUES (?,?,?,?)", issue_rows)
        conn.execute(
            "INSERT INTO snapshots VALUES (?,?,?,?)",
            (day, datetime.now(timezone.utc).isoformat(timespec="seconds"), len(trial_rows), len(site_rows)),
        )
    return len(trial_rows), len(site_rows), len(issue_rows)


def replace_rows(conn: sqlite3.Connection, table: str, snapshot: date, frame: pd.DataFrame) -> int:
    """Replace one snapshot's rows in a derived table with a DataFrame's rows."""
    day = snapshot.isoformat()
    with conn:
        conn.execute(f"DELETE FROM {table} WHERE snapshot_date = ?", (day,))
        if frame.empty:
            return 0
        out = frame.copy()
        out.insert(0, "snapshot_date", day)
        for column in out.columns:
            if pd.api.types.is_datetime64_any_dtype(out[column]):
                out[column] = out[column].dt.strftime("%Y-%m-%d")
        out = out.astype(object).where(out.notna(), None)
        placeholders = ",".join("?" * len(out.columns))
        conn.executemany(
            f"INSERT INTO {table} ({','.join(out.columns)}) VALUES ({placeholders})",
            out.itertuples(index=False, name=None),
        )
    return len(out)


def latest_snapshot(conn: sqlite3.Connection) -> date | None:
    row = conn.execute("SELECT MAX(snapshot_date) FROM snapshots").fetchone()
    return date.fromisoformat(row[0]) if row and row[0] else None


DATE_COLUMNS = {
    "start_date", "primary_completion_date", "completion_date", "last_update_date",
    "date_p25", "date_median", "date_p75", "posted_primary_completion_date",
}


def read_table(conn: sqlite3.Connection, table: str, snapshot: date | None = None) -> pd.DataFrame:
    query = f"SELECT * FROM {table}"
    params: tuple[Any, ...] = ()
    if snapshot is not None:
        query += " WHERE snapshot_date = ?"
        params = (snapshot.isoformat(),)
    frame = pd.read_sql_query(query, conn, params=params)
    for column in frame.columns:
        if column in DATE_COLUMNS:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame
