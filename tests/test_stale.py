from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from trialpace import db
from trialpace.forecast import OVERALL_KEY, RateQuantiles, build_forecasts
from trialpace.parse import parse_studies
from trialpace.predictors import RatePredictor
from trialpace.stale import is_stale, stale_cutoff


def test_stale_cutoff_is_twelve_months_before_snapshot(config: dict[str, Any]) -> None:
    snapshot = date(2026, 9, 21)
    cutoff = stale_cutoff(snapshot, config["forecast"])
    assert cutoff == snapshot - timedelta(days=round(12 * 30.4375))


def test_stale_flag_threshold(config: dict[str, Any]) -> None:
    snapshot = date(2026, 9, 21)
    cutoff = stale_cutoff(snapshot, config["forecast"])
    assert is_stale(cutoff - timedelta(days=1), snapshot, config["forecast"]) == 1
    assert is_stale(cutoff, snapshot, config["forecast"]) == 0
    assert is_stale(snapshot, snapshot, config["forecast"]) == 0
    assert is_stale(None, snapshot, config["forecast"]) is None


def test_stale_threshold_comes_from_config(config: dict[str, Any]) -> None:
    snapshot = date(2026, 9, 21)
    short = dict(config["forecast"], stale_after_months=1)
    assert is_stale(snapshot - timedelta(days=45), snapshot, short) == 1
    assert is_stale(snapshot - timedelta(days=45), snapshot, config["forecast"]) == 0


def test_stale_flag_is_stored_and_carried_into_forecasts(tmp_path: Path, config: dict[str, Any], sample_studies: list[dict[str, Any]]) -> None:
    records, _ = parse_studies(sample_studies, config)
    snapshot = date(2026, 1, 15)
    for record in records:
        record.is_stale = is_stale(record.last_update_date, snapshot, config["forecast"])
    conn = db.connect(tmp_path / "test.db")
    db.replace_snapshot(conn, snapshot, records)
    trials = db.read_table(conn, "trials", snapshot).set_index("nct_id")
    assert trials.loc["NCT00000001", "is_stale"] == 1
    assert trials.loc["NCT00000002", "is_stale"] == 0
    assert pd.isna(trials.loc["NCT00000003", "is_stale"])

    predictor = RatePredictor(config["forecast"])
    predictor.rates = {OVERALL_KEY: RateQuantiles(p25=0.5, p50=1.0, p75=2.0, n=10, source="overall")}
    forecasts, _ = build_forecasts(trials.reset_index(), predictor, config["forecast"], snapshot)
    row = forecasts.set_index("nct_id").loc["NCT00000002"]
    assert row["is_stale"] == 0
    assert row["last_update_posted"] == pd.Timestamp("2025-08-01")
