"""Shared data format (PROPOSAL, to be agreed by the team).

Every daily series in the project (NASA POWER, station, attacked series)
is a pandas table with:
  - index : one row per day, named "date", no time zone
  - columns : the five names below, in this order
  - missing value : NaN (never 0, never -999)
  - units : fixed, see UNITS

If the team changes a name or a unit, change it HERE only.
"""

from __future__ import annotations

import pandas as pd

TEMP = "temp_c"
HUMIDITY = "humidity_pct"
WIND = "wind_ms"
RAIN = "rain_mm"
SOLAR = "solar_mj_m2_day"

COLUMNS = [TEMP, HUMIDITY, WIND, RAIN, SOLAR]

UNITS = {
    TEMP: "degC (air temperature at 2 m)",
    HUMIDITY: "% (relative humidity at 2 m)",
    WIND: "m/s (wind speed at 2 m)",
    RAIN: "mm/day (daily total)",
    SOLAR: "MJ/m2/day (daily total, downward shortwave)",
}


def validate_daily_table(df: pd.DataFrame) -> None:
    """Raise ValueError if the table does not follow the shared format."""
    if list(df.columns) != COLUMNS:
        raise ValueError(f"Columns must be {COLUMNS}, got {list(df.columns)}")
    if df.index.name != "date":
        raise ValueError("Index must be named 'date'")
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is not None:
        raise ValueError("Index must be a DatetimeIndex without time zone")
    if not df.index.is_monotonic_increasing or df.index.has_duplicates:
        raise ValueError("Dates must be sorted and unique")