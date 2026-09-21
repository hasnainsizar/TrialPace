from __future__ import annotations

from typing import Any


def normalize_sponsor(raw_name: str | None, sponsor_config: dict[str, Any]) -> str:
    """Map a lead sponsor name onto a canonical sponsor bucket from config."""
    default = str(sponsor_config.get("default", "Other"))
    if not raw_name:
        return default
    lowered = raw_name.lower()
    mapping: dict[str, list[str]] = sponsor_config.get("mapping", {})
    for canonical, patterns in mapping.items():
        if any(pattern.lower() in lowered for pattern in patterns):
            return canonical
    return default


def classify_valve(text: str, valve_config: dict[str, Any]) -> str:
    """Pick the valve type whose keywords appear first in the config order."""
    lowered = text.lower()
    keywords: dict[str, list[str]] = valve_config.get("keywords", {})
    for valve_type, words in keywords.items():
        if any(word.lower() in lowered for word in words):
            return valve_type
    return str(valve_config.get("default", "other"))
