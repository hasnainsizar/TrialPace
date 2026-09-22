from __future__ import annotations

from typing import Any

import pytest

from trialpace.sponsors import classify_valve, normalize_sponsor, sponsor_groups


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Edwards Lifesciences", ("Edwards Lifesciences", "direct")),
        ("EDWARDS LIFESCIENCES LLC", ("Edwards Lifesciences", "direct")),
        ("JC Medical, Inc., an affiliate of Edwards Lifesciences LLC", ("Edwards Lifesciences", "affiliate")),
        ("Medtronic Cardiovascular", ("Medtronic", "direct")),
        ("Medtronic Bakken Research Center", ("Medtronic", "direct")),
        ("Boston Scientific Corporation", ("Boston Scientific", "direct")),
        ("Symetis SA", ("Boston Scientific", "acquisition")),
        ("Abbott Medical Devices", ("Abbott", "direct")),
        ("St. Jude Medical", ("Abbott", "acquisition")),
        ("University Hospital Somewhere", ("Other", "none")),
        ("", ("Other", "none")),
        (None, ("Other", "none")),
    ],
)
def test_normalize_sponsor(raw: str | None, expected: tuple[str, str], config: dict[str, Any]) -> None:
    assert normalize_sponsor(raw, config["sponsors"]) == expected


def test_direct_match_requires_name_to_start_with_pattern(config: dict[str, Any]) -> None:
    assert normalize_sponsor("Partners of Medtronic Foundation", config["sponsors"]) == ("Other", "none")


def test_parent_map_is_checked_after_direct(config: dict[str, Any]) -> None:
    sponsor_cfg = dict(config["sponsors"], parent_map=[{"pattern": "Edwards", "group": "Wrong Group", "mapped_via": "affiliate"}])
    assert normalize_sponsor("Edwards Lifesciences", sponsor_cfg) == ("Edwards Lifesciences", "direct")


def test_sponsor_groups_lists_every_group_default_last(config: dict[str, Any]) -> None:
    groups = sponsor_groups(config["sponsors"])
    assert groups[-1] == "Other"
    assert set(groups) == {"Edwards Lifesciences", "Medtronic", "Boston Scientific", "Abbott", "Other"}
    assert len(groups) == len(set(groups))


def test_valve_classification_prefers_specific_over_aortic(config: dict[str, Any]) -> None:
    assert classify_valve("TAVR for aortic stenosis", config["valve_types"]) == "aortic"
    assert classify_valve("Mitral Regurgitation; MitraClip", config["valve_types"]) == "mitral"
    assert classify_valve("Tricuspid regurgitation after TAVI", config["valve_types"]) == "tricuspid"
    assert classify_valve("Heart failure device", config["valve_types"]) == "other"
