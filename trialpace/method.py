from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

TEMPLATE_PATH = Path(__file__).with_name("method_template.md")


def _fmt(value: float | None, suffix: str = "") -> str:
    return "not available" if value is None or pd.isna(value) else f"{value:.1f}{suffix}"


def render_method(config: dict[str, Any], metrics: dict[str, float | None], rates: pd.DataFrame, benchmarks: pd.DataFrame, snapshot: date) -> str:
    forecast_cfg = config["forecast"]
    thresholds = forecast_cfg["status_thresholds"]
    if rates.empty:
        rates_table = "No benchmark rates were available for this snapshot."
    else:
        lines = ["| Valve type | Size band | Trials | P25 | Median | P75 | Source |", "|---|---|---|---|---|---|---|"]
        for row in rates.sort_values(["source", "valve_type", "size_band"]).itertuples(index=False):
            lines.append(f"| {row.valve_type} | {row.size_band} | {row.n} | {row.rate_p25:.3f} | {row.rate_p50:.3f} | {row.rate_p75:.3f} | {row.source} |")
        rates_table = "\n".join(lines)
    holdout = metrics.get("holdout_count")
    if not holdout:
        backtest_text = "The backtest could not run: there were not enough benchmark trials to hold any out."
    else:
        backtest_text = (
            f"Benchmark trials: {int(metrics['benchmark_count'])}. Training set: {int(metrics['train_count'])}. "
            f"Holdout: {int(holdout)}.\n\n"
            f"- MAPE on duration in months (median forecast vs actual): {_fmt(metrics.get('mape_pct'), '%')}\n"
            f"- Median absolute percentage error: {_fmt(metrics.get('median_ape_pct'), '%')}\n"
            f"- Share of holdout trials whose actual duration fell inside the P25 to P75 range: {_fmt(metrics.get('coverage_p25_p75_pct'), '%')}"
        )
    bands = ", ".join(
        f"{b['name']} (up to {b['max_enrollment']})" if b.get("max_enrollment") else f"{b['name']} (above the previous band)"
        for b in forecast_cfg["size_bands"]
    )
    if benchmarks.empty:
        single_site_pct = 0.0
    else:
        single_site_pct = float((benchmarks["site_count"] == 1).mean() * 100.0)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.format(
        single_site_pct=f"{single_site_pct:.0f}",
        max_horizon_months=forecast_cfg["max_horizon_months"],
        snapshot=snapshot.isoformat(),
        min_segment_count=forecast_cfg["min_segment_count"],
        min_months=forecast_cfg["min_months"],
        on_track_days=thresholds["on_track_max_days"],
        at_risk_days=thresholds["at_risk_max_days"],
        holdout_pct=int(float(config["backtest"]["holdout_fraction"]) * 100),
        size_bands=bands,
        rates_table=rates_table,
        backtest=backtest_text,
    )
