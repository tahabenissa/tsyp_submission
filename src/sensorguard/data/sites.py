"""Load and validate configured data-acquisition sites."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import math
from pathlib import Path
from typing import Any

import yaml


SITE_ROLES = frozenset({"development", "held_out"})


@dataclass(frozen=True)
class Site:
    """One approved site and the daily reference period to acquire."""

    site_id: str
    latitude: float
    longitude: float
    start: str
    end: str
    role: str


def _config_error(path: Path, message: str) -> ValueError:
    return ValueError(f"Invalid site configuration {path}: {message}")


def _date_string(value: Any, field: str, path: Path, index: int) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise _config_error(path, f"site {index} field '{field}' must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise _config_error(
            path, f"site {index} field '{field}' must be YYYY-MM-DD"
        ) from exc


def _coordinate(
    value: Any, field: str, lower: float, upper: float, path: Path, index: int
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _config_error(path, f"site {index} field '{field}' must be a number")
    coordinate = float(value)
    if not math.isfinite(coordinate) or not lower <= coordinate <= upper:
        raise _config_error(
            path,
            f"site {index} field '{field}' must be between {lower} and {upper}",
        )
    return coordinate


def load_sites(path: str | Path) -> list[Site]:
    """Load approved sites from a YAML configuration file.

    The file must contain a ``sites`` list.  Each item requires ``id``,
    ``latitude``, ``longitude``, ``start``, ``end`` and ``role``.  Dates may
    be quoted ``YYYY-MM-DD`` strings or YAML date scalars.  An empty list is
    valid while the team has not approved any sites.
    """
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise _config_error(config_path, "YAML could not be parsed") from exc

    if not isinstance(raw, dict):
        raise _config_error(config_path, "top level must be a mapping")
    entries = raw.get("sites")
    if not isinstance(entries, list):
        raise _config_error(config_path, "field 'sites' must be a list")

    sites: list[Site] = []
    seen_ids: set[str] = set()
    required = {"id", "latitude", "longitude", "start", "end", "role"}
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise _config_error(config_path, f"site {index} must be a mapping")
        missing = sorted(required - entry.keys())
        if missing:
            raise _config_error(config_path, f"site {index} missing {', '.join(missing)}")

        site_id = entry["id"]
        if not isinstance(site_id, str) or not site_id.strip():
            raise _config_error(config_path, f"site {index} field 'id' must be non-empty")
        if site_id in seen_ids:
            raise _config_error(config_path, f"site ID '{site_id}' is duplicated")

        role = entry["role"]
        if role not in SITE_ROLES:
            allowed = ", ".join(sorted(SITE_ROLES))
            raise _config_error(
                config_path, f"site '{site_id}' role must be one of {allowed}"
            )

        start = _date_string(entry["start"], "start", config_path, index)
        end = _date_string(entry["end"], "end", config_path, index)
        if start > end:
            raise _config_error(config_path, f"site '{site_id}' start must not be after end")

        sites.append(
            Site(
                site_id=site_id,
                latitude=_coordinate(
                    entry["latitude"], "latitude", -90.0, 90.0, config_path, index
                ),
                longitude=_coordinate(
                    entry["longitude"], "longitude", -180.0, 180.0, config_path, index
                ),
                start=start,
                end=end,
                role=role,
            )
        )
        seen_ids.add(site_id)

    return sorted(sites, key=lambda site: site.site_id)
