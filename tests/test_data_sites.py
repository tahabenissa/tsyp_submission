"""Tests for site configuration and batch NASA POWER acquisition."""

from __future__ import annotations

import json

import pytest

from scripts import fetch_data
from sensorguard.data import power
from sensorguard.data.cache import save_with_checksum
from sensorguard.data.sites import load_sites


FAKE_JSON = json.dumps(
    {
        "properties": {
            "parameter": {
                "T2M": {"20240101": 10.0},
                "RH2M": {"20240101": 50.0},
                "WS2M": {"20240101": 2.0},
                "PRECTOTCORR": {"20240101": 0.0},
                "ALLSKY_SFC_SW_DWN": {"20240101": 8.0},
            }
        }
    }
).encode()


def write_sites(tmp_path, text: str):
    path = tmp_path / "sites.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_sites_validates_and_sorts_site_ids(tmp_path):
    path = write_sites(
        tmp_path,
        """sites:
  - id: bravo
    latitude: -34.5
    longitude: 18.4
    start: "2024-01-01"
    end: "2024-01-02"
    role: held_out
  - id: alpha
    latitude: 36.8
    longitude: 10.18
    start: 2024-01-01
    end: 2024-01-02
    role: development
""",
    )

    sites = load_sites(path)

    assert [site.site_id for site in sites] == ["alpha", "bravo"]
    assert sites[0].start == "2024-01-01"
    assert sites[1].role == "held_out"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("sites: [{}]", "missing end, id, latitude, longitude, role, start"),
        (
            """sites:
  - id: one
    latitude: 91
    longitude: 0
    start: "2024-01-01"
    end: "2024-01-02"
    role: development
""",
            "latitude",
        ),
        (
            """sites:
  - id: one
    latitude: 0
    longitude: 0
    start: "2024-01-03"
    end: "2024-01-02"
    role: development
""",
            "start must not be after end",
        ),
        (
            """sites:
  - id: one
    latitude: 0
    longitude: 0
    start: "2024-01-01"
    end: "2024-01-02"
    role: unknown
""",
            "role must be one of",
        ),
        (
            """sites:
  - id: one
    latitude: 0
    longitude: 0
    start: "2024-01-01"
    end: "2024-01-02"
    role: development
  - id: one
    latitude: 1
    longitude: 1
    start: "2024-01-01"
    end: "2024-01-02"
    role: held_out
""",
            "duplicated",
        ),
    ],
)
def test_load_sites_rejects_invalid_configurations(tmp_path, text, message):
    with pytest.raises(ValueError, match=message):
        load_sites(write_sites(tmp_path, text))


def test_batch_downloads_multiple_sites_once_then_uses_cache(tmp_path, monkeypatch):
    sites_path = write_sites(
        tmp_path,
        """sites:
  - id: beta
    latitude: 1.0
    longitude: 2.0
    start: "2024-01-01"
    end: "2024-01-01"
    role: held_out
  - id: alpha
    latitude: 3.0
    longitude: 4.0
    start: "2024-01-01"
    end: "2024-01-01"
    role: development
""",
    )
    calls = []

    def fake_download(lat, lon, start, end):
        calls.append((lat, lon, start, end))
        return FAKE_JSON

    monkeypatch.setattr(power, "_download", fake_download)
    first = fetch_data.fetch_configured_sites(sites_path, tmp_path / "cache")
    second = fetch_data.fetch_configured_sites(sites_path, tmp_path / "cache")

    assert [result.site_id for result in first] == ["alpha", "beta"]
    assert [result.outcome for result in first] == ["downloaded", "downloaded"]
    assert [result.outcome for result in second] == ["cached", "cached"]
    assert len(calls) == 2


def test_batch_offline_uses_cache_and_identifies_missing_site(tmp_path, monkeypatch):
    sites_path = write_sites(
        tmp_path,
        """sites:
  - id: cached-site
    latitude: 1.0
    longitude: 2.0
    start: "2024-01-01"
    end: "2024-01-01"
    role: development
  - id: missing-site
    latitude: 3.0
    longitude: 4.0
    start: "2024-01-01"
    end: "2024-01-01"
    role: held_out
""",
    )
    cache_dir = tmp_path / "cache"
    name = power.power_cache_name(1.0, 2.0, "2024-01-01", "2024-01-01")
    save_with_checksum(cache_dir, name, FAKE_JSON)
    monkeypatch.setattr(
        power,
        "_download",
        lambda *args: pytest.fail("offline mode made a network request"),
    )

    with pytest.raises(FileNotFoundError, match="missing-site"):
        fetch_data.fetch_configured_sites(sites_path, cache_dir, offline=True)


def test_batch_refuses_to_replace_invalid_raw_response(tmp_path, monkeypatch):
    sites_path = write_sites(
        tmp_path,
        """sites:
  - id: protected-source
    latitude: 1.0
    longitude: 2.0
    start: "2024-01-01"
    end: "2024-01-01"
    role: development
""",
    )
    cache_dir = tmp_path / "cache"
    name = power.power_cache_name(1.0, 2.0, "2024-01-01", "2024-01-01")
    response = save_with_checksum(cache_dir, name, FAKE_JSON)
    response.write_bytes(b"changed")
    monkeypatch.setattr(
        power,
        "_download",
        lambda *args: pytest.fail("invalid source data was overwritten"),
    )

    with pytest.raises(RuntimeError, match="protected-source"):
        fetch_data.fetch_configured_sites(sites_path, cache_dir)
