"""Tests for the AZMET loader. No internet needed (the API is faked)."""

import numpy as np
import pandas as pd
import pytest

from sensorguard import schema
from sensorguard.data import stations


def _day(date, temp="13.5", rh="27", wind="6.8", rain="0.0", sol="17.86"):
    """One entry shaped like the real AZMET answer (all values are text)."""
    return {
        "datetime": date,
        "temp_air_meanC": temp,
        "relative_humidity_mean": rh,
        "wind_spd_mean_mps": wind,
        "precip_total_mm": rain,
        "sol_rad_total": sol,
        "meta_needs_review": "0",
        "meta_station_name": "Bonita",  # extra field, must be ignored
    }


def _raw():
    rows = [
        _day("2023-01-01"),
        _day("2023-01-02", temp="-999", rain="12.5"),  # missing temperature
        _day("2023-01-03", sol="9.0"),
    ]
    return pd.DataFrame(rows)[stations.AZMET_FIELDS]


def test_text_values_become_numbers_in_schema_format():
    out = stations.azmet_to_schema(_raw())
    schema.validate_daily_table(out)
    assert out[schema.TEMP].iloc[0] == pytest.approx(13.5)
    assert out[schema.WIND].iloc[0] == pytest.approx(6.8)
    assert out[schema.RAIN].iloc[1] == pytest.approx(12.5)
    assert out[schema.SOLAR].iloc[0] == pytest.approx(17.86)  # no conversion


def test_missing_code_becomes_nan():
    out = stations.azmet_to_schema(_raw())
    assert np.isnan(out[schema.TEMP].iloc[1])


def test_downloads_in_chunks_and_trims_to_requested_dates(monkeypatch):
    calls = []

    def fake_get(station, first_day, n_days):
        calls.append((first_day, n_days))
        days = pd.date_range(first_day, periods=n_days + 1)  # API gives one extra
        return [_day(d.strftime("%Y-%m-%d")) for d in days]

    monkeypatch.setattr(stations, "AZMET_CHUNK_DAYS", 30)
    monkeypatch.setattr(stations, "_get_azmet_json", fake_get)
    raw = stations._download_azmet("az09", "2023-01-01", "2023-03-31")  # 90 days
    assert len(calls) == 3
    assert len(raw) == 90
    assert raw["datetime"].min() == "2023-01-01"
    assert raw["datetime"].max() == "2023-03-31"


def test_second_call_uses_cache_and_gives_full_calendar(tmp_path, monkeypatch):
    calls = []

    def fake_download(station, start, end):
        calls.append(1)
        return _raw()  # only 3 days exist, the 4th will be a gap

    monkeypatch.setattr(stations, "_download_azmet", fake_download)
    a = stations.fetch_azmet_daily("az09", "2023-01-01", "2023-01-04", tmp_path)
    b = stations.fetch_azmet_daily("az09", "2023-01-01", "2023-01-04", tmp_path)
    assert len(calls) == 1
    assert len(a) == 4                       # one row per day
    assert a.iloc[3].isna().all()            # the missing day is NaN
    pd.testing.assert_frame_equal(a, b)


def test_offline_without_copy_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        stations.fetch_azmet_daily(
            "az09", "2023-01-01", "2023-01-04", tmp_path, offline=True
        )