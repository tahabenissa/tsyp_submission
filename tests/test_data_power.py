"""Tests for cache.py and power.py. No internet needed (download is faked)."""

import json

import numpy as np
import pytest

from sensorguard import schema
from sensorguard.data import power
from sensorguard.data.cache import (
    load_if_valid,
    save_with_checksum,
    sha256_of_bytes,
    sha256_of_file,
)

FAKE_JSON = json.dumps(
    {
        "properties": {
            "parameter": {
                "T2M": {"20240101": 10.0, "20240102": -999.0},
                "RH2M": {"20240101": 50.0, "20240102": 55.0},
                "WS2M": {"20240101": 2.0, "20240102": 3.0},
                "PRECTOTCORR": {"20240101": 0.0, "20240102": 1.5},
                "ALLSKY_SFC_SW_DWN": {"20240101": 8.0, "20240102": 9.0},
            }
        }
    }
).encode()


def test_checksum_is_stable_and_matches_file(tmp_path):
    p = save_with_checksum(tmp_path, "a.bin", b"hello")
    assert sha256_of_file(p) == sha256_of_bytes(b"hello")


def test_cache_detects_a_changed_file(tmp_path):
    p = save_with_checksum(tmp_path, "a.bin", b"hello")
    assert load_if_valid(tmp_path, "a.bin") == p
    p.write_bytes(b"hello!")  # someone edits the file
    assert load_if_valid(tmp_path, "a.bin") is None


def test_second_call_uses_cache_not_network(tmp_path, monkeypatch):
    calls = []

    def fake_download(lat, lon, start, end):
        calls.append(1)
        return FAKE_JSON

    monkeypatch.setattr(power, "_download", fake_download)
    df1 = power.fetch_power_daily(36.8, 10.18, "2024-01-01", "2024-01-02", tmp_path)
    df2 = power.fetch_power_daily(36.8, 10.18, "2024-01-01", "2024-01-02", tmp_path)
    assert len(calls) == 1          # downloaded only once
    assert df1.equals(df2) or df1.fillna(-1).equals(df2.fillna(-1))


def test_offline_without_copy_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        power.fetch_power_daily(
            36.8, 10.18, "2024-01-01", "2024-01-02", tmp_path, offline=True
        )


def test_missing_value_becomes_nan():
    df = power.parse_power_json(FAKE_JSON)
    assert np.isnan(df.loc["2024-01-02", schema.TEMP])
    assert df.loc["2024-01-01", schema.TEMP] == 10.0
    assert list(df.index.strftime("%Y%m%d")) == ["20240101", "20240102"]


def test_output_follows_shared_schema():
    df = power.parse_power_json(FAKE_JSON)
    schema.validate_daily_table(df)  # raises if the format is wrong