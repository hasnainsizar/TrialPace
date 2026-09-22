from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from trialpace.db import read_table

HEADER_FONT = Font(bold=True)
STATUS_FILLS = {
    "on_track": "C6EFCE",
    "behind_forecast": "FFEB9C",
    "overdue": "FFC7CE",
    "primary_completion_reached": "D9D9D9",
}
DATE_FORMAT = "yyyy-mm-dd"


def _write_frame(ws: Worksheet, frame: pd.DataFrame, empty_message: str) -> None:
    ws.append(list(frame.columns))
    for cell in ws[1]:
        cell.font = HEADER_FONT
    if frame.empty:
        ws.append([empty_message])
        ws.freeze_panes = "A2"
        return
    date_columns = [c for c in frame.columns if pd.api.types.is_datetime64_any_dtype(frame[c])]
    for row in frame.itertuples(index=False):
        values = [None if pd.isna(v) else (v.to_pydatetime().date() if isinstance(v, pd.Timestamp) else v) for v in row]
        ws.append(values)
    for column in date_columns:
        letter = get_column_letter(list(frame.columns).index(column) + 1)
        for cell in ws[letter][1:]:
            cell.number_format = DATE_FORMAT
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for index, column in enumerate(frame.columns, start=1):
        sample = frame[column].astype(str).str.len().quantile(0.9) if len(frame) else 0
        width = min(max(len(str(column)), int(sample)) + 2, 60)
        ws.column_dimensions[get_column_letter(index)].width = max(width, 8)


def _append_block(ws: Worksheet, frame: pd.DataFrame, title: str, empty_message: str) -> None:
    """Append a titled table below whatever the sheet already holds."""
    ws.append([])
    ws.append([title])
    ws.cell(row=ws.max_row, column=1).font = HEADER_FONT
    header_row = ws.max_row + 1
    ws.append(list(frame.columns))
    for cell in ws[header_row]:
        cell.font = HEADER_FONT
    if frame.empty:
        ws.append([empty_message])
        return
    date_columns = [c for c in frame.columns if pd.api.types.is_datetime64_any_dtype(frame[c])]
    for row in frame.itertuples(index=False):
        ws.append([None if pd.isna(v) else (v.to_pydatetime().date() if isinstance(v, pd.Timestamp) else v) for v in row])
    for column in date_columns:
        letter = get_column_letter(list(frame.columns).index(column) + 1)
        for cell in ws[letter][header_row:]:
            cell.number_format = DATE_FORMAT


def _with_sponsor_name(frame: pd.DataFrame, trials: pd.DataFrame) -> pd.DataFrame:
    """Insert the original lead sponsor name and mapping reason right after the sponsor group column."""
    if frame.empty or "sponsor_group" not in frame.columns or trials.empty:
        return frame
    lookup = trials.set_index("nct_id")
    out = frame.copy()
    position = list(out.columns).index("sponsor_group") + 1
    out.insert(position, "sponsor_name", out["nct_id"].map(lookup["lead_sponsor_raw"]))
    out.insert(position + 1, "mapped_via", out["nct_id"].map(lookup["mapped_via"]))
    return out


def top_other_sponsors(trials: pd.DataFrame, sponsor_cfg: dict[str, Any], limit: int = 10) -> pd.DataFrame:
    default = str(sponsor_cfg.get("default", "Other"))
    columns = ["sponsor_name", "trials_in_scope"]
    if trials.empty:
        return pd.DataFrame(columns=columns)
    other = trials[trials["sponsor_group"] == default]
    counts = other["lead_sponsor_raw"].fillna("(no sponsor name)").value_counts().head(limit)
    return pd.DataFrame({"sponsor_name": counts.index, "trials_in_scope": counts.values}, columns=columns)


def _status_fill(ws: Worksheet, frame: pd.DataFrame, labels: dict[str, str]) -> None:
    if frame.empty or "status_label" not in frame.columns:
        return
    letter = get_column_letter(list(frame.columns).index("status_label") + 1)
    cell_range = f"{letter}2:{letter}{len(frame) + 1}"
    for key, color in STATUS_FILLS.items():
        label = labels.get(key)
        if label:
            fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
            ws.conditional_formatting.add(cell_range, CellIsRule(operator="equal", formula=[f'"{label}"'], fill=fill))


def summary_frame(
    trials: pd.DataFrame,
    forecasts: pd.DataFrame,
    benchmarks: pd.DataFrame,
    comparison: pd.DataFrame,
    filter_log: pd.DataFrame,
    snapshot: date,
    stale_after_months: float,
    labels: dict[str, str],
) -> pd.DataFrame:
    rows: list[tuple[str, Any]] = [("Snapshot date", snapshot.isoformat())]
    for step in filter_log.sort_values("step_order").itertuples(index=False):
        rows.append((f"Scope: {step.step}", f"removed {step.removed}, {step.remaining} remain") if step.removed or step.step != "parsed" else ("Trials parsed from the API", step.remaining))
    rows.append(("Trials in scope", len(trials)))
    if not trials.empty:
        for group, count in trials["sponsor_group"].value_counts().items():
            rows.append((f"Trials: {group}", int(count)))
    rows.append(("Active trials", len(forecasts)))
    if not forecasts.empty:
        finished = str(labels.get("primary_completion_reached", ""))
        rows.append(("Active trials with a forecast", int((forecasts["status_label"] != finished).sum())))
        models = forecasts.loc[forecasts["model"] != "none", "model"]
        rows.append(("Forecast model", str(models.iloc[0]) if len(models) else "none"))
        counts = forecasts["status_label"].value_counts()
        for label in labels.values():
            rows.append((f"Forecast status: {label}", int(counts.get(label, 0))))
        rows.append((f"Stale active trials (last update more than {stale_after_months:g} months before snapshot)", int(forecasts["is_stale"].fillna(0).sum())))
    rows.append(("Benchmark trials", len(benchmarks)))
    if not benchmarks.empty:
        rows.append(("Median rate per site per month", round(float(benchmarks["rate_per_site_month"].median()), 3)))
    for row in comparison.itertuples(index=False):
        if row.median_ape_pct is None or pd.isna(row.median_ape_pct):
            rows.append((f"Backtest {row.model}", "could not be fitted"))
            continue
        rows.append((f"Backtest {row.model}: median abs % error", round(float(row.median_ape_pct), 1)))
        rows.append((f"Backtest {row.model}: MAPE", round(float(row.mape_pct), 1)))
        rows.append((f"Backtest {row.model}: inside P25 to P75", round(float(row.coverage_p25_p75_pct), 1)))
    return pd.DataFrame(rows, columns=["Metric", "Value"])


def export_excel(conn: sqlite3.Connection, snapshot: date, config: dict[str, Any], out_path: Path, method_text: str) -> dict[str, int]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    trials = read_table(conn, "trials", snapshot)
    forecasts = read_table(conn, "forecasts", snapshot)
    sites = read_table(conn, "sites", snapshot)
    benchmarks = read_table(conn, "benchmarks", snapshot)
    segment = read_table(conn, "segment_rates", snapshot)
    quality = read_table(conn, "data_quality", snapshot)
    comparison = read_table(conn, "model_comparison", snapshot)
    filter_log = read_table(conn, "filter_log", snapshot)
    labels: dict[str, str] = config["forecast"]["labels"]

    if not sites.empty and not trials.empty:
        sites = sites.merge(trials[["nct_id", "sponsor_group", "lead_sponsor_raw", "mapped_via", "overall_status", "valve_type"]], on="nct_id", how="left")
        sites = sites.rename(columns={"lead_sponsor_raw": "sponsor_name"})

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    _write_frame(ws, summary_frame(trials, forecasts, benchmarks, comparison, filter_log, snapshot, float(config["forecast"]["stale_after_months"]), labels), "No data loaded")
    ws.auto_filter.ref = None
    _append_block(ws, top_other_sponsors(trials, config["sponsors"]), "Top Other sponsors by trials in scope", "No trials in the Other group")

    ws = wb.create_sheet("Active Trials Forecast")
    forecast_view = _with_sponsor_name(forecasts.drop(columns=["snapshot_date"], errors="ignore"), trials)
    _write_frame(ws, forecast_view, "No active trials in this snapshot")
    _status_fill(ws, forecast_view, labels)

    ws = wb.create_sheet("Sites")
    _write_frame(ws, sites.drop(columns=["snapshot_date"], errors="ignore"), "No sites in this snapshot")

    ws = wb.create_sheet("Benchmark Rates")
    _write_frame(ws, segment.drop(columns=["snapshot_date"], errors="ignore"), "No benchmark trials met the criteria")
    detail = _with_sponsor_name(benchmarks.drop(columns=["snapshot_date"], errors="ignore"), trials)
    _append_block(ws, detail, "Benchmark trials", "No completed trials met the benchmark criteria")

    ws = wb.create_sheet("Data Quality")
    scope_view = filter_log.drop(columns=["snapshot_date", "step_order"], errors="ignore").rename(columns={"step": "scope_filter"})
    _write_frame(ws, scope_view, "No scope filter log recorded")
    ws.auto_filter.ref = None
    ws.append([])
    start_row = ws.max_row + 1
    issues_view = quality.drop(columns=["snapshot_date"], errors="ignore")
    ws.append(list(issues_view.columns))
    for cell in ws[start_row]:
        cell.font = HEADER_FONT
    if issues_view.empty:
        ws.append(["No missing or unparseable fields found"])
    for row in issues_view.itertuples(index=False):
        ws.append(list(row))
    ws.column_dimensions["A"].width = 64
    ws.column_dimensions["B"].width = 28

    ws = wb.create_sheet("Method Notes")
    ws.column_dimensions["A"].width = 120
    for line in method_text.splitlines():
        ws.append([line])

    wb.save(out_path)
    return {
        "Active Trials Forecast": len(forecasts),
        "Sites": len(sites),
        "Benchmark Rates": len(segment),
        "Data Quality": len(quality),
    }
