from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from trialpace.forecast import (
    OVERALL_KEY,
    RateQuantiles,
    add_months,
    build_forecasts,
    classify_status,
    forecast_months,
    label_status,
    lookup_rate,
    segment_rates,
)
from trialpace.predictors import RatePredictor


def _rate_predictor(config: dict) -> RatePredictor:
    predictor = RatePredictor(config["forecast"])
    predictor.rates = {OVERALL_KEY: RateQuantiles(p25=0.5, p50=1.0, p75=2.0, n=10, source="overall")}
    return predictor


def test_forecast_months_orders_fast_to_slow() -> None:
    rates = RateQuantiles(p25=0.5, p50=1.0, p75=2.0, n=10, source="segment")
    m25, m50, m75 = forecast_months(target=120, sites=6, rates=rates)
    assert m25 == pytest.approx(10.0)
    assert m50 == pytest.approx(20.0)
    assert m75 == pytest.approx(40.0)
    assert m25 <= m50 <= m75


def test_add_months_rounds_to_days() -> None:
    assert add_months(date(2024, 1, 1), 12.0, 30.4375) == date(2024, 12, 31)


def test_segment_rates_falls_back_when_segment_is_small() -> None:
    benchmarks = pd.DataFrame(
        {
            "valve_type": ["aortic"] * 5 + ["mitral"] * 2,
            "size_band": ["small"] * 7,
            "rate_per_site_month": [1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 20.0],
        }
    )
    rates = segment_rates(benchmarks, min_segment_count=5)
    assert ("aortic", "small") in rates
    assert ("mitral", "small") not in rates
    assert rates[("aortic", "small")].p50 == pytest.approx(3.0)
    assert lookup_rate(rates, "mitral", "small") is rates[OVERALL_KEY]
    assert rates[OVERALL_KEY].n == 7


@pytest.mark.parametrize(
    ("gap", "expected"),
    [(-400, "On track"), (0, "On track"), (90, "On track"), (91, "Behind forecast"), (366, "Behind forecast"), (None, "On track")],
)
def test_label_status_thresholds(gap: int | None, expected: str, config: dict) -> None:
    assert label_status(gap, config["forecast"]) == expected


def test_build_forecasts_produces_range_and_label(config: dict) -> None:
    trials = pd.DataFrame(
        [
            {
                "nct_id": "NCT9", "sponsor_group": "Abbott", "overall_status": "RECRUITING", "valve_type": "mitral",
                "enrollment_count": 120, "site_count": 6, "start_date": pd.Timestamp("2024-01-01"),
                "primary_completion_date": pd.Timestamp("2025-01-01"), "primary_completion_type": "ESTIMATED",
                "last_update_date": pd.Timestamp("2024-06-01"), "is_stale": 1,
            },
            {
                "nct_id": "NCT10", "sponsor_group": "Other", "overall_status": "RECRUITING", "valve_type": "aortic",
                "enrollment_count": 50, "site_count": 0, "start_date": pd.Timestamp("2024-01-01"),
                "primary_completion_date": pd.NaT, "primary_completion_type": None,
                "last_update_date": pd.NaT, "is_stale": None,
            },
        ]
    )
    forecasts, exclusions = build_forecasts(trials, _rate_predictor(config), config["forecast"], date(2024, 6, 1))
    assert len(forecasts) == 1
    row = forecasts.iloc[0]
    assert row["model"] == "rate"
    assert row["basis"] == "rate:overall"
    assert row["date_p25"] < row["date_median"] < row["date_p75"]
    assert row["months_median"] == pytest.approx(20.0)
    assert row["gap_days"] == (row["date_median"] - pd.Timestamp("2025-01-01")).days
    assert row["status_label"] == "Behind forecast"
    assert row["is_stale"] == 1
    assert exclusions.iloc[0]["reason"] == "no sites listed"


def test_build_forecasts_excludes_trials_beyond_horizon(config: dict) -> None:
    trials = pd.DataFrame(
        [
            {
                "nct_id": "NCT11", "sponsor_group": "Other", "overall_status": "RECRUITING", "valve_type": "aortic",
                "enrollment_count": 3000, "site_count": 1, "start_date": pd.Timestamp("2024-01-01"),
                "primary_completion_date": pd.NaT, "primary_completion_type": None,
                "last_update_date": pd.NaT, "is_stale": None,
            }
        ]
    )
    forecasts, exclusions = build_forecasts(trials, _rate_predictor(config), config["forecast"], date(2024, 6, 1))
    assert forecasts.empty
    assert "horizon" in exclusions.iloc[0]["reason"]


SNAPSHOT = date(2026, 9, 21)


def test_classify_overdue_takes_priority(config: dict) -> None:
    posted = date(2026, 1, 1)
    assert classify_status(posted, date(2027, 6, 1), SNAPSHOT, config["forecast"]) == "Overdue"
    assert classify_status(posted, date(2025, 6, 1), SNAPSHOT, config["forecast"]) == "Overdue"


def test_classify_behind_forecast_when_median_is_behind_snapshot(config: dict) -> None:
    assert classify_status(date(2027, 6, 1), date(2026, 3, 1), SNAPSHOT, config["forecast"]) == "Behind forecast"
    assert classify_status(None, date(2026, 3, 1), SNAPSHOT, config["forecast"]) == "Behind forecast"


def test_classify_falls_through_to_gap_threshold(config: dict) -> None:
    posted = date(2027, 1, 1)
    assert classify_status(posted, date(2026, 12, 1), SNAPSHOT, config["forecast"]) == "On track"
    assert classify_status(posted, date(2027, 3, 1), SNAPSHOT, config["forecast"]) == "On track"
    assert classify_status(posted, date(2027, 7, 1), SNAPSHOT, config["forecast"]) == "Behind forecast"
    assert classify_status(posted, date(2028, 6, 1), SNAPSHOT, config["forecast"]) == "Behind forecast"
    assert classify_status(None, date(2027, 1, 1), SNAPSHOT, config["forecast"]) == "On track"


def test_classify_dates_equal_to_snapshot_are_not_past(config: dict) -> None:
    assert classify_status(SNAPSHOT, SNAPSHOT, SNAPSHOT, config["forecast"]) == "On track"


def test_build_forecasts_labels_trials_past_their_dates(config: dict) -> None:
    trials = pd.DataFrame(
        [
            {
                "nct_id": "OVERDUE", "sponsor_group": "Other", "overall_status": "RECRUITING", "valve_type": "aortic",
                "enrollment_count": 120, "site_count": 6, "start_date": pd.Timestamp("2026-01-01"),
                "primary_completion_date": pd.Timestamp("2026-06-01"), "primary_completion_type": "ESTIMATED",
                "last_update_date": pd.NaT, "is_stale": None,
            },
            {
                "nct_id": "BEHIND", "sponsor_group": "Other", "overall_status": "RECRUITING", "valve_type": "aortic",
                "enrollment_count": 12, "site_count": 6, "start_date": pd.Timestamp("2024-01-01"),
                "primary_completion_date": pd.Timestamp("2027-06-01"), "primary_completion_type": "ESTIMATED",
                "last_update_date": pd.NaT, "is_stale": None,
            },
            {
                "nct_id": "OVERDUE_AND_BEHIND", "sponsor_group": "Other", "overall_status": "ACTIVE_NOT_RECRUITING", "valve_type": "aortic",
                "enrollment_count": 12, "site_count": 6, "start_date": pd.Timestamp("2020-01-01"),
                "primary_completion_date": pd.Timestamp("2021-01-01"), "primary_completion_type": "ESTIMATED",
                "last_update_date": pd.NaT, "is_stale": None,
            },
        ]
    )
    forecasts, _ = build_forecasts(trials, _rate_predictor(config), config["forecast"], SNAPSHOT)
    labels = forecasts.set_index("nct_id")["status_label"]
    assert labels["OVERDUE"] == "Overdue"
    assert labels["BEHIND"] == "Behind forecast"
    assert labels["OVERDUE_AND_BEHIND"] == "Overdue"
    medians = forecasts.set_index("nct_id")["date_median"]
    assert medians["BEHIND"] < pd.Timestamp(SNAPSHOT)
    assert medians["OVERDUE"] > pd.Timestamp(SNAPSHOT)


def test_active_trial_with_actual_primary_completion_is_not_forecast(config: dict) -> None:
    trials = pd.DataFrame(
        [
            {
                "nct_id": "DONE", "sponsor_group": "Medtronic", "overall_status": "ACTIVE_NOT_RECRUITING", "valve_type": "aortic",
                "enrollment_count": 300, "site_count": 20, "start_date": pd.Timestamp("2021-01-01"),
                "primary_completion_date": pd.Timestamp("2024-01-01"), "primary_completion_type": "ACTUAL",
                "last_update_date": pd.Timestamp("2026-01-01"), "is_stale": 0,
            },
            {
                "nct_id": "LIVE", "sponsor_group": "Medtronic", "overall_status": "RECRUITING", "valve_type": "aortic",
                "enrollment_count": 120, "site_count": 6, "start_date": pd.Timestamp("2026-01-01"),
                "primary_completion_date": pd.Timestamp("2027-10-01"), "primary_completion_type": "ESTIMATED",
                "last_update_date": pd.NaT, "is_stale": None,
            },
        ]
    )
    forecasts, exclusions = build_forecasts(trials, _rate_predictor(config), config["forecast"], SNAPSHOT)
    assert exclusions.empty
    by_id = forecasts.set_index("nct_id")
    done = by_id.loc["DONE"]
    assert done["status_label"] == "Primary completion reached"
    assert done["model"] == "none"
    assert pd.isna(done["date_median"]) and pd.isna(done["months_median"]) and pd.isna(done["gap_days"])
    assert done["posted_primary_completion_date"] == pd.Timestamp("2024-01-01")
    assert done["is_stale"] == 0
    assert by_id.loc["LIVE", "status_label"] == "On track"
    assert not set(forecasts["status_label"]) & {"Overdue", "Behind forecast"}
