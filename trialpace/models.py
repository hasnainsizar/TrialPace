from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class SiteRecord:
    nct_id: str
    site_index: int
    facility: str | None
    city: str | None
    state: str | None
    country: str | None
    location_status: str | None


@dataclass(frozen=True)
class QualityIssue:
    nct_id: str
    field: str
    issue: str


@dataclass
class TrialRecord:
    nct_id: str
    title: str | None
    lead_sponsor_raw: str | None
    sponsor: str
    overall_status: str | None
    phase: str | None
    conditions: str | None
    interventions: str | None
    enrollment_count: int | None
    enrollment_type: str | None
    start_date: date | None
    primary_completion_date: date | None
    primary_completion_type: str | None
    completion_date: date | None
    last_update_date: date | None
    valve_type: str
    site_count: int
    sites: list[SiteRecord] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)
