"""NASA POWER daily reference data (spec F1).

One function does the job: fetch_power_daily(lat, lon, start, end).
  1. If a valid local copy exists, use it (no internet needed).
  2. Otherwise download it, save it with a checksum, then use it.

Output columns follow the shared format defined in schema.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import requests

from sensorguard import schema
from sensorguard.data.cache import load_if_valid, save_with_checksum

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"

# NASA POWER name -> our column name (names and units are set in schema.py)
VARIABLES = {
    "T2M": schema.TEMP,
    "RH2M": schema.HUMIDITY,
    "WS2M": schema.WIND,
    "PRECTOTCORR": schema.RAIN,
    "ALLSKY_SFC_SW_DWN": schema.SOLAR,  # check the unit in the JSON header
}

MISSING_VALUE = -999.0  # NASA POWER uses -999 for "no data"
DEFAULT_CACHE_DIR = Path("data/raw/power")


def _to_yyyymmdd(date: str) -> str:
    """'2024-07-14' -> '20240714' (also accepts '20240714')."""
    return pd.Timestamp(date).strftime("%Y%m%d")


def _cache_name(lat: float, lon: float, start: str, end: str) -> str:
    return f"power_{lat:.3f}_{lon:.3f}_{start}_{end}.json"


def power_cache_name(lat: float, lon: float, start: str, end: str) -> str:
    """Return the cache filename for one POWER point request.

    ``start`` and ``end`` accept the same date forms as
    :func:`fetch_power_daily`.  The batch acquisition script uses this helper
    to report whether a response came from an already verified cache entry.
    """
    return _cache_name(
        lat,
        lon,
        _to_yyyymmdd(start),
        _to_yyyymmdd(end),
    )


def _download(lat: float, lon: float, start: str, end: str) -> bytes:
    params = {
        "parameters": ",".join(VARIABLES),
        "community": "AG",
        "latitude": lat,
        "longitude": lon,
        "start": start,
        "end": end,
        "format": "JSON",
    }
    resp = requests.get(POWER_URL, params=params, timeout=60)
    resp.raise_for_status()
    return resp.content


def parse_power_json(raw: bytes) -> pd.DataFrame:
    """Turn the NASA POWER JSON into a table: one row per day."""
    data = json.loads(raw)
    series = data["properties"]["parameter"]
    df = pd.DataFrame({VARIABLES[k]: v for k, v in series.items() if k in VARIABLES})
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df.index.name = "date"
    df = df.sort_index()[schema.COLUMNS]
    df = df.mask(df == MISSING_VALUE)  # -999 -> NaN (a gap, never a value)
    schema.validate_daily_table(df)
    return df


def fetch_power_daily(
    lat: float,
    lon: float,
    start: str,
    end: str,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    offline: bool = False,
) -> pd.DataFrame:
    """Daily reference series for a place and dates.

    start, end : 'YYYY-MM-DD' (or 'YYYYMMDD')
    offline    : if True, never use the network (raise if no local copy)
    """
    s, e = _to_yyyymmdd(start), _to_yyyymmdd(end)
    name = _cache_name(lat, lon, s, e)

    path = load_if_valid(cache_dir, name)
    if path is not None:
        return parse_power_json(path.read_bytes())

    # Do not replace a raw response whose fingerprint no longer matches.  It
    # is evidence of what was downloaded and needs an explicit investigation
    # or removal, rather than a silent replacement by a new API response.
    raw_path = Path(cache_dir) / name
    if raw_path.exists():
        raise ValueError(
            f"Cached POWER response {raw_path} has no valid checksum; "
            "refusing to overwrite raw source data."
        )

    if offline:
        raise FileNotFoundError(
            f"No valid local copy of {name} in {cache_dir} and offline=True."
        )

    raw = _download(lat, lon, s, e)
    url_info = f"{POWER_URL}?lat={lat}&lon={lon}&start={s}&end={e}"
    saved = save_with_checksum(cache_dir, name, raw, source=url_info)
    return parse_power_json(saved.read_bytes())
