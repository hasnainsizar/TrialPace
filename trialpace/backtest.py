from __future__ import annotations

from typing import Any

import pandas as pd

from trialpace.predictors import MODEL_NAIVE, MODEL_NAMES, make_predictor

PREDICTION_COLUMNS = [
    "model", "nct_id", "valve_type", "size_band", "actual_months",
    "pred_months_p25", "pred_months_median", "pred_months_p75", "abs_pct_error", "within_range",
]
COMPARISON_COLUMNS = ["model", "scored_n", "median_ape_pct", "mape_pct", "coverage_p25_p75_pct", "selected"]


def score_model(name: str, train: pd.DataFrame, holdout: pd.DataFrame, forecast_cfg: dict[str, Any]) -> pd.DataFrame:
    """Fit one model on train and predict every holdout trial. Empty when the model cannot fit."""
    predictor = make_predictor(name, forecast_cfg)
    if not predictor.fit(train):
        return pd.DataFrame(columns=PREDICTION_COLUMNS)
    rows: list[dict[str, Any]] = []
    for row in holdout.itertuples(index=False):
        pred = predictor.predict(int(row.enrollment_count), int(row.site_count), row.valve_type)
        actual = float(row.months)
        rows.append(
            {
                "model": name,
                "nct_id": row.nct_id,
                "valve_type": row.valve_type,
                "size_band": row.size_band,
                "actual_months": actual,
                "pred_months_p25": pred.months_p25,
                "pred_months_median": pred.months_median,
                "pred_months_p75": pred.months_p75,
                "abs_pct_error": abs(pred.months_median - actual) / actual * 100.0,
                "within_range": int(pred.months_p25 <= actual <= pred.months_p75),
            }
        )
    return pd.DataFrame(rows, columns=PREDICTION_COLUMNS)


def leave_one_out(benchmarks: pd.DataFrame, forecast_cfg: dict[str, Any]) -> pd.DataFrame:
    """Predict every benchmark trial from a model fitted on all the others."""
    frames: list[pd.DataFrame] = []
    for position in range(len(benchmarks)):
        holdout = benchmarks.iloc[[position]]
        train = benchmarks.drop(benchmarks.index[position])
        for name in MODEL_NAMES:
            frames.append(score_model(name, train, holdout, forecast_cfg))
    if not frames:
        return pd.DataFrame(columns=PREDICTION_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def compare_models(benchmarks: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Leave-one-out cross-validation of every model over the benchmark set.

    Returns (comparison table, per-trial predictions, sizes). The comparison marks
    the model with the lowest median absolute percentage error as selected.
    """
    forecast_cfg = config["forecast"]
    sizes = {"benchmark_count": len(benchmarks), "folds": len(benchmarks)}
    if len(benchmarks) < 2:
        return pd.DataFrame(columns=COMPARISON_COLUMNS), pd.DataFrame(columns=PREDICTION_COLUMNS), sizes

    predictions = leave_one_out(benchmarks, forecast_cfg)
    rows: list[dict[str, Any]] = []
    for name in MODEL_NAMES:
        scored = predictions[predictions["model"] == name]
        rows.append(
            {
                "model": name,
                "scored_n": len(scored),
                "median_ape_pct": float(scored["abs_pct_error"].median()) if len(scored) else None,
                "mape_pct": float(scored["abs_pct_error"].mean()) if len(scored) else None,
                "coverage_p25_p75_pct": float(scored["within_range"].mean() * 100.0) if len(scored) else None,
                "selected": 0,
            }
        )
    comparison = pd.DataFrame(rows, columns=COMPARISON_COLUMNS)
    selected = select_model(comparison, forecast_cfg)
    comparison["selected"] = (comparison["model"] == selected).astype(int)
    return comparison, predictions, sizes


def select_model(comparison: pd.DataFrame, forecast_cfg: dict[str, Any]) -> str:
    """Honor a configured model, otherwise pick the lowest median error. Naive wins ties."""
    configured = str(forecast_cfg.get("model", "auto"))
    if configured != "auto":
        return configured
    scored = comparison.dropna(subset=["median_ape_pct"])
    if scored.empty:
        return MODEL_NAIVE
    best = scored["median_ape_pct"].min()
    tied = scored[scored["median_ape_pct"] == best]["model"].tolist()
    return MODEL_NAIVE if MODEL_NAIVE in tied else tied[0]


def duration_by_valve(benchmarks: pd.DataFrame) -> pd.DataFrame:
    """Median and quartile months from start to primary completion per valve type."""
    columns = ["valve_type", "n", "months_p25", "months_median", "months_p75"]
    if benchmarks.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for valve, group in benchmarks.groupby("valve_type"):
        months = group["months"]
        rows.append({"valve_type": valve, "n": len(group), "months_p25": float(months.quantile(0.25)), "months_median": float(months.median()), "months_p75": float(months.quantile(0.75))})
    rows.append({"valve_type": "all", "n": len(benchmarks), "months_p25": float(benchmarks["months"].quantile(0.25)), "months_median": float(benchmarks["months"].median()), "months_p75": float(benchmarks["months"].quantile(0.75))})
    return pd.DataFrame(rows, columns=columns)
