from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from trialpace.backtest import compare_models, duration_by_valve, leave_one_out, select_model
from trialpace.predictors import MODEL_NAIVE, MODEL_RATE, MODEL_REGRESSION, NaivePredictor, RegressionPredictor, make_predictor


def _benchmarks(n: int, seed: int = 0) -> pd.DataFrame:
    """Synthetic benchmarks where months = 2 x target^0.5 / sites^0.5 exactly."""
    rng = np.random.default_rng(seed)
    target = rng.integers(50, 2000, size=n)
    sites = rng.integers(5, 80, size=n)
    valve = rng.choice(["aortic", "mitral", "tricuspid"], size=n)
    months = 2.0 * np.sqrt(target) / np.sqrt(sites)
    return pd.DataFrame(
        {
            "nct_id": [f"NCT{i:08d}" for i in range(n)],
            "sponsor": "Other",
            "valve_type": valve,
            "size_band": "medium",
            "enrollment_count": target,
            "site_count": sites,
            "months": months,
            "rate_per_site_month": target / sites / months,
        }
    )


def test_regression_recovers_exact_log_linear_relationship(config: dict[str, Any]) -> None:
    model = RegressionPredictor(config["forecast"])
    assert model.fit(_benchmarks(60))
    pred = model.predict(target=400, sites=16, valve_type="aortic")
    assert pred.months_median == pytest.approx(2.0 * 20 / 4, rel=1e-6)
    assert pred.months_p25 == pytest.approx(pred.months_median, rel=1e-6)
    assert pred.months_p75 == pytest.approx(pred.months_median, rel=1e-6)


def test_regression_refuses_to_fit_on_too_few_rows(config: dict[str, Any]) -> None:
    model = RegressionPredictor(config["forecast"])
    assert not model.fit(_benchmarks(int(config["forecast"]["min_regression_rows"]) - 1))


def test_regression_handles_unseen_valve_type(config: dict[str, Any]) -> None:
    model = RegressionPredictor(config["forecast"])
    model.fit(_benchmarks(60))
    pred = model.predict(target=400, sites=16, valve_type="other")
    assert pred.months_median > 0


def test_naive_uses_valve_type_median_with_fallback(config: dict[str, Any]) -> None:
    frame = pd.DataFrame(
        {
            "valve_type": ["aortic"] * 6 + ["mitral"] * 2,
            "months": [10, 12, 14, 16, 18, 20, 40, 60],
        }
    )
    model = NaivePredictor(config["forecast"])
    assert model.fit(frame)
    aortic = model.predict(target=1, sites=1, valve_type="aortic")
    assert aortic.months_median == pytest.approx(15.0)
    assert aortic.months_p25 < aortic.months_median < aortic.months_p75
    mitral = model.predict(target=1, sites=1, valve_type="mitral")
    assert mitral.basis.startswith("naive:all")
    assert mitral.months_median == pytest.approx(frame["months"].median())


def test_naive_refuses_empty(config: dict[str, Any]) -> None:
    assert not NaivePredictor(config["forecast"]).fit(pd.DataFrame(columns=["valve_type", "months"]))


def test_make_predictor_rejects_unknown_model(config: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        make_predictor("oracle", config["forecast"])


def test_leave_one_out_scores_every_trial_once_per_model(config: dict[str, Any]) -> None:
    benchmarks = _benchmarks(40)
    predictions = leave_one_out(benchmarks, config["forecast"])
    for name in (MODEL_RATE, MODEL_REGRESSION, MODEL_NAIVE):
        scored = predictions[predictions["model"] == name]
        assert sorted(scored["nct_id"]) == sorted(benchmarks["nct_id"])


def test_leave_one_out_never_trains_on_the_held_out_trial(config: dict[str, Any]) -> None:
    benchmarks = _benchmarks(30)
    outlier = benchmarks.index[0]
    benchmarks.loc[outlier, "months"] = 1000.0
    predictions = leave_one_out(benchmarks, config["forecast"])
    naive = predictions[(predictions["model"] == MODEL_NAIVE) & (predictions["nct_id"] == benchmarks.loc[outlier, "nct_id"])]
    assert naive.iloc[0]["pred_months_median"] < 100


def test_compare_models_scores_all_three_and_selects_lowest_median_error(config: dict[str, Any]) -> None:
    comparison, predictions, sizes = compare_models(_benchmarks(60), config)
    assert list(comparison["model"]) == [MODEL_RATE, MODEL_REGRESSION, MODEL_NAIVE]
    assert sizes == {"benchmark_count": 60, "folds": 60}
    assert comparison["scored_n"].tolist() == [60, 60, 60]
    assert len(predictions) == 180
    assert comparison["selected"].sum() == 1
    assert comparison.loc[comparison["selected"] == 1, "model"].iloc[0] == MODEL_REGRESSION
    assert comparison.set_index("model").loc[MODEL_REGRESSION, "median_ape_pct"] == pytest.approx(0.0, abs=1e-6)


def test_compare_models_is_deterministic(config: dict[str, Any]) -> None:
    first, _, _ = compare_models(_benchmarks(30), config)
    second, _, _ = compare_models(_benchmarks(30), config)
    pd.testing.assert_frame_equal(first, second)


def test_compare_models_reports_unfittable_models(config: dict[str, Any]) -> None:
    comparison, _, _ = compare_models(_benchmarks(10), config)
    by_model = comparison.set_index("model")
    assert by_model.loc[MODEL_REGRESSION, "scored_n"] == 0
    assert pd.isna(by_model.loc[MODEL_REGRESSION, "median_ape_pct"])
    assert by_model.loc[MODEL_NAIVE, "scored_n"] == 10


def test_compare_models_needs_two_benchmarks(config: dict[str, Any]) -> None:
    comparison, predictions, sizes = compare_models(_benchmarks(1), config)
    assert comparison.empty
    assert predictions.empty
    assert sizes == {"benchmark_count": 1, "folds": 1}


def test_duration_by_valve_includes_overall_row() -> None:
    frame = pd.DataFrame({"valve_type": ["aortic", "aortic", "mitral"], "months": [10.0, 20.0, 30.0]})
    durations = duration_by_valve(frame)
    assert durations["valve_type"].tolist() == ["aortic", "mitral", "all"]
    assert durations.set_index("valve_type").loc["aortic", "months_median"] == pytest.approx(15.0)
    assert durations.set_index("valve_type").loc["all", "n"] == 3
    assert duration_by_valve(frame.iloc[0:0]).empty


def test_select_model_prefers_naive_on_ties_and_honors_override(config: dict[str, Any]) -> None:
    comparison = pd.DataFrame(
        {"model": [MODEL_RATE, MODEL_REGRESSION, MODEL_NAIVE], "median_ape_pct": [30.0, 30.0, 30.0]}
    )
    assert select_model(comparison, config["forecast"]) == MODEL_NAIVE
    comparison.loc[0, "median_ape_pct"] = 10.0
    assert select_model(comparison, config["forecast"]) == MODEL_RATE
    assert select_model(comparison, dict(config["forecast"], model="regression")) == MODEL_REGRESSION
    comparison["median_ape_pct"] = [None, None, None]
    assert select_model(comparison, config["forecast"]) == MODEL_NAIVE
