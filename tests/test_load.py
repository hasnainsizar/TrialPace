from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from trialpace import db
from trialpace.parse import parse_studies


def test_same_day_load_replaces_instead_of_duplicating(tmp_path: Path, config: dict[str, Any], sample_studies: list[dict[str, Any]]) -> None:
    records, _ = parse_studies(sample_studies, config)
    conn = db.connect(tmp_path / "test.db")
    day = date(2026, 1, 15)
    first = db.replace_snapshot(conn, day, records)
    second = db.replace_snapshot(conn, day, records)
    assert first == second
    trials = db.read_table(conn, "trials", day)
    sites = db.read_table(conn, "sites", day)
    assert len(trials) == 3
    assert len(sites) == 8
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1


def test_different_days_are_kept_separately(tmp_path: Path, config: dict[str, Any], sample_studies: list[dict[str, Any]]) -> None:
    records, _ = parse_studies(sample_studies, config)
    conn = db.connect(tmp_path / "test.db")
    db.replace_snapshot(conn, date(2026, 1, 15), records)
    db.replace_snapshot(conn, date(2026, 1, 16), records)
    assert len(db.read_table(conn, "trials")) == 6
    assert db.latest_snapshot(conn) == date(2026, 1, 16)
