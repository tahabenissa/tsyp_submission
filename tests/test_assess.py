"""File mode: loading any station table, and the whole defence on one series."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sensorguard import assess as A


def test_columns_are_recognised_whatever_their_name():
    cols = ["Date", "T2M", "RH2M", "WS2M", "PRECTOTCORR", "ALLSKY_SFC_SW_DWN", "T2M_MAX"]
    m = A.guess_columns(cols)
    assert m == {"temp_c": "T2M", "rh_pct": "RH2M", "wind_ms": "WS2M", "precip_mm": "PRECTOTCORR", "solar_mj_m2": "ALLSKY_SFC_SW_DWN"}
    assert A.guess_date_column(cols) == "Date"
    m = A.guess_columns(["day", "Temperature", "Relative Humidity", "Wind Speed", "Rain"])
    assert m["temp_c"] == "Temperature" and m["rh_pct"] == "Relative Humidity" and m["precip_mm"] == "Rain"
    assert m["solar_mj_m2"] is None


def test_to_daily_fills_the_calendar_averages_subdaily_and_drops_fill_codes():
    raw = pd.DataFrame({
        "time": ["2024-01-01 00:00", "2024-01-01 12:00", "2024-01-03 06:00"],
        "temp": [10.0, 20.0, -999.0],
        "rain": [1.0, 2.0, 0.5],
    })
    df = A.to_daily(raw, {"temp_c": "temp", "precip_mm": "rain"}, "time")
    assert list(df.index) == list(pd.date_range("2024-01-01", "2024-01-03"))
    assert df.loc["2024-01-01", "temp_c"] == 15.0          # mean
    assert df.loc["2024-01-01", "precip_mm"] == 3.0        # sum
    assert np.isnan(df.loc["2024-01-02", "temp_c"])        # missing day stays missing
    assert np.isnan(df.loc["2024-01-03", "temp_c"])        # -999 is a fill code
    assert df["rh_pct"].isna().all()                       # not in the file


def test_default_periods_fit_two_thirds_and_score_the_rest():
    idx = pd.date_range("2022-01-01", periods=900, freq="D")
    p = A.default_periods(idx)
    assert p["train_start"] == "2022-01-01"
    assert pd.Timestamp(p["validation_start"]) == pd.Timestamp(p["train_end"]) + pd.Timedelta(days=1)
    assert p["validation_end"] == str(idx[-1].date())
    assert (pd.Timestamp(p["train_end"]) - idx[0]).days + 1 == 600


@pytest.mark.skipif(not A.FUSION_FILE.is_file(), reason="fusion model not trained (scripts/train_fusion.py)")
def test_assess_runs_on_a_development_site_without_knowing_it():
    from sensorguard import pipeline as pl
    cfg = pl.load_config()
    station, power, (lat, lon) = pl.load_site("kansas", cfg)
    attack = pl.inject(station, pl.AttackSpec(attack="step", variables=("temp_c",), onset="2024-04-15",
                                              magnitude=0.12, relative_to="range", length_days=60))
    r = A.assess(attack.series, power, lat, lon, cfg["split"])          # no site: detector M off
    assert r.fusion_variant == "s_only"
    assert r.trust.index[0] == pd.Timestamp("2024-01-01")
    assert 0 <= r.probability.min() and r.probability.max() <= 1
    window = r.band.loc["2024-04-15":"2024-06-13"]
    assert (window != "trusted").any(), "a 12 % of range temperature step should at least de-weight the station"
    assert set(r.decisions.columns) == {"decision_as_received", "decision_with_defence", "confidence"}
