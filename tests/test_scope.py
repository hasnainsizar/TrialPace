from __future__ import annotations

from typing import Any

from trialpace.parse import parse_studies
from trialpace.scope import apply_scope


def test_scope_filters_remove_in_order_and_log_counts(config: dict[str, Any], sample_studies: list[dict[str, Any]]) -> None:
    records, _ = parse_studies(sample_studies, config)
    kept, excluded, log = apply_scope(records, config["scope"])
    assert [r.nct_id for r in kept] == ["NCT00000001", "NCT00000002"]
    reasons = dict(excluded)
    assert reasons["NCT00000003"] == "no DEVICE intervention"
    assert reasons["NCT00000004"] == "no transcatheter term or product name in title or interventions"
    assert reasons["NCT00000005"] == "lead sponsor class is not INDUSTRY"
    assert [(s.step, s.removed, s.remaining) for s in log] == [
        ("parsed", 0, 5),
        ("no DEVICE intervention", 1, 4),
        ("no transcatheter term or product name in title or interventions", 1, 3),
        ("lead sponsor class is not INDUSTRY", 1, 2),
    ]


def test_industry_filter_can_be_turned_off(config: dict[str, Any], sample_studies: list[dict[str, Any]]) -> None:
    records, _ = parse_studies(sample_studies, config)
    scope_cfg = dict(config["scope"], industry_only=False)
    kept, _, log = apply_scope(records, scope_cfg)
    assert "NCT00000005" in {r.nct_id for r in kept}
    assert len(log) == 3


def test_product_name_counts_as_transcatheter_term(config: dict[str, Any], sample_studies: list[dict[str, Any]]) -> None:
    records, _ = parse_studies(sample_studies, config)
    scope_cfg = dict(config["scope"], require_device_intervention=False, industry_only=False)
    kept, excluded, _ = apply_scope(records, scope_cfg)
    kept_ids = {r.nct_id for r in kept}
    assert "NCT00000005" in kept_ids
    assert dict(excluded) == {
        "NCT00000003": "no transcatheter term or product name in title or interventions",
        "NCT00000004": "no transcatheter term or product name in title or interventions",
    }


def test_scope_with_all_filters_off_keeps_everything(config: dict[str, Any], sample_studies: list[dict[str, Any]]) -> None:
    records, _ = parse_studies(sample_studies, config)
    scope_cfg = {"require_device_intervention": False, "require_transcatheter_term": False, "industry_only": False}
    kept, excluded, log = apply_scope(records, scope_cfg)
    assert len(kept) == 5
    assert excluded == []
    assert len(log) == 1
