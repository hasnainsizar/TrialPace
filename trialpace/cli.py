from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import typer

from trialpace import api, db
from trialpace.backtest import compare_models, duration_by_valve, select_model
from trialpace.config import load_config
from trialpace.export_excel import export_excel
from trialpace.export_powerbi import TABLE_DESCRIPTIONS, export_powerbi
from trialpace.forecast import HORIZON_REASON, build_benchmarks, build_forecasts, rates_frame, segment_rates
from trialpace.method import render_method
from trialpace.parse import parse_studies
from trialpace.predictors import MODEL_NAMES, make_predictor
from trialpace.scope import apply_scope
from trialpace.stale import is_stale, stale_cutoff

app = typer.Typer(help="Enrollment pace forecasts for structural heart device trials.", no_args_is_help=True)

ConfigOption = typer.Option(Path("config.yaml"), "--config", "-c", help="Path to config.yaml")
DateOption = typer.Option(None, "--date", "-d", help="Snapshot date (YYYY-MM-DD). Defaults to today.")


def _day(value: Optional[str]) -> date:
    return date.fromisoformat(value) if value else date.today()


def _snapshot_or_fail(conn: Any, value: Optional[str]) -> date:
    if value:
        return date.fromisoformat(value)
    latest = db.latest_snapshot(conn)
    if latest is None:
        typer.echo("No snapshots in the database. Run `fetch` and `load` first.")
        raise typer.Exit(code=1)
    return latest


def _warn_if_small(label: str, count: int, floor: int = 1) -> None:
    if count == 0:
        typer.echo(f"  Note: {label} is empty.")
    elif count < floor:
        typer.echo(f"  Note: {label} has only {count} rows, so results rest on very little data.")


@app.command()
def fetch(config: Path = ConfigOption, snapshot_date: Optional[str] = DateOption) -> None:
    """Pull studies from ClinicalTrials.gov and cache raw JSON under data/raw/YYYY-MM-DD/."""
    cfg = load_config(config)
    day = _day(snapshot_date)
    typer.echo(f"Fetching into {api.raw_day_dir(cfg, day)} (cached queries are skipped)")
    counts = api.fetch_all(cfg, day)
    for label, count in counts.items():
        typer.echo(f"  {label}: {count} studies")
        _warn_if_small(f"query {label}", count)
    typer.echo(f"Fetch complete: {sum(counts.values())} study records across {len(counts)} queries before deduplication")


@app.command()
def load(config: Path = ConfigOption, snapshot_date: Optional[str] = DateOption) -> None:
    """Parse cached raw JSON into the dated snapshot in SQLite. Rerunning replaces the same day."""
    cfg = load_config(config)
    day = _day(snapshot_date)
    day_dir = api.raw_day_dir(cfg, day)
    if not day_dir.exists():
        available = ", ".join(d.isoformat() for d in api.list_raw_days(cfg)) or "none"
        typer.echo(f"No raw data for {day}. Available days: {available}. Run `fetch` first.")
        raise typer.Exit(code=1)
    studies = list(api.iter_raw_studies(day_dir))
    parsed, skipped = parse_studies(studies, cfg)
    records, excluded, filter_log = apply_scope(parsed, cfg["scope"])
    for record in records:
        record.is_stale = is_stale(record.last_update_date, day, cfg["forecast"])
    conn = db.connect(Path(cfg["paths"]["db_path"]))
    trials, sites, issues = db.replace_snapshot(conn, day, records, excluded, filter_log)
    typer.echo(f"Snapshot {day}: {len(parsed)} unique trials parsed, {trials} in scope, {sites} sites, {issues} data quality issues")
    if skipped:
        typer.echo(f"  Skipped {skipped} study objects with no NCT ID")
    for step in filter_log[1:]:
        typer.echo(f"  Filter '{step.step}': removed {step.removed}, {step.remaining} remain")
    _warn_if_small("trial snapshot", trials)
    frame = pd.DataFrame([{"sponsor": r.sponsor} for r in records])
    if not frame.empty:
        for sponsor, count in frame["sponsor"].value_counts().items():
            typer.echo(f"  {sponsor}: {count}")


@app.command()
def forecast(config: Path = ConfigOption, snapshot_date: Optional[str] = DateOption) -> None:
    """Build benchmark rates and forecast every active trial in the snapshot."""
    cfg = load_config(config)
    conn = db.connect(Path(cfg["paths"]["db_path"]))
    day = _snapshot_or_fail(conn, snapshot_date)
    trials = db.read_table(conn, "trials", day)
    benchmarks, bench_excl = build_benchmarks(trials, cfg["forecast"])
    rates = segment_rates(benchmarks, int(cfg["forecast"]["min_segment_count"]))
    comparison, _, _ = compare_models(benchmarks, cfg)
    model_name = select_model(comparison, cfg["forecast"])
    predictor = make_predictor(model_name, cfg["forecast"])
    fitted = predictor.fit(benchmarks)
    forecasts, fc_excl = build_forecasts(trials, predictor if fitted else None, cfg["forecast"], day)
    exclusions = pd.concat([bench_excl.assign(reason="benchmark: " + bench_excl["reason"]), fc_excl.assign(reason="forecast: " + fc_excl["reason"])])

    horizon_reason = HORIZON_REASON.format(horizon=float(cfg["forecast"]["max_horizon_months"]))
    horizon_rows = []
    for name in MODEL_NAMES:
        candidate = make_predictor(name, cfg["forecast"])
        candidate_fitted = candidate.fit(benchmarks)
        _, candidate_excl = build_forecasts(trials, candidate if candidate_fitted else None, cfg["forecast"], day)
        horizon_rows.append({"model": name, "fitted": int(candidate_fitted), "excluded_by_horizon": int((candidate_excl["reason"] == horizon_reason).sum())})
    horizon_checks = pd.DataFrame(horizon_rows)

    db.replace_rows(conn, "benchmarks", day, benchmarks)
    db.replace_rows(conn, "segment_rates", day, rates_frame(rates))
    db.replace_rows(conn, "forecasts", day, forecasts)
    db.replace_rows(conn, "forecast_exclusions", day, exclusions)
    db.replace_rows(conn, "horizon_checks", day, horizon_checks)

    typer.echo(f"Snapshot {day}: {len(benchmarks)} benchmark trials, {len(forecasts)} active trials forecast with the {model_name} model")
    if not fitted:
        typer.echo(f"  The {model_name} model could not be fitted on {len(benchmarks)} benchmark trials, so no forecasts were produced.")
    _warn_if_small("benchmark set", len(benchmarks), int(cfg["forecast"]["min_segment_count"]))
    _warn_if_small("forecast set", len(forecasts))
    if not forecasts.empty:
        counts = forecasts["status_label"].value_counts()
        for label in cfg["forecast"]["labels"].values():
            typer.echo(f"  {label}: {int(counts.get(label, 0))}")
        stale = int(forecasts["is_stale"].fillna(0).sum())
        typer.echo(f"  Stale: {stale} of {len(forecasts)} forecast trials last updated before {stale_cutoff(day, cfg['forecast'])} ({cfg['forecast']['stale_after_months']} months before the snapshot)")
    if len(exclusions):
        typer.echo(f"  {len(exclusions)} trials excluded (reasons stored in forecast_exclusions)")
    for row in horizon_checks.itertuples(index=False):
        typer.echo(f"  Horizon cap would exclude {row.excluded_by_horizon} trials under the {row.model} model" if row.fitted else f"  {row.model} model could not be fitted")


@app.command()
def backtest(config: Path = ConfigOption, snapshot_date: Optional[str] = DateOption) -> None:
    """Leave-one-out cross-validate all models on the benchmark set and report accuracy."""
    cfg = load_config(config)
    conn = db.connect(Path(cfg["paths"]["db_path"]))
    day = _snapshot_or_fail(conn, snapshot_date)
    benchmarks = db.read_table(conn, "benchmarks", day)
    if benchmarks.empty:
        typer.echo(f"No benchmark rows for {day}. Run `forecast` first.")
    comparison, predictions, sizes = compare_models(benchmarks, cfg)
    metrics = {k: float(v) for k, v in sizes.items()}
    db.replace_rows(conn, "backtest_results", day, pd.DataFrame({"metric": list(metrics), "value": list(metrics.values())}))
    db.replace_rows(conn, "model_comparison", day, comparison)
    db.replace_rows(conn, "backtest_predictions", day, predictions)
    context = {
        "rates": db.read_table(conn, "segment_rates", day).drop(columns=["snapshot_date"], errors="ignore"),
        "benchmarks": benchmarks,
        "filter_log": db.read_table(conn, "filter_log", day),
        "exclusions": db.read_table(conn, "forecast_exclusions", day),
        "horizon_checks": db.read_table(conn, "horizon_checks", day),
        "comparison": comparison,
        "sizes": sizes,
        "durations": duration_by_valve(benchmarks),
        "forecasts": db.read_table(conn, "forecasts", day),
    }
    method_path = Path(cfg["paths"]["method_path"])
    method_path.write_text(render_method(cfg, context, day), encoding="utf-8")

    typer.echo(f"Leave-one-out backtest on snapshot {day}: {sizes['folds']} folds over {sizes['benchmark_count']} benchmark trials")
    min_benchmarks = int(cfg["backtest"]["min_benchmarks_for_confidence"])
    if 0 < sizes["benchmark_count"] < min_benchmarks:
        typer.echo(f"  Note: only {sizes['benchmark_count']} benchmark trials, fewer than {min_benchmarks}. The comparison below is thin.")
    if comparison.empty:
        typer.echo("  Fewer than two benchmark trials, so no model can be cross-validated.")
    else:
        typer.echo(f"  {'model':<12}{'scored':>8}{'median APE':>12}{'MAPE':>10}{'coverage':>10}  selected")
        for row in comparison.itertuples(index=False):
            if row.median_ape_pct is None or pd.isna(row.median_ape_pct):
                typer.echo(f"  {row.model:<12}{row.scored_n:>8}  could not be fitted")
                continue
            typer.echo(f"  {row.model:<12}{row.scored_n:>8}{row.median_ape_pct:>11.1f}%{row.mape_pct:>9.1f}%{row.coverage_p25_p75_pct:>9.1f}%  {'yes' if row.selected else ''}")
    durations = duration_by_valve(benchmarks)
    if not durations.empty:
        typer.echo("  Months from start to primary completion by valve type (benchmark set):")
        typer.echo(f"  {'valve':<12}{'n':>5}{'P25':>8}{'median':>8}{'P75':>8}")
        for row in durations.itertuples(index=False):
            typer.echo(f"  {row.valve_type:<12}{row.n:>5}{row.months_p25:>8.1f}{row.months_median:>8.1f}{row.months_p75:>8.1f}")
    typer.echo(f"  Wrote {method_path}")


@app.command()
def export(config: Path = ConfigOption, snapshot_date: Optional[str] = DateOption) -> None:
    """Write the Power BI star schema CSVs and the Excel workbook."""
    cfg = load_config(config)
    conn = db.connect(Path(cfg["paths"]["db_path"]))
    day = _snapshot_or_fail(conn, snapshot_date)
    powerbi_dir = Path(cfg["paths"]["powerbi_dir"])
    counts = export_powerbi(conn, day, cfg, powerbi_dir)
    typer.echo(f"Power BI tables in {powerbi_dir}:")
    for name, count in counts.items():
        typer.echo(f"  {name}.csv: {count} rows ({TABLE_DESCRIPTIONS[name]})")
        _warn_if_small(name, count)
    method_path = Path(cfg["paths"]["method_path"])
    method_text = method_path.read_text(encoding="utf-8") if method_path.exists() else "METHOD.md not generated yet. Run `backtest`."
    excel_path = Path(cfg["paths"]["excel_path"])
    sheet_counts = export_excel(conn, day, cfg, excel_path, method_text)
    typer.echo(f"Excel workbook: {excel_path}")
    for name, count in sheet_counts.items():
        typer.echo(f"  {name}: {count} rows")
        _warn_if_small(f"sheet {name}", count)


@app.command("run-all")
def run_all(config: Path = ConfigOption, snapshot_date: Optional[str] = DateOption) -> None:
    """Fetch, load, forecast, backtest, and export in order."""
    fetch(config, snapshot_date)
    load(config, snapshot_date)
    forecast(config, snapshot_date)
    backtest(config, snapshot_date)
    export(config, snapshot_date)


if __name__ == "__main__":
    app()
