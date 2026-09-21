from __future__ import annotations

from typing import Any

import pandas as pd

from trialpace.forecast import forecast_months, lookup_rate, segment_rates

PREDICTION_COLUMNS = [
    "nct_id", "valve_type", "size_band", "actual_months",
    "pred_months_p25", "pred_months_median", "pred_months_p75", "abs_pct_error", "within_range",
]


def split_holdout(benchmarks: pd.DataFrame, fraction: float, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    shuffled = benchmarks.sample(frac=1.0, random_state=seed)
    holdout_size = int(round(len(shuffled) * fraction))
    return shuffled.iloc[holdout_size:], shuffled.iloc[:holdout_size]


def run_backtest(benchmarks: pd.DataFrame, config: dict[str, Any]) -> tuple[dict[str, float | None], pd.DataFrame]:
    """Predict holdout durations from training-set rates. Returns (metrics, predictions)."""
    bt_cfg = config["backtest"]
    forecast_cfg = config["forecast"]
    train, holdout = split_holdout(benchmarks, float(bt_cfg["holdout_fraction"]), int(bt_cfg["random_seed"]))
    metrics: dict[str, float | None] = {
        "benchmark_count": float(len(benchmarks)),
        "train_count": float(len(train)),
        "holdout_count": float(len(holdout)),
        "mape_pct": None,
        "median_ape_pct": None,
        "coverage_p25_p75_pct": None,
    }
    if train.empty or holdout.empty:
        return metrics, pd.DataFrame(columns=PREDICTION_COLUMNS)

    rates = segment_rates(train, int(forecast_cfg["min_segment_count"]))
    rows: list[dict[str, Any]] = []
    for row in holdout.itertuples(index=False):
        quantiles = lookup_rate(rates, row.valve_type, row.size_band)
        m25, m50, m75 = forecast_months(int(row.enrollment_count), int(row.site_count), quantiles)
        actual = float(row.months)
        rows.append(
            {
                "nct_id": row.nct_id,
                "valve_type": row.valve_type,
                "size_band": row.size_band,
                "actual_months": actual,
                "pred_months_p25": m25,
                "pred_months_median": m50,
                "pred_months_p75": m75,
                "abs_pct_error": abs(m50 - actual) / actual * 100.0,
                "within_range": int(m25 <= actual <= m75),
            }
        )
    predictions = pd.DataFrame(rows, columns=PREDICTION_COLUMNS)
    metrics["mape_pct"] = float(predictions["abs_pct_error"].mean())
    metrics["median_ape_pct"] = float(predictions["abs_pct_error"].median())
    metrics["coverage_p25_p75_pct"] = float(predictions["within_range"].mean() * 100.0)
    return metrics, predictions
