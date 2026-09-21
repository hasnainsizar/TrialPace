from __future__ import annotations

from datetime import date
from typing import Any

from trialpace.parse import parse_date, parse_studies


def test_partial_dates_snap_to_first_of_period() -> None:
    assert parse_date("2015-01") == date(2015, 1, 1)
    assert parse_date("2015") == date(2015, 1, 1)
    assert parse_date("2015-03-17") == date(2015, 3, 17)
    assert parse_date(None) is None
    assert parse_date("not a date") is None


def test_missing_fields_are_recorded_not_fatal(config: dict[str, Any], sample_studies: list[dict[str, Any]]) -> None:
    records, skipped = parse_studies(sample_studies, config)
    assert skipped == 1
    by_id = {r.nct_id: r for r in records}
    sparse = by_id["NCT00000003"]
    assert sparse.sponsor == "Other"
    assert sparse.valve_type == "tricuspid"
    assert sparse.enrollment_count is None
    assert sparse.start_date is None
    missing_fields = {i.field for i in sparse.issues if i.issue == "missing"}
    assert {"title", "enrollment_count", "enrollment_type", "start_date", "primary_completion_date", "interventions"} <= missing_fields
    assert "location[0].facility" in missing_fields
    assert "location[0].country" in missing_fields
    complete = by_id["NCT00000001"]
    assert complete.issues == []
    assert complete.site_count == 5


def test_duplicate_nct_ids_across_queries_are_collapsed(config: dict[str, Any], sample_studies: list[dict[str, Any]]) -> None:
    records, _ = parse_studies(sample_studies + sample_studies, config)
    assert len(records) == 3
