from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from trialpace.forecast import build_benchmarks, enrollment_rate, months_between, size_band


def test_rate_is_enrollment_per_site_per_month() -> None:
    assert enrollment_rate(240, 5, 24.0) == pytest.approx(2.0)


@pytest.mark.parametrize(("enrollment", "sites", "months"), [(100, 0, 12.0), (100, 5, 0.0), (0, 5, 12.0), (None, 5, 12.0), (100, 5, -3.0)])
def test_rate_is_none_for_degenerate_inputs(enrollment: int | None, sites: int, months: float) -> None:
    assert enrollment_rate(enrollment, sites, months) is None


def test_months_between_uses_configured_month_length() -> None:
    assert months_between(date(2020, 1, 1), date(2020, 12, 31), 30.4375) == pytest.approx(365 / 30.4375)


def test_size_band_boundaries(config: dict) -> None:
    bands = config["forecast"]["size_bands"]
    assert size_band(100, bands) == "small"
    assert size_band(101, bands) == "medium"
    assert size_band(500, bands) == "medium"
    assert size_band(5000, bands) == "large"


def _trial(nct_id: str, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "nct_id": nct_id,
        "sponsor_group": "Other",
        "valve_type": "aortic",
        "overall_status": "COMPLETED",
        "enrollment_count": 240,
        "enrollment_type": "ACTUAL",
        "site_count": 5,
        "start_date": pd.Timestamp("2015-01-01"),
        "primary_completion_date": pd.Timestamp("2017-01-01"),
        "primary_completion_type": "ACTUAL",
    }
    base.update(overrides)
    return base


def test_build_benchmarks_excludes_zero_sites_and_zero_months(config: dict) -> None:
    trials = pd.DataFrame(
        [
            _trial("NCT1"),
            _trial("NCT2", site_count=0),
            _trial("NCT6", site_count=4),
            _trial("NCT3", primary_completion_date=pd.Timestamp("2015-01-01")),
            _trial("NCT4", enrollment_type="ESTIMATED"),
            _trial("NCT5", overall_status="RECRUITING"),
            _trial("NCT7", overall_status="RECRUITING", primary_completion_type="ESTIMATED"),
        ]
    )
    benchmarks, exclusions = build_benchmarks(trials, config["forecast"])
    assert list(benchmarks["nct_id"]) == ["NCT1", "NCT5"]
    assert benchmarks.set_index("nct_id").loc["NCT5", "overall_status"] == "RECRUITING"
    assert benchmarks.iloc[0]["rate_per_site_month"] == pytest.approx(240 / 5 / (731 / 30.4375))
    reasons = dict(zip(exclusions["nct_id"], exclusions["reason"]))
    assert reasons["NCT2"] == "no sites listed"
    assert reasons["NCT6"] == "fewer than 5 sites listed"
    assert "months" in reasons["NCT3"]
    assert "ACTUAL" in reasons["NCT4"]
    assert "NCT5" not in reasons
    assert "NCT7" not in reasons
