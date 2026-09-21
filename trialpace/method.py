from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from trialpace.predictors import MODEL_NAIVE

TEMPLATE_PATH = Path(__file__).with_name("method_template.md")
MODEL_LABELS = {"rate": "Per-site rate", "regression": "Log-linear regression", "naive": "Naive baseline"}


def _fmt(value: float | None, suffix: str = "") -> str:
    return "not available" if value is None or pd.isna(value) else f"{value:.1f}{suffix}"


def _rates_table(rates: pd.DataFrame) -> str:
    if rates.empty:
        return "No benchmark rates were available for this snapshot."
    lines = ["| Valve type | Size band | Trials | P25 | Median | P75 | Source |", "|---|---|---|---|---|---|---|"]
    for row in rates.sort_values(["source", "valve_type", "size_band"]).itertuples(index=False):
        lines.append(f"| {row.valve_type} | {row.size_band} | {row.n} | {row.rate_p25:.3f} | {row.rate_p50:.3f} | {row.rate_p75:.3f} | {row.source} |")
    return "\n".join(lines)


def _filter_table(filter_log: pd.DataFrame) -> str:
    if filter_log.empty:
        return "No filter log was recorded for this snapshot."
    lines = ["| Step | Removed | Remaining |", "|---|---|---|"]
    for row in filter_log.sort_values("step_order").itertuples(index=False):
        lines.append(f"| {row.step} | {row.removed} | {row.remaining} |")
    return "\n".join(lines)


def _benchmark_table(exclusions: pd.DataFrame, benchmark_count: int) -> str:
    bench = exclusions[exclusions["reason"].str.startswith("benchmark: ")] if not exclusions.empty else exclusions
    lines = ["| Reason | Trials removed |", "|---|---|"]
    if not bench.empty:
        for reason, count in bench["reason"].str.replace("benchmark: ", "", regex=False).value_counts().items():
            lines.append(f"| {reason} | {count} |")
    lines.append(f"| Kept as benchmarks | {benchmark_count} |")
    return "\n".join(lines)


def _comparison_table(comparison: pd.DataFrame) -> str:
    if comparison.empty:
        return "The backtest could not run: there were not enough benchmark trials to hold any out."
    lines = ["| Model | Holdout trials | Median abs. % error | MAPE | Inside P25 to P75 | Selected |", "|---|---|---|---|---|---|"]
    for row in comparison.itertuples(index=False):
        label = MODEL_LABELS.get(row.model, row.model)
        if row.median_ape_pct is None or pd.isna(row.median_ape_pct):
            lines.append(f"| {label} | {row.holdout_n} | could not be fitted | | | |")
            continue
        lines.append(
            f"| {label} | {row.holdout_n} | {row.median_ape_pct:.1f}% | {row.mape_pct:.1f}% | "
            f"{row.coverage_p25_p75_pct:.1f}% | {'yes' if row.selected else ''} |"
        )
    return "\n".join(lines)


def _choice_text(comparison: pd.DataFrame, forecast_cfg: dict[str, Any], wins: dict[str, int]) -> str:
    text = _choice_core(comparison, forecast_cfg)
    total = sum(wins.values())
    if total and not comparison.empty:
        selected = comparison[comparison["selected"] == 1]
        if not selected.empty and wins.get(str(selected.iloc[0].model), 0) * 2 < total:
            text += (
                " Across the alternative seeds no model wins consistently, so the selection is a coin flip between three "
                "models of similar accuracy rather than a clear winner. The naive baseline is the safe default in that situation."
            )
    return text


def _choice_core(comparison: pd.DataFrame, forecast_cfg: dict[str, Any]) -> str:
    if comparison.empty:
        return "No model was selected because the backtest could not run."
    selected = comparison[comparison["selected"] == 1]
    if selected.empty:
        return "No model was selected."
    chosen = selected.iloc[0]
    label = MODEL_LABELS.get(chosen.model, chosen.model)
    configured = str(forecast_cfg.get("model", "auto"))
    if configured != "auto":
        return f"**Forecast outputs use the {label} model because config.yaml sets `forecast.model: {configured}`**, overriding the backtest."
    scored = comparison.dropna(subset=["median_ape_pct"])
    naive = scored[scored["model"] == MODEL_NAIVE]
    naive_err = float(naive.iloc[0]["median_ape_pct"]) if not naive.empty else None
    if chosen.model == MODEL_NAIVE:
        return (
            f"**Neither the per-site rate model nor the regression beat the naive baseline** on median error, so the forecast "
            f"outputs use the naive baseline: the median duration of completed trials with the same valve type. "
            f"Target enrollment and site count do not improve the prediction enough to be worth using in this data."
        )
    beats = f" against {naive_err:.1f}% for the naive baseline" if naive_err is not None else ""
    return (
        f"**Forecast outputs use the {label} model.** It had the lowest median absolute percentage error on the holdout "
        f"({float(chosen.median_ape_pct):.1f}%{beats}). Median error is the selection criterion because MAPE is dominated by a few short trials."
    )


def render_method(config: dict[str, Any], context: dict[str, Any], snapshot: date) -> str:
    forecast_cfg = config["forecast"]
    thresholds = forecast_cfg["status_thresholds"]
    benchmarks: pd.DataFrame = context["benchmarks"]
    exclusions: pd.DataFrame = context["exclusions"]
    sizes: dict[str, int] = context["sizes"]
    horizon = float(forecast_cfg["max_horizon_months"])
    checks: pd.DataFrame = context.get("horizon_checks", pd.DataFrame())
    if checks.empty:
        horizon_text = "No horizon check was recorded for this snapshot."
    else:
        parts = [f"{int(r.excluded_by_horizon)} under the {MODEL_LABELS.get(r.model, r.model).lower()} model" if r.fitted else f"{MODEL_LABELS.get(r.model, r.model).lower()} model not fitted" for r in checks.itertuples(index=False)]
        horizon_text = "In this snapshot, after the scope and benchmark filters, the horizon cap excluded " + ", ".join(parts) + "."
    min_holdout = int(config["backtest"]["min_holdout_for_confidence"])
    holdout = sizes.get("holdout_count", 0)
    if 0 < holdout < min_holdout:
        holdout_note = (
            f"**The holdout has only {holdout} trials, fewer than the {min_holdout} needed for a stable comparison.** "
            "This ranking can change with a different seed. Treat it as indicative, not settled."
        )
    else:
        holdout_note = ""
    wins: dict[str, int] = context.get("wins", {})
    total_wins = sum(wins.values())
    if total_wins:
        wins_text = "As a check on seed sensitivity, the split was repeated with " + str(total_wins) + " other seeds. Lowest median error: " + ", ".join(
            f"{MODEL_LABELS.get(k, k).lower()} {v} of {total_wins}" for k, v in wins.items()
        ) + "."
    else:
        wins_text = ""

    single_site_pct = 0.0 if benchmarks.empty else float((benchmarks["site_count"] == 1).mean() * 100.0)
    bands = ", ".join(
        f"{b['name']} (up to {b['max_enrollment']})" if b.get("max_enrollment") else f"{b['name']} (above the previous band)"
        for b in forecast_cfg["size_bands"]
    )
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.format(
        snapshot=snapshot.isoformat(),
        filter_table=_filter_table(context["filter_log"]),
        benchmark_table=_benchmark_table(exclusions, len(benchmarks)),
        min_benchmark_sites=forecast_cfg["min_benchmark_sites"],
        min_segment_count=forecast_cfg["min_segment_count"],
        min_months=forecast_cfg["min_months"],
        max_horizon_months=int(horizon),
        horizon_text=horizon_text,
        holdout_note=holdout_note,
        wins_text=wins_text,
        on_track_days=thresholds["on_track_max_days"],
        at_risk_days=thresholds["at_risk_max_days"],
        holdout_pct=int(float(config["backtest"]["holdout_fraction"]) * 100),
        seed=config["backtest"]["random_seed"],
        size_bands=bands,
        single_site_pct=f"{single_site_pct:.0f}",
        rates_table=_rates_table(context["rates"]),
        benchmark_count=sizes.get("benchmark_count", 0),
        train_count=sizes.get("train_count", 0),
        holdout_count=sizes.get("holdout_count", 0),
        comparison_table=_comparison_table(context["comparison"]),
        choice=_choice_text(context["comparison"], forecast_cfg, wins),
    )
