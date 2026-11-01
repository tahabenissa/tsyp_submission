"""Real weather-station series (spec F2).

Each network has one loader. All loaders return a table in the shared
format of schema.py (index "date", five columns, NaN for missing values).

Done here: Kansas Mesonet, AZMET, FAWN.
"""

from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np
import pandas as pd

from sensorguard import schema
from sensorguard.data.cache import load_if_valid, save_with_checksum

DEFAULT_CACHE_DIR = Path("data/raw/stations")

# Kansas Mesonet API names (see the ksmesopy documentation)
KANSAS_VARIABLES = [
    "TEMP2MAVG",    # air temperature 2 m, degC
    "RELHUM2MAVG",  # relative humidity 2 m, %
    "WSPD2MAVG",    # wind speed 2 m, m/s
    "PRECIP",       # rain gauge 1, mm
    "PRECIP2",      # rain gauge 2, mm
    "SRAVG",        # solar radiation, daily mean power in W/m2
]

# Daily mean power (W/m2) -> daily energy (MJ/m2/day): x 86400 s / 1e6
W_M2_TO_MJ_M2_DAY = 0.0864


def kansas_to_schema(raw: pd.DataFrame) -> pd.DataFrame:
    """Convert a Kansas Mesonet daily table to the shared format."""
    df = raw.copy()
    df["date"] = pd.to_datetime(df["TIMESTAMP"]).dt.normalize()
    df = df.set_index("date").sort_index()

    out = pd.DataFrame(index=df.index)
    out[schema.TEMP] = df["TEMP2MAVG"]
    out[schema.HUMIDITY] = df["RELHUM2MAVG"]
    out[schema.WIND] = df["WSPD2MAVG"]
    # two tipping-bucket gauges: keep the larger value of the two
    # (max skips NaN, so one broken gauge does not hide the other)
    out[schema.RAIN] = df[["PRECIP", "PRECIP2"]].max(axis=1)
    out[schema.SOLAR] = df["SRAVG"] * W_M2_TO_MJ_M2_DAY

    out = out[schema.COLUMNS]
    schema.validate_daily_table(out)
    return out


def _download_kansas(station: str, start: str, end: str) -> pd.DataFrame:
    import ksmesopy as ms  # imported here so tests do not need the package

    return ms.request_data(
        station=station,
        start=start,
        end=end,
        interval="day",
        variables=KANSAS_VARIABLES,
    )


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text)


def fetch_kansas_daily(
    station: str,
    start: str,
    end: str,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    offline: bool = False,
) -> pd.DataFrame:
    """Daily station series from the Kansas Mesonet, in the shared format.

    Uses the local copy (checked with its checksum) if there is one.
    offline=True never uses the network.
    """
    name = f"kansas_{_slug(station)}_{start}_{end}.csv"

    path = load_if_valid(cache_dir, name)
    if path is None:
        if offline:
            raise FileNotFoundError(
                f"No valid local copy of {name} in {cache_dir} and offline=True."
            )
        raw = _download_kansas(station, start, end)
        path = save_with_checksum(
            cache_dir,
            name,
            raw.to_csv(index=False).encode("utf-8"),
            source="Kansas Mesonet API via ksmesopy",
        )

    raw = pd.read_csv(io.BytesIO(path.read_bytes()), parse_dates=["TIMESTAMP"])
    return kansas_to_schema(raw)


# ---------------------------------------------------------------------------
# AZMET (Arizona Meteorological Network)
# ---------------------------------------------------------------------------

AZMET_URL = "https://api.azmet.arizona.edu/v1/observations/daily"
AZMET_CHUNK_DAYS = 90  # several small requests are safer than one huge one

# raw AZMET field -> kept in the local copy
AZMET_FIELDS = [
    "datetime",                # date, "YYYY-MM-DD"
    "temp_air_meanC",          # air temperature, degC
    "relative_humidity_mean",  # %
    "wind_spd_mean_mps",       # m/s (check the sensor height, see docs)
    "precip_total_mm",         # mm/day
    "sol_rad_total",           # MJ/m2/day (426.86 ly = 17.86 MJ/m2)
    "meta_needs_review",       # AZMET quality flag, kept for later checks
]

# Codes that would be impossible real values for any of the five variables.
# Assumption: AZMET marks missing data with one of them. Check your NaN count.
AZMET_MISSING_CODES = [-999, -9999, 999, 9999]


def azmet_to_schema(raw: pd.DataFrame) -> pd.DataFrame:
    """Convert an AZMET daily table (text values) to the shared format."""
    df = raw.copy()
    df["date"] = pd.to_datetime(df["datetime"]).dt.normalize()
    df = df.set_index("date").sort_index()

    num = df[AZMET_FIELDS[1:6]].apply(pd.to_numeric, errors="coerce")
    num = num.replace(AZMET_MISSING_CODES, np.nan)

    out = pd.DataFrame(index=df.index)
    out[schema.TEMP] = num["temp_air_meanC"]
    out[schema.HUMIDITY] = num["relative_humidity_mean"]
    out[schema.WIND] = num["wind_spd_mean_mps"]
    out[schema.RAIN] = num["precip_total_mm"]
    out[schema.SOLAR] = num["sol_rad_total"]  # already MJ/m2/day

    out = out[~out.index.duplicated(keep="first")][schema.COLUMNS]
    schema.validate_daily_table(out)
    return out


def _get_azmet_json(station: str, first_day: str, n_days: int) -> list[dict]:
    """One request. 'P{k}D' returns the first day plus k more days."""
    import requests

    url = f"{AZMET_URL}/{station}/{first_day}T00:00/P{max(n_days - 1, 1)}D"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errors") and not payload.get("data"):
        raise RuntimeError(f"AZMET returned errors: {payload['errors']}")
    return payload.get("data", [])


def _download_azmet(station: str, start: str, end: str) -> pd.DataFrame:
    days = pd.date_range(start, end)
    rows: list[dict] = []
    for i in range(0, len(days), AZMET_CHUNK_DAYS):
        chunk = days[i : i + AZMET_CHUNK_DAYS]
        rows += _get_azmet_json(station, chunk[0].strftime("%Y-%m-%d"), len(chunk))
    raw = pd.DataFrame(rows)
    for col in AZMET_FIELDS:  # a field missing in the answer becomes NaN
        if col not in raw:
            raw[col] = np.nan
    raw = raw[AZMET_FIELDS].drop_duplicates(subset="datetime")
    d = pd.to_datetime(raw["datetime"])
    return raw[(d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))]


def fetch_azmet_daily(
    station: str,
    start: str,
    end: str,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    offline: bool = False,
) -> pd.DataFrame:
    """Daily station series from AZMET (station id like 'az09'), shared format.

    One row per day from start to end; a day with no data is a row of NaN.
    Uses the local copy (checked with its checksum) if there is one.
    """
    name = f"azmet_{_slug(station)}_{start}_{end}.csv"

    path = load_if_valid(cache_dir, name)
    if path is None:
        if offline:
            raise FileNotFoundError(
                f"No valid local copy of {name} in {cache_dir} and offline=True."
            )
        raw = _download_azmet(station, start, end)
        path = save_with_checksum(
            cache_dir,
            name,
            raw.to_csv(index=False).encode("utf-8"),
            source="AZMET daily API (api.azmet.arizona.edu)",
        )

    raw = pd.read_csv(io.BytesIO(path.read_bytes()), dtype=str)
    out = azmet_to_schema(raw)
    full = pd.date_range(start, end, name="date")
    return out.reindex(full)


# ---------------------------------------------------------------------------
# FAWN (Florida Automated Weather Network)
# ---------------------------------------------------------------------------
# FAWN gives yearly CSV files with one row every 15 minutes. The files are
# downloaded by hand from the FAWN "FTP: Yearly CSV Data" page and put in
# data/raw/fawn/ (not committed). This loader turns them into daily values.

FAWN_DIR = Path("data/raw/fawn")
FAWN_COLUMNS = [
    "Station ID",
    "Date Time",
    "Temp @ 2m (C)",
    "Relative Humidity (%)",
    "Rainfall Amount (in)",
    "Wind Speed (mph)",
    "Solar Radiation (w/m2)",
]
FAWN_MISSING_CODES = [-999, -9999]  # assumption, check your NaN count
FAWN_READINGS_PER_DAY = 96          # one every 15 minutes
FAWN_WIND_HEIGHT_M = 10.0           # FAWN wind mast (VERIFY on the FAWN
                                    # "Technical Information" page)
MPH_TO_MS = 0.44704
INCH_TO_MM = 25.4


def wind_to_2m_factor(height_m: float) -> float:
    """FAO-56 log profile: speed at 2 m = speed at height_m x this factor."""
    return 4.87 / math.log(67.8 * height_m - 5.42)


def fawn_to_schema(
    raw: pd.DataFrame,
    min_coverage: float = 0.9,
    wind_height_m: float | None = FAWN_WIND_HEIGHT_M,
) -> pd.DataFrame:
    """15-minute FAWN rows of ONE station -> daily table in the shared format.

    A day with fewer than min_coverage of its 96 readings (for a variable)
    gets NaN for that variable: a partial day would bias sums and means.
    wind_height_m=None keeps the wind as measured (no 2 m conversion).
    """
    df = raw.copy()
    df["date"] = pd.to_datetime(df["Date Time"]).dt.normalize()
    cols = FAWN_COLUMNS[2:]
    df[cols] = df[cols].apply(pd.to_numeric, errors="coerce")
    df[cols] = df[cols].replace(FAWN_MISSING_CODES, np.nan)

    g = df.groupby("date")
    enough = g[cols].count() >= min_coverage * FAWN_READINGS_PER_DAY

    out = pd.DataFrame(index=g.size().index)
    out.index.name = "date"
    out[schema.TEMP] = g["Temp @ 2m (C)"].mean()
    out[schema.HUMIDITY] = g["Relative Humidity (%)"].mean()
    wind = g["Wind Speed (mph)"].mean() * MPH_TO_MS
    if wind_height_m is not None:
        wind = wind * wind_to_2m_factor(wind_height_m)
    out[schema.WIND] = wind
    out[schema.RAIN] = g["Rainfall Amount (in)"].sum(min_count=1) * INCH_TO_MM
    # mean power (W/m2) x 86400 s / 1e6 = MJ/m2/day
    out[schema.SOLAR] = g["Solar Radiation (w/m2)"].mean() * W_M2_TO_MJ_M2_DAY

    for col, raw_col in [
        (schema.TEMP, "Temp @ 2m (C)"),
        (schema.HUMIDITY, "Relative Humidity (%)"),
        (schema.WIND, "Wind Speed (mph)"),
        (schema.RAIN, "Rainfall Amount (in)"),
        (schema.SOLAR, "Solar Radiation (w/m2)"),
    ]:
        out.loc[~enough[raw_col], col] = np.nan

    out = out[schema.COLUMNS]
    schema.validate_daily_table(out)
    return out


def _read_fawn_station(files: list[Path], station_id: int) -> pd.DataFrame:
    """Read big yearly files in blocks and keep only one station."""
    parts = []
    for f in files:
        for block in pd.read_csv(f, usecols=FAWN_COLUMNS, chunksize=200_000):
            parts.append(block[block["Station ID"] == station_id])
    if not parts:
        return pd.DataFrame(columns=FAWN_COLUMNS)
    return pd.concat(parts, ignore_index=True)


def fetch_fawn_daily(
    station_id: int,
    start: str,
    end: str,
    data_dir: str | Path = FAWN_DIR,
    wind_height_m: float | None = FAWN_WIND_HEIGHT_M,
) -> pd.DataFrame:
    """Daily series of one FAWN station, shared format, one row per day.

    Reads every *.csv in data_dir (the yearly FAWN files). Works offline.
    """
    files = sorted(Path(data_dir).glob("*.csv"))
    if not files:
        raise FileNotFoundError(
            f"No FAWN csv file in {data_dir}. Download the yearly files "
            "from the FAWN data page first."
        )
    raw = _read_fawn_station(files, int(station_id))
    if raw.empty:
        raise ValueError(f"No rows for FAWN station {station_id} in {data_dir}.")

    daily = fawn_to_schema(raw, wind_height_m=wind_height_m)
    full = pd.date_range(start, end, name="date")
    return daily.reindex(full)