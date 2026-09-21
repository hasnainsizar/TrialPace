from __future__ import annotations

from datetime import date
from typing import Any

from trialpace.models import QualityIssue, SiteRecord, TrialRecord
from trialpace.sponsors import classify_valve, normalize_sponsor

SEPARATOR = "; "


def parse_date(value: str | None) -> date | None:
    """Parse YYYY, YYYY-MM, or YYYY-MM-DD. Partial dates snap to the first day."""
    if not value:
        return None
    parts = value.split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return date(year, month, day)
    except (ValueError, IndexError):
        return None


def _get(mapping: dict[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def parse_study(study: dict[str, Any], config: dict[str, Any]) -> TrialRecord | None:
    """Flatten one API study object. Returns None only when the NCT ID is missing."""
    protocol = study.get("protocolSection", {})
    nct_id = _get(protocol, "identificationModule", "nctId")
    if not nct_id:
        return None

    issues: list[QualityIssue] = []

    def require(value: Any, field: str) -> Any:
        if value is None or value == "" or value == []:
            issues.append(QualityIssue(nct_id, field, "missing"))
            return None
        return value

    title = require(_get(protocol, "identificationModule", "briefTitle"), "title")
    sponsor_raw = require(_get(protocol, "sponsorCollaboratorsModule", "leadSponsor", "name"), "lead_sponsor")
    sponsor_class = require(_get(protocol, "sponsorCollaboratorsModule", "leadSponsor", "class"), "lead_sponsor_class")
    status = require(_get(protocol, "statusModule", "overallStatus"), "overall_status")
    phases = require(_get(protocol, "designModule", "phases"), "phase")
    conditions = require(_get(protocol, "conditionsModule", "conditions"), "conditions")
    interventions_raw = require(_get(protocol, "armsInterventionsModule", "interventions"), "interventions")
    enrollment_count = require(_get(protocol, "designModule", "enrollmentInfo", "count"), "enrollment_count")
    enrollment_type = require(_get(protocol, "designModule", "enrollmentInfo", "type"), "enrollment_type")
    start_raw = require(_get(protocol, "statusModule", "startDateStruct", "date"), "start_date")
    pc_raw = require(_get(protocol, "statusModule", "primaryCompletionDateStruct", "date"), "primary_completion_date")
    pc_type = require(_get(protocol, "statusModule", "primaryCompletionDateStruct", "type"), "primary_completion_type")
    completion_raw = require(_get(protocol, "statusModule", "completionDateStruct", "date"), "completion_date")
    update_raw = require(_get(protocol, "statusModule", "lastUpdatePostDateStruct", "date"), "last_update_date")
    locations_raw = require(_get(protocol, "contactsLocationsModule", "locations"), "locations") or []

    def parse_dated(raw: str | None, field: str) -> date | None:
        if raw is None:
            return None
        parsed = parse_date(raw)
        if parsed is None:
            issues.append(QualityIssue(nct_id, field, f"unparseable date: {raw}"))
        return parsed

    intervention_names = [item.get("name") for item in interventions_raw or [] if item.get("name")]
    intervention_types = sorted({item.get("type") for item in interventions_raw or [] if item.get("type")})
    sites: list[SiteRecord] = []
    for index, loc in enumerate(locations_raw):
        for key in ("facility", "country"):
            if not loc.get(key):
                issues.append(QualityIssue(nct_id, f"location[{index}].{key}", "missing"))
        sites.append(
            SiteRecord(
                nct_id=nct_id,
                site_index=index,
                facility=loc.get("facility"),
                city=loc.get("city"),
                state=loc.get("state"),
                country=loc.get("country"),
                location_status=loc.get("status"),
            )
        )

    conditions_text = SEPARATOR.join(conditions) if conditions else None
    interventions_text = SEPARATOR.join(intervention_names) if intervention_names else None
    valve_text = " ".join(filter(None, [title, conditions_text, interventions_text]))

    try:
        enrollment_int = int(enrollment_count) if enrollment_count is not None else None
    except (TypeError, ValueError):
        issues.append(QualityIssue(nct_id, "enrollment_count", f"not an integer: {enrollment_count}"))
        enrollment_int = None

    return TrialRecord(
        nct_id=nct_id,
        title=title,
        lead_sponsor_raw=sponsor_raw,
        lead_sponsor_class=sponsor_class,
        sponsor=normalize_sponsor(sponsor_raw, config["sponsors"]),
        overall_status=status,
        phase=SEPARATOR.join(phases) if phases else None,
        conditions=conditions_text,
        interventions=interventions_text,
        intervention_types=SEPARATOR.join(intervention_types) if intervention_types else None,
        enrollment_count=enrollment_int,
        enrollment_type=enrollment_type,
        start_date=parse_dated(start_raw, "start_date"),
        primary_completion_date=parse_dated(pc_raw, "primary_completion_date"),
        primary_completion_type=pc_type,
        completion_date=parse_dated(completion_raw, "completion_date"),
        last_update_date=parse_dated(update_raw, "last_update_date"),
        valve_type=classify_valve(valve_text, config["valve_types"]),
        site_count=len(sites),
        sites=sites,
        issues=issues,
    )


def parse_studies(studies: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[TrialRecord], int]:
    """Parse and dedupe by NCT ID. Returns records and the count of skipped objects."""
    seen: dict[str, TrialRecord] = {}
    skipped = 0
    for study in studies:
        record = parse_study(study, config)
        if record is None:
            skipped += 1
            continue
        seen.setdefault(record.nct_id, record)
    return list(seen.values()), skipped
