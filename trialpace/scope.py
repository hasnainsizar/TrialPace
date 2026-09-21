from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from trialpace.models import TrialRecord


@dataclass(frozen=True)
class FilterStep:
    step: str
    removed: int
    remaining: int


def has_device_intervention(record: TrialRecord, device_type: str) -> bool:
    types = (record.intervention_types or "").split("; ")
    return device_type in types


def has_transcatheter_term(record: TrialRecord, terms: list[str]) -> bool:
    text = " ".join(filter(None, [record.title, record.interventions])).lower()
    return any(term.lower() in text for term in terms)


def is_industry(record: TrialRecord, industry_class: str) -> bool:
    return (record.lead_sponsor_class or "").upper() == industry_class.upper()


def apply_scope(records: list[TrialRecord], scope_cfg: dict[str, Any]) -> tuple[list[TrialRecord], list[tuple[str, str]], list[FilterStep]]:
    """Apply the configured scope filters in order.

    Returns kept records, (nct_id, reason) pairs for removed records, and a per-step log.
    """
    steps: list[tuple[str, Callable[[TrialRecord], bool]]] = []
    if scope_cfg.get("require_device_intervention", False):
        device_type = str(scope_cfg.get("device_intervention_type", "DEVICE"))
        steps.append((f"no {device_type} intervention", lambda r: has_device_intervention(r, device_type)))
    if scope_cfg.get("require_transcatheter_term", False):
        terms = list(scope_cfg.get("transcatheter_terms", [])) + list(scope_cfg.get("product_names", []))
        steps.append(("no transcatheter term or product name in title or interventions", lambda r: has_transcatheter_term(r, terms)))
    if scope_cfg.get("industry_only", False):
        industry_class = str(scope_cfg.get("industry_sponsor_class", "INDUSTRY"))
        steps.append((f"lead sponsor class is not {industry_class}", lambda r: is_industry(r, industry_class)))

    log = [FilterStep("parsed", 0, len(records))]
    excluded: list[tuple[str, str]] = []
    kept = list(records)
    for reason, keep in steps:
        next_kept = []
        for record in kept:
            if keep(record):
                next_kept.append(record)
            else:
                excluded.append((record.nct_id, reason))
        log.append(FilterStep(reason, len(kept) - len(next_kept), len(next_kept)))
        kept = next_kept
    return kept, excluded, log
