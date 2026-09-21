from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from trialpace.config import load_config

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def config() -> dict[str, Any]:
    return load_config(ROOT / "config.yaml")


@pytest.fixture(scope="session")
def sample_studies() -> list[dict[str, Any]]:
    payload = json.loads((FIXTURES / "studies_sample.json").read_text(encoding="utf-8"))
    return payload["studies"]
