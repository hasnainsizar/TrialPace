from __future__ import annotations

import re
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


def _benchmark_table(exclusions: pd.DataFrame, benchmarks: pd.DataFrame, active_statuses: list[str]) -> str:
    bench = exclusions[exclusions["reason"].str.startswith("benchmark: ")] if not exclusions.empty else exclusions
    lines = ["| Reason | Trials removed |", "|---|---|"]
    if not bench.empty:
        for reason, count in bench["reason"].str.replace("benchmark: ", "", regex=False).value_counts().items():
            lines.append(f"| {reason} | {count} |")
    from_active = int(benchmarks["overall_status"].isin(active_statuses).sum()) if not benchmarks.empty and "overall_status" in benchmarks.columns else 0
    lines.append(f"| Kept as benchmarks | {len(benchmarks)} |")
    lines.append(f"| Of which active trials that reached primary completion | {from_active} |")
    return "\n".join(lines)


def _comparison_table(comparison: pd.DataFrame) -> str:
    if comparison.empty:
        return "The backtest could not run: fewer than two benchmark trials."
    lines = ["| Model | Trials scored | Median abs. % error | MAPE | Inside P25 to P75 | Selected |", "|---|---|---|---|---|---|"]
    for row in comparison.itertuples(index=False):
        label = MODEL_LABELS.get(row.model, row.model)
        if row.median_ape_pct is None or pd.isna(row.median_ape_pct):
            lines.append(f"| {label} | {row.scored_n} | could not be fitted | | | |")
            continue
        lines.append(
            f"| {label} | {row.scored_n} | {row.median_ape_pct:.1f}% | {row.mape_pct:.1f}% | "
            f"{row.coverage_p25_p75_pct:.1f}% | {'yes' if row.selected else ''} |"
        )
    return "\n".join(lines)


def _durations_table(durations: pd.DataFrame) -> str:
    if durations.empty:
        return "No benchmark durations were available for this snapshot."
    lines = ["| Valve type | Trials | P25 | Median | P75 |", "|---|---|---|---|---|"]
    for row in durations.itertuples(index=False):
        lines.append(f"| {row.valve_type} | {row.n} | {row.months_p25:.1f} | {row.months_median:.1f} | {row.months_p75:.1f} |")
    return "\n".join(lines)


def _choice_text(comparison: pd.DataFrame, forecast_cfg: dict[str, Any]) -> str:
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
    if naive_err is not None and float(chosen.median_ape_pct) >= naive_err:
        return (
            f"**Forecast outputs use the {label} model**, but it does not beat the naive baseline: its median error of "
            f"{float(chosen.median_ape_pct):.1f}% matches or exceeds the baseline's {naive_err:.1f}%."
        )
    beats = f" against {naive_err:.1f}% for the naive baseline" if naive_err is not None else ""
    return (
        f"**Forecast outputs use the {label} model.** It had the lowest median absolute percentage error under leave-one-out cross-validation "
        f"({float(chosen.median_ape_pct):.1f}%{beats}). Median error is the selection criterion because MAPE is dominated by a few short trials."
    )


LABEL_MEANINGS = {
    "primary_completion_reached": "The trial is still listed as active but its primary completion date is marked ACTUAL, so enrollment has finished. No forecast is made and the trial is kept out of the late and at-risk counts. If it meets the benchmark rules it joins the benchmark set.",
    "past_posted_date": "The sponsor's posted primary completion date is already behind the snapshot date, yet the trial is still listed as active. Either the record is out of date or the trial has slipped past its own plan.",
    "past_forecast": "The model's median estimate is already behind the snapshot date but the trial is still active. The estimate has passed, so the trial is running slower than comparable completed trials.",
    "on_track": "The median forecast lands no more than {on_track_days} days after the posted date, or earlier.",
    "at_risk": "The median forecast lands between {on_track_days} and {at_risk_days} days after the posted date.",
    "likely_late": "The median forecast lands more than {at_risk_days} days after the posted date.",
    "no_posted_date": "The registry has no primary completion date for the trial, so there is nothing to compare against.",
}


def _labels_table(forecasts: pd.DataFrame, forecast_cfg: dict[str, Any]) -> str:
    labels: dict[str, str] = forecast_cfg["labels"]
    thresholds = forecast_cfg["status_thresholds"]
    counts = forecasts["status_label"].value_counts() if not forecasts.empty else pd.Series(dtype=int)
    lines = ["| Label | Meaning | Trials |", "|---|---|---|"]
    for key, label in labels.items():
        meaning = LABEL_MEANINGS.get(key, "").format(
            on_track_days=thresholds["on_track_max_days"], at_risk_days=thresholds["at_risk_max_days"]
        )
        lines.append(f"| {label} | {meaning} | {int(counts.get(label, 0))} |")
    return "\n".join(lines)


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
    min_benchmarks = int(config["backtest"]["min_benchmarks_for_confidence"])
    count = sizes.get("benchmark_count", 0)
    if 0 < count < min_benchmarks:
        holdout_note = (
            f"**Only {count} benchmark trials are available, fewer than the {min_benchmarks} needed for a stable comparison.** "
            "Every trial is scored, but a handful of unusual trials can still move the ranking. Treat it as indicative, not settled."
        )
    else:
        holdout_note = ""

    single_site_pct = 0.0 if benchmarks.empty else float((benchmarks["site_count"] == 1).mean() * 100.0)
    bands = ", ".join(
        f"{b['name']} (up to {b['max_enrollment']})" if b.get("max_enrollment") else f"{b['name']} (above the previous band)"
        for b in forecast_cfg["size_bands"]
    )
    forecasts: pd.DataFrame = context.get("forecasts", pd.DataFrame())
    if forecasts.empty or "is_stale" not in forecasts.columns:
        stale_text = "No forecast trials were available to check for stale records."
    else:
        stale_count = int(forecasts["is_stale"].fillna(0).sum())
        stale_text = f"In this snapshot {stale_count} of {len(forecasts)} active trials are stale."
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    rendered = template.format(
        stale_after_months=forecast_cfg["stale_after_months"],
        stale_text=stale_text,
        labels_table=_labels_table(forecasts, forecast_cfg),
        snapshot=snapshot.isoformat(),
        filter_table=_filter_table(context["filter_log"]),
        benchmark_table=_benchmark_table(exclusions, benchmarks, list(forecast_cfg["active_statuses"])),
        min_benchmark_sites=forecast_cfg["min_benchmark_sites"],
        min_segment_count=forecast_cfg["min_segment_count"],
        min_months=forecast_cfg["min_months"],
        max_horizon_months=int(horizon),
        horizon_text=horizon_text,
        holdout_note=holdout_note,
        durations_table=_durations_table(context.get("durations", pd.DataFrame())),
        on_track_days=thresholds["on_track_max_days"],
        at_risk_days=thresholds["at_risk_max_days"],
        size_bands=bands,
        single_site_pct=f"{single_site_pct:.0f}",
        rates_table=_rates_table(context["rates"]),
        benchmark_count=sizes.get("benchmark_count", 0),
        comparison_table=_comparison_table(context["comparison"]),
        choice=_choice_text(context["comparison"], forecast_cfg),
    )
    return re.sub(r"\n{3,}", "\n\n", rendered)
