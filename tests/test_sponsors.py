from __future__ import annotations

from typing import Any

import pytest

from trialpace.sponsors import classify_valve, normalize_sponsor


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Edwards Lifesciences", "Edwards Lifesciences"),
        ("EDWARDS LIFESCIENCES LLC", "Edwards Lifesciences"),
        ("Medtronic Cardiovascular", "Medtronic"),
        ("Medtronic Bakken Research Center", "Medtronic"),
        ("Boston Scientific Corporation", "Boston Scientific"),
        ("Abbott Medical Devices", "Abbott"),
        ("St. Jude Medical", "Abbott"),
        ("University Hospital Somewhere", "Other"),
        ("", "Other"),
        (None, "Other"),
    ],
)
def test_normalize_sponsor(raw: str | None, expected: str, config: dict[str, Any]) -> None:
    assert normalize_sponsor(raw, config["sponsors"]) == expected


def test_valve_classification_prefers_specific_over_aortic(config: dict[str, Any]) -> None:
    assert classify_valve("TAVR for aortic stenosis", config["valve_types"]) == "aortic"
    assert classify_valve("Mitral Regurgitation; MitraClip", config["valve_types"]) == "mitral"
    assert classify_valve("Tricuspid regurgitation after TAVI", config["valve_types"]) == "tricuspid"
    assert classify_valve("Heart failure device", config["valve_types"]) == "other"
