from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def stale_cutoff(snapshot: date, forecast_cfg: dict[str, Any]) -> date:
    months = float(forecast_cfg["stale_after_months"])
    return snapshot - timedelta(days=round(months * float(forecast_cfg["days_per_month"])))


def is_stale(last_update: date | None, snapshot: date, forecast_cfg: dict[str, Any]) -> int | None:
    """1 when the last update predates the cutoff, 0 otherwise, None when the date is unknown."""
    if last_update is None:
        return None
    return int(last_update < stale_cutoff(snapshot, forecast_cfg))
