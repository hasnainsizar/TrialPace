from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd

OVERALL_KEY = ("all", "all")


@dataclass(frozen=True)
class RateQuantiles:
    p25: float
    p50: float
    p75: float
    n: int
    source: str


def months_between(start: date, end: date, days_per_month: float) -> float:
    return (end - start).days / days_per_month


def enrollment_rate(enrollment: int | None, sites: int, months: float) -> float | None:
    """Patients per site per month. None when any input cannot support a rate."""
    if enrollment is None or enrollment <= 0 or sites <= 0 or months <= 0:
        return None
    return enrollment / sites / months


def size_band(enrollment: int, bands: list[dict[str, Any]]) -> str:
    for band in bands:
        limit = band.get("max_enrollment")
        if limit is None or enrollment <= limit:
            return str(band["name"])
    return str(bands[-1]["name"])


def build_benchmarks(trials: pd.DataFrame, forecast_cfg: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Select benchmark trials and compute their rates. Returns (benchmarks, exclusions)."""
    columns = [
        "nct_id", "sponsor_group", "overall_status", "valve_type", "size_band", "enrollment_count", "site_count",
        "start_date", "primary_completion_date", "months", "rate_per_site_month",
    ]
    if trials.empty:
        return pd.DataFrame(columns=columns), pd.DataFrame(columns=["nct_id", "reason"])

    days_per_month = float(forecast_cfg["days_per_month"])
    min_months = float(forecast_cfg["min_months"])
    min_sites = int(forecast_cfg["min_benchmark_sites"])
    candidates = trials[benchmark_candidate_mask(trials, forecast_cfg)]
    rows: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for row in candidates.itertuples(index=False):
        reason = _benchmark_exclusion(row, min_months, min_sites, days_per_month)
        if reason:
            exclusions.append({"nct_id": row.nct_id, "reason": reason})
            continue
        months = months_between(row.start_date.date(), row.primary_completion_date.date(), days_per_month)
        enrollment = int(row.enrollment_count)
        rate = enrollment_rate(enrollment, int(row.site_count), months)
        rows.append(
            {
                "nct_id": row.nct_id,
                "sponsor_group": row.sponsor_group,
                "overall_status": row.overall_status,
                "valve_type": row.valve_type,
                "size_band": size_band(enrollment, forecast_cfg["size_bands"]),
                "enrollment_count": enrollment,
                "site_count": int(row.site_count),
                "start_date": row.start_date,
                "primary_completion_date": row.primary_completion_date,
                "months": months,
                "rate_per_site_month": rate,
            }
        )
    return pd.DataFrame(rows, columns=columns), pd.DataFrame(exclusions, columns=["nct_id", "reason"])


def reached_primary_completion(trials: pd.DataFrame) -> pd.Series:
    """Active trials whose primary completion date is ACTUAL have finished enrolling."""
    return trials["primary_completion_type"] == "ACTUAL"


def benchmark_candidate_mask(trials: pd.DataFrame, forecast_cfg: dict[str, Any]) -> pd.Series:
    completed = trials["overall_status"].isin(forecast_cfg["benchmark_statuses"])
    active_done = trials["overall_status"].isin(forecast_cfg["active_statuses"]) & reached_primary_completion(trials)
    return completed | active_done


def _benchmark_exclusion(row: Any, min_months: float, min_sites: int, days_per_month: float) -> str | None:
    if row.enrollment_type != "ACTUAL":
        return "enrollment type is not ACTUAL"
    if pd.isna(row.enrollment_count) or int(row.enrollment_count) <= 0:
        return "enrollment count missing or zero"
    if pd.isna(row.start_date):
        return "start date missing"
    if pd.isna(row.primary_completion_date):
        return "primary completion date missing"
    if row.primary_completion_type != "ACTUAL":
        return "primary completion date is not ACTUAL"
    if int(row.site_count) <= 0:
        return "no sites listed"
    if int(row.site_count) < min_sites:
        return f"fewer than {min_sites} sites listed"
    months = months_between(row.start_date.date(), row.primary_completion_date.date(), days_per_month)
    if months < min_months:
        return f"duration under {min_months} months"
    return None


def segment_rates(benchmarks: pd.DataFrame, min_segment_count: int) -> dict[tuple[str, str], RateQuantiles]:
    """Quantile rates per (valve_type, size_band), plus the overall fallback."""
    if benchmarks.empty:
        return {}
    rates = benchmarks["rate_per_site_month"]
    result = {
        OVERALL_KEY: RateQuantiles(
            float(rates.quantile(0.25)), float(rates.quantile(0.5)), float(rates.quantile(0.75)),
            len(benchmarks), "overall",
        )
    }
    for (valve, band), group in benchmarks.groupby(["valve_type", "size_band"]):
        values = group["rate_per_site_month"]
        if len(values) >= min_segment_count:
            result[(str(valve), str(band))] = RateQuantiles(
                float(values.quantile(0.25)), float(values.quantile(0.5)), float(values.quantile(0.75)),
                len(values), "segment",
            )
    return result


def lookup_rate(rates: dict[tuple[str, str], RateQuantiles], valve_type: str, band: str) -> RateQuantiles:
    return rates.get((valve_type, band), rates[OVERALL_KEY])


def rates_frame(rates: dict[tuple[str, str], RateQuantiles]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"valve_type": k[0], "size_band": k[1], "n": v.n, "rate_p25": v.p25, "rate_p50": v.p50, "rate_p75": v.p75, "source": v.source}
            for k, v in rates.items()
        ],
        columns=["valve_type", "size_band", "n", "rate_p25", "rate_p50", "rate_p75", "source"],
    )


def forecast_months(target: int, sites: int, rates: RateQuantiles) -> tuple[float, float, float]:
    """Months to target as (fast P25, median, slow P75). Faster rates give earlier dates."""
    capacity_high = sites * rates.p75
    capacity_mid = sites * rates.p50
    capacity_low = sites * rates.p25
    return target / capacity_high, target / capacity_mid, target / capacity_low


def add_months(start: date, months: float, days_per_month: float) -> date:
    return start + timedelta(days=round(months * days_per_month))


def classify_status(posted: date | None, forecast_median: date, snapshot: date, forecast_cfg: dict[str, Any]) -> str:
    """Status for an active trial. A posted date already behind the snapshot is Overdue;
    a median forecast already behind the snapshot is Behind forecast; otherwise the gap decides."""
    labels = forecast_cfg["labels"]
    if posted is not None and posted < snapshot:
        return str(labels["overdue"])
    if forecast_median < snapshot:
        return str(labels["behind_forecast"])
    gap = (forecast_median - posted).days if posted else None
    return label_status(gap, forecast_cfg)


def label_status(gap_days: int | None, forecast_cfg: dict[str, Any]) -> str:
    """Gap-threshold label only. A missing gap (no posted date) cannot show a delay, so it is On track."""
    labels = forecast_cfg["labels"]
    if gap_days is None or gap_days <= int(forecast_cfg["status_thresholds"]["on_track_max_days"]):
        return str(labels["on_track"])
    return str(labels["behind_forecast"])


FORECAST_COLUMNS = [
    "nct_id", "sponsor_group", "overall_status", "valve_type", "size_band", "target_enrollment", "site_count",
    "start_date", "model", "basis", "months_p25", "months_median", "months_p75",
    "date_p25", "date_median", "date_p75", "posted_primary_completion_date",
    "posted_primary_completion_type", "gap_days", "status_label", "last_update_posted", "is_stale",
]


HORIZON_REASON = "median forecast exceeds the {horizon:.0f} month horizon"


def build_forecasts(
    trials: pd.DataFrame,
    predictor: Any,
    forecast_cfg: dict[str, Any],
    snapshot: date,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Forecast every active trial with a fitted predictor as of the snapshot date. Returns (forecasts, exclusions)."""
    if trials.empty or predictor is None:
        return pd.DataFrame(columns=FORECAST_COLUMNS), pd.DataFrame(columns=["nct_id", "reason"])
    days_per_month = float(forecast_cfg["days_per_month"])
    max_horizon = float(forecast_cfg["max_horizon_months"])
    active = trials[trials["overall_status"].isin(forecast_cfg["active_statuses"])]
    rows: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    labels = forecast_cfg["labels"]
    for row in active.itertuples(index=False):
        if row.primary_completion_type == "ACTUAL":
            rows.append(_completed_row(row, str(labels["finished_enrolling"])))
            continue
        if pd.isna(row.enrollment_count) or int(row.enrollment_count) <= 0:
            exclusions.append({"nct_id": row.nct_id, "reason": "target enrollment missing or zero"})
            continue
        if int(row.site_count) <= 0:
            exclusions.append({"nct_id": row.nct_id, "reason": "no sites listed"})
            continue
        if pd.isna(row.start_date):
            exclusions.append({"nct_id": row.nct_id, "reason": "start date missing"})
            continue
        target = int(row.enrollment_count)
        sites = int(row.site_count)
        band = size_band(target, forecast_cfg["size_bands"])
        prediction = predictor.predict(target, sites, row.valve_type)
        m25, m50, m75 = prediction.months_p25, prediction.months_median, prediction.months_p75
        if m50 > max_horizon:
            exclusions.append({"nct_id": row.nct_id, "reason": HORIZON_REASON.format(horizon=max_horizon)})
            continue
        start = row.start_date.date()
        d25, d50, d75 = (add_months(start, m, days_per_month) for m in (m25, m50, m75))
        posted = None if pd.isna(row.primary_completion_date) else row.primary_completion_date.date()
        gap = (d50 - posted).days if posted else None
        rows.append(
            {
                "nct_id": row.nct_id,
                "sponsor_group": row.sponsor_group,
                "overall_status": row.overall_status,
                "valve_type": row.valve_type,
                "size_band": band,
                "target_enrollment": target,
                "site_count": sites,
                "start_date": pd.Timestamp(start),
                "model": predictor.name,
                "basis": prediction.basis,
                "months_p25": m25,
                "months_median": m50,
                "months_p75": m75,
                "date_p25": pd.Timestamp(d25),
                "date_median": pd.Timestamp(d50),
                "date_p75": pd.Timestamp(d75),
                "posted_primary_completion_date": pd.Timestamp(posted) if posted else pd.NaT,
                "posted_primary_completion_type": row.primary_completion_type,
                "gap_days": gap,
                "status_label": classify_status(posted, d50, snapshot, forecast_cfg),
                "last_update_posted": row.last_update_date,
                "is_stale": None if pd.isna(row.is_stale) else int(row.is_stale),
            }
        )
    return pd.DataFrame(rows, columns=FORECAST_COLUMNS), pd.DataFrame(exclusions, columns=["nct_id", "reason"])


def _completed_row(row: Any, label: str) -> dict[str, Any]:
    """A forecast-table row for an active trial that already reached primary completion."""
    posted = None if pd.isna(row.primary_completion_date) else row.primary_completion_date
    return {
        "nct_id": row.nct_id,
        "sponsor_group": row.sponsor_group,
        "overall_status": row.overall_status,
        "valve_type": row.valve_type,
        "size_band": None,
        "target_enrollment": None if pd.isna(row.enrollment_count) else int(row.enrollment_count),
        "site_count": int(row.site_count),
        "start_date": row.start_date,
        "model": "none",
        "basis": "primary completion date is ACTUAL; enrollment finished",
        "months_p25": None,
        "months_median": None,
        "months_p75": None,
        "date_p25": pd.NaT,
        "date_median": pd.NaT,
        "date_p75": pd.NaT,
        "posted_primary_completion_date": posted if posted is not None else pd.NaT,
        "posted_primary_completion_type": row.primary_completion_type,
        "gap_days": None,
        "status_label": label,
        "last_update_posted": row.last_update_date,
        "is_stale": None if pd.isna(row.is_stale) else int(row.is_stale),
    }
