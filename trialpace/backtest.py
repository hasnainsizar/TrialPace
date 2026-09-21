from __future__ import annotations

from typing import Any

import pandas as pd

from trialpace.predictors import MODEL_NAIVE, MODEL_NAMES, make_predictor

PREDICTION_COLUMNS = [
    "model", "nct_id", "valve_type", "size_band", "actual_months",
    "pred_months_p25", "pred_months_median", "pred_months_p75", "abs_pct_error", "within_range",
]
COMPARISON_COLUMNS = ["model", "holdout_n", "median_ape_pct", "mape_pct", "coverage_p25_p75_pct", "selected"]


def split_holdout(benchmarks: pd.DataFrame, fraction: float, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    shuffled = benchmarks.sample(frac=1.0, random_state=seed)
    holdout_size = int(round(len(shuffled) * fraction))
    return shuffled.iloc[holdout_size:], shuffled.iloc[:holdout_size]


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


def compare_models(benchmarks: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Backtest every model on one shared holdout split.

    Returns (comparison table, per-trial predictions, split sizes). The comparison
    marks the model with the lowest median absolute percentage error as selected.
    """
    bt_cfg = config["backtest"]
    forecast_cfg = config["forecast"]
    train, holdout = split_holdout(benchmarks, float(bt_cfg["holdout_fraction"]), int(bt_cfg["random_seed"]))
    sizes = {"benchmark_count": len(benchmarks), "train_count": len(train), "holdout_count": len(holdout)}
    if train.empty or holdout.empty:
        return pd.DataFrame(columns=COMPARISON_COLUMNS), pd.DataFrame(columns=PREDICTION_COLUMNS), sizes

    predictions = pd.concat([score_model(name, train, holdout, forecast_cfg) for name in MODEL_NAMES], ignore_index=True)
    rows: list[dict[str, Any]] = []
    for name in MODEL_NAMES:
        scored = predictions[predictions["model"] == name]
        rows.append(
            {
                "model": name,
                "holdout_n": len(scored),
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


def seed_sensitivity(benchmarks: pd.DataFrame, config: dict[str, Any]) -> dict[str, int]:
    """Count how often each model has the lowest median error across alternative seeds."""
    seeds = int(config["backtest"].get("sensitivity_seeds", 0))
    wins = {name: 0 for name in MODEL_NAMES}
    auto_cfg = dict(config["forecast"], model="auto")
    for seed in range(seeds):
        alt = {**config, "backtest": {**config["backtest"], "random_seed": seed}, "forecast": auto_cfg}
        comparison, _, _ = compare_models(benchmarks, alt)
        if comparison.empty:
            continue
        wins[select_model(comparison, auto_cfg)] += 1
    return wins
