from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import requests

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def raw_day_dir(config: dict[str, Any], day: date) -> Path:
    return Path(config["paths"]["raw_dir"]) / day.isoformat()


def search_items(config: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (query parameter, value) pairs, one API query per item."""
    search = config["search"]
    items = [("query.cond", cond) for cond in search.get("conditions", [])]
    items += [("query.term", term) for term in search.get("terms", [])]
    return items


def build_params(config: dict[str, Any], query_param: str, value: str) -> dict[str, str]:
    search = config["search"]
    api = config["api"]
    advanced = (
        f"AREA[StudyType]{search['study_type']} AND "
        f"AREA[StartDate]RANGE[{search['start_date_min']},MAX]"
    )
    return {
        query_param: value,
        "filter.advanced": advanced,
        "fields": ",".join(api["fields"]),
        "pageSize": str(api["page_size"]),
        "countTotal": "true",
    }


def get_with_retry(session: requests.Session, url: str, params: dict[str, str], api: dict[str, Any]) -> dict[str, Any]:
    retries = int(api["max_retries"])
    backoff = float(api["backoff_seconds"])
    timeout = float(api["timeout_seconds"])
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = session.get(url, params=params, timeout=timeout)
            if response.status_code in RETRYABLE_STATUS:
                raise requests.HTTPError(f"HTTP {response.status_code}", response=response)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(backoff * (2**attempt))
    raise RuntimeError(f"Request failed after {retries + 1} attempts: {last_error}")


def fetch_query(config: dict[str, Any], query_param: str, value: str, out_dir: Path, session: requests.Session | None = None) -> int:
    """Fetch every page for one query into out_dir. Returns the study count."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    fields = list(config["api"]["fields"])
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("fields") == fields:
            return int(manifest.get("study_count", 0))
        for stale in out_dir.glob("page_*.json"):
            stale.unlink()

    session = session or requests.Session()
    params = build_params(config, query_param, value)
    url = config["api"]["base_url"]
    page = 0
    total = 0
    next_token: str | None = None
    while True:
        page += 1
        page_params = dict(params)
        if next_token:
            page_params["pageToken"] = next_token
        payload = get_with_retry(session, url, page_params, config["api"])
        (out_dir / f"page_{page:03d}.json").write_text(json.dumps(payload), encoding="utf-8")
        total += len(payload.get("studies", []))
        next_token = payload.get("nextPageToken")
        if not next_token:
            break
    manifest = {"query_param": query_param, "value": value, "pages": page, "study_count": total, "fields": fields}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return total


def fetch_all(config: dict[str, Any], day: date) -> dict[str, int]:
    """Fetch all search items for a day. Skips items already cached for that day."""
    session = requests.Session()
    counts: dict[str, int] = {}
    day_dir = raw_day_dir(config, day)
    for query_param, value in search_items(config):
        label = f"{query_param}={value}"
        counts[label] = fetch_query(config, query_param, value, day_dir / slugify(value), session)
    return counts


def iter_raw_studies(day_dir: Path) -> Iterator[dict[str, Any]]:
    """Yield every study JSON object cached under a day directory."""
    for page_path in sorted(day_dir.glob("*/page_*.json")):
        payload = json.loads(page_path.read_text(encoding="utf-8"))
        yield from payload.get("studies", [])


def list_raw_days(config: dict[str, Any]) -> list[date]:
    root = Path(config["paths"]["raw_dir"])
    if not root.exists():
        return []
    days = []
    for child in root.iterdir():
        try:
            days.append(date.fromisoformat(child.name))
        except ValueError:
            continue
    return sorted(days)
