from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
import pandas as pd

from trialpace.forecast import OVERALL_KEY, RateQuantiles, forecast_months, lookup_rate, segment_rates

MODEL_RATE = "rate"
MODEL_REGRESSION = "regression"
MODEL_NAIVE = "naive"
MODEL_NAMES = [MODEL_RATE, MODEL_REGRESSION, MODEL_NAIVE]


@dataclass(frozen=True)
class Prediction:
    months_p25: float
    months_median: float
    months_p75: float
    basis: str


class Predictor(Protocol):
    name: str

    def fit(self, benchmarks: pd.DataFrame) -> bool: ...

    def predict(self, target: int, sites: int, valve_type: str) -> Prediction: ...


@dataclass
class RatePredictor:
    """Model A: months = target / (sites x segment rate per site per month)."""

    forecast_cfg: dict[str, Any]
    name: str = MODEL_RATE
    rates: dict[tuple[str, str], RateQuantiles] = field(default_factory=dict)

    def fit(self, benchmarks: pd.DataFrame) -> bool:
        self.rates = segment_rates(benchmarks, int(self.forecast_cfg["min_segment_count"]))
        return bool(self.rates)

    def predict(self, target: int, sites: int, valve_type: str) -> Prediction:
        from trialpace.forecast import size_band

        band = size_band(target, self.forecast_cfg["size_bands"])
        quantiles = lookup_rate(self.rates, valve_type, band)
        m25, m50, m75 = forecast_months(target, sites, quantiles)
        return Prediction(m25, m50, m75, f"rate:{quantiles.source}")


@dataclass
class RegressionPredictor:
    """Model B: log(months) on log(target), log(sites), and valve type dummies.

    The P25 and P75 come from the empirical residual quantiles on the training set.
    """

    forecast_cfg: dict[str, Any]
    name: str = MODEL_REGRESSION
    coef: np.ndarray = field(default_factory=lambda: np.zeros(0))
    valve_levels: list[str] = field(default_factory=list)
    residual_quantiles: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def _design(self, target: np.ndarray, sites: np.ndarray, valve: list[str]) -> np.ndarray:
        columns = [np.ones(len(target)), np.log(target), np.log(sites)]
        for level in self.valve_levels:
            columns.append(np.array([1.0 if v == level else 0.0 for v in valve]))
        return np.column_stack(columns)

    def fit(self, benchmarks: pd.DataFrame) -> bool:
        if len(benchmarks) < int(self.forecast_cfg["min_regression_rows"]):
            return False
        valves = sorted(benchmarks["valve_type"].unique())
        self.valve_levels = valves[1:]
        x = self._design(
            benchmarks["enrollment_count"].to_numpy(dtype=float),
            benchmarks["site_count"].to_numpy(dtype=float),
            list(benchmarks["valve_type"]),
        )
        y = np.log(benchmarks["months"].to_numpy(dtype=float))
        self.coef, *_ = np.linalg.lstsq(x, y, rcond=None)
        residuals = y - x @ self.coef
        self.residual_quantiles = tuple(float(np.quantile(residuals, q)) for q in (0.25, 0.5, 0.75))
        return True

    def predict(self, target: int, sites: int, valve_type: str) -> Prediction:
        x = self._design(np.array([float(target)]), np.array([float(sites)]), [valve_type])
        center = float((x @ self.coef)[0])
        r25, r50, r75 = self.residual_quantiles
        return Prediction(
            float(np.exp(center + r25)), float(np.exp(center + r50)), float(np.exp(center + r75)),
            f"regression:n={len(self.valve_levels) + 1} valve levels",
        )


@dataclass
class NaivePredictor:
    """Baseline: median duration of benchmark trials with the same valve type."""

    forecast_cfg: dict[str, Any]
    name: str = MODEL_NAIVE
    durations: dict[str, tuple[float, float, float, int]] = field(default_factory=dict)

    def fit(self, benchmarks: pd.DataFrame) -> bool:
        if benchmarks.empty:
            return False
        min_count = int(self.forecast_cfg["min_segment_count"])
        self.durations = {}
        overall = benchmarks["months"]
        self.durations["all"] = (float(overall.quantile(0.25)), float(overall.quantile(0.5)), float(overall.quantile(0.75)), len(overall))
        for valve, group in benchmarks.groupby("valve_type"):
            if len(group) >= min_count:
                months = group["months"]
                self.durations[str(valve)] = (float(months.quantile(0.25)), float(months.quantile(0.5)), float(months.quantile(0.75)), len(months))
        return True

    def predict(self, target: int, sites: int, valve_type: str) -> Prediction:
        key = valve_type if valve_type in self.durations else "all"
        p25, p50, p75, n = self.durations[key]
        return Prediction(p25, p50, p75, f"naive:{key} (n={n})")


def make_predictor(name: str, forecast_cfg: dict[str, Any]) -> Predictor:
    if name == MODEL_RATE:
        return RatePredictor(forecast_cfg)
    if name == MODEL_REGRESSION:
        return RegressionPredictor(forecast_cfg)
    if name == MODEL_NAIVE:
        return NaivePredictor(forecast_cfg)
    raise ValueError(f"Unknown model '{name}'. Expected one of {MODEL_NAMES}")
