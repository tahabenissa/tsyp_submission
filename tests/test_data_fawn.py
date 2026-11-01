"""Tests for the FAWN loader. Uses small fake files in the real FAWN format."""

import numpy as np
import pandas as pd
import pytest

from sensorguard import schema
from sensorguard.data import stations


def _rows(station, day, n=96, **over):
    """n readings (every 15 min) for one day, in the real FAWN column names."""
    t = pd.date_range(day, periods=n, freq="15min")
    d = {
        "Station ID": station,
        "Date Time": t.strftime("%Y-%m-%d %H:%M:%S"),
        "Temp @ 2m (C)": 20.0,
        "Relative Humidity (%)": 80.0,
        "Rainfall Amount (in)": 0.01,   # per 15 min
        "Wind Speed (mph)": 10.0,
        "Solar Radiation (w/m2)": 100.0,
    }
    d.update(over)
    return pd.DataFrame(d)


def test_daily_values_and_units():
    out = stations.fawn_to_schema(_rows(303, "2023-01-01"))
    schema.validate_daily_table(out)
    assert out[schema.TEMP].iloc[0] == pytest.approx(20.0)
    assert out[schema.HUMIDITY].iloc[0] == pytest.approx(80.0)
    # 96 x 0.01 in = 0.96 in = 24.384 mm
    assert out[schema.RAIN].iloc[0] == pytest.approx(24.384)
    # 100 W/m2 all day = 8.64 MJ/m2
    assert out[schema.SOLAR].iloc[0] == pytest.approx(8.64)


def test_wind_converted_to_ms_and_to_2m():
    mps = 10.0 * 0.44704
    kept = stations.fawn_to_schema(_rows(303, "2023-01-01"), wind_height_m=None)
    assert kept[schema.WIND].iloc[0] == pytest.approx(mps)
    at2m = stations.fawn_to_schema(_rows(303, "2023-01-01"), wind_height_m=10.0)
    assert at2m[schema.WIND].iloc[0] == pytest.approx(mps * 0.7479, rel=1e-3)


def test_partial_day_becomes_nan():
    raw = pd.concat([_rows(303, "2023-01-01"), _rows(303, "2023-01-02", n=40)])
    out = stations.fawn_to_schema(raw)
    assert out.loc["2023-01-01"].notna().all()
    assert out.loc["2023-01-02"].isna().all()


def test_missing_readings_do_not_count_as_zero():
    day = _rows(303, "2023-01-01")
    day.loc[:5, "Solar Radiation (w/m2)"] = np.nan   # 6 of 96 missing: still ok
    out = stations.fawn_to_schema(day)
    assert out[schema.SOLAR].iloc[0] == pytest.approx(8.64)


def test_fetch_keeps_one_station_and_gives_full_calendar(tmp_path):
    f = pd.concat(
        [
            _rows(303, "2023-01-01"),
            _rows(303, "2023-01-03"),                       # 2 Jan has no data
            _rows(999, "2023-01-01", **{"Temp @ 2m (C)": 5.0}),  # other station
        ]
    )
    f.to_csv(tmp_path / "fawn_2023.csv", index=False)
    out = stations.fetch_fawn_daily(303, "2023-01-01", "2023-01-03", tmp_path)
    assert len(out) == 3
    assert out[schema.TEMP].iloc[0] == pytest.approx(20.0)   # not the 5.0 one
    assert out.iloc[1].isna().all()                          # missing day


def test_no_file_gives_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        stations.fetch_fawn_daily(303, "2023-01-01", "2023-01-03", tmp_path)


def test_unknown_station_gives_clear_error(tmp_path):
    _rows(303, "2023-01-01").to_csv(tmp_path / "f.csv", index=False)
    with pytest.raises(ValueError):
        stations.fetch_fawn_daily(111, "2023-01-01", "2023-01-03", tmp_path)