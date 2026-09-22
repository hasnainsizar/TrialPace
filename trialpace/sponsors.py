from __future__ import annotations

from typing import Any


def normalize_sponsor(raw_name: str | None, sponsor_config: dict[str, Any]) -> tuple[str, str]:
    """Map a lead sponsor name onto (sponsor_group, mapped_via).

    Direct groups match on the start of the name. The parent map then matches
    anywhere in the name, so affiliates and acquired companies are grouped
    without letting a substring hijack an unrelated direct match.
    """
    default = str(sponsor_config.get("default", "Other"))
    unmapped = str(sponsor_config.get("unmapped_via", "none"))
    if not raw_name:
        return default, unmapped
    lowered = raw_name.lower().strip()
    direct: dict[str, list[str]] = sponsor_config.get("direct", {})
    for group, prefixes in direct.items():
        if any(lowered.startswith(prefix.lower()) for prefix in prefixes):
            return group, "direct"
    for rule in sponsor_config.get("parent_map", []):
        if str(rule["pattern"]).lower() in lowered:
            return str(rule["group"]), str(rule["mapped_via"])
    return default, unmapped


def sponsor_groups(sponsor_config: dict[str, Any]) -> list[str]:
    """Every group name the config can produce, default last."""
    groups = list(sponsor_config.get("direct", {}).keys())
    for rule in sponsor_config.get("parent_map", []):
        if rule["group"] not in groups:
            groups.append(str(rule["group"]))
    groups.append(str(sponsor_config.get("default", "Other")))
    return groups


def classify_valve(text: str, valve_config: dict[str, Any]) -> str:
    """Pick the valve type whose keywords appear first in the config order."""
    lowered = text.lower()
    keywords: dict[str, list[str]] = valve_config.get("keywords", {})
    for valve_type, words in keywords.items():
        if any(word.lower() in lowered for word in words):
            return valve_type
    return str(valve_config.get("default", "other"))
