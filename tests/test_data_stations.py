"""Tests for stations.py. No internet needed (the download is faked)."""

import numpy as np
import pandas as pd
import pytest

from sensorguard import schema
from sensorguard.data import stations


def _fake_raw():
    return pd.DataFrame(
        {
            "TIMESTAMP": pd.to_datetime(["2023-01-01", "2023-01-02", "2023-01-03"]),
            "TEMP2MAVG": [4.0, np.nan, 2.0],
            "RELHUM2MAVG": [80.0, 90.0, 85.0],
            "WSPD2MAVG": [2.0, 3.0, 4.0],
            "PRECIP": [0.0, 23.6, 0.25],
            "PRECIP2": [0.0, 0.0, np.nan],
            "SRAVG": [100.0, 200.0, 250.0],
        }
    )


def test_output_follows_shared_schema():
    out = stations.kansas_to_schema(_fake_raw())
    schema.validate_daily_table(out)


def test_solar_conversion_w_to_mj():
    out = stations.kansas_to_schema(_fake_raw())
    # 100 W/m2 for 24 h = 8.64 MJ/m2
    assert out[schema.SOLAR].iloc[0] == pytest.approx(8.64)


def test_rain_takes_larger_gauge_and_skips_nan():
    out = stations.kansas_to_schema(_fake_raw())
    assert out[schema.RAIN].iloc[1] == pytest.approx(23.6)
    assert out[schema.RAIN].iloc[2] == pytest.approx(0.25)  # other gauge is NaN


def test_missing_value_stays_nan():
    out = stations.kansas_to_schema(_fake_raw())
    assert np.isnan(out[schema.TEMP].iloc[1])


def test_second_call_uses_cache_not_network(tmp_path, monkeypatch):
    calls = []

    def fake_download(station, start, end):
        calls.append(1)
        return _fake_raw()

    monkeypatch.setattr(stations, "_download_kansas", fake_download)
    a = stations.fetch_kansas_daily("Some Station", "2023-01-01", "2023-01-03", tmp_path)
    b = stations.fetch_kansas_daily("Some Station", "2023-01-01", "2023-01-03", tmp_path)
    assert len(calls) == 1
    pd.testing.assert_frame_equal(a, b)


def test_offline_without_copy_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        stations.fetch_kansas_daily(
            "Some Station", "2023-01-01", "2023-01-03", tmp_path, offline=True
        )