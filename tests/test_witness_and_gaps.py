"""The humidity witness regression and the rolling-gap fusion features."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from sensorguard.detect import fusion
from sensorguard.processing import calibrate as C


def _power(days=900, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-01", periods=days, freq="D")
    season = np.sin(2 * np.pi * idx.dayofyear / 365.25)
    return pd.DataFrame({
        "temp_c": 15 + 10 * season + rng.normal(0, 2, days),
        "rh_pct": np.clip(60 - 15 * season + rng.normal(0, 8, days), 5, 100),
        "wind_ms": np.abs(3 + rng.normal(0, 1, days)),
        "precip_mm": np.clip(rng.exponential(1.0, days) - 0.5, 0, None),
        "solar_mj_m2": 18 + 8 * season + rng.normal(0, 2, days),
    }, index=idx)


def test_witness_regression_beats_the_raw_power_humidity():
    power = _power()
    rng = np.random.default_rng(1)
    # station humidity depends on POWER humidity AND temperature: raw POWER humidity misses part of it
    station = 0.7 * power["rh_pct"] - 0.8 * power["temp_c"] + 30 + rng.normal(0, 3, len(power))
    fit, test = power.index[:600], power.index[600:]
    model = C.fit_witness_model(station.loc[fit], power.loc[fit], alpha=10.0)
    pred = C.predict_witness(model, power.loc[test])
    err_model = (station.loc[test] - pred).std()
    err_raw = (station.loc[test] - power.loc[test, "rh_pct"]).std()
    assert err_model < 3.5 < err_raw                      # near the noise floor (3), raw POWER is not
    json.dumps(model)                                     # saves with the calibration


def test_witness_keeps_power_when_an_input_is_missing_and_clips_humidity():
    power = _power()
    model = C.fit_witness_model(power["rh_pct"] + 50, power, alpha=10.0)  # pushes predictions above 100
    gap = power.copy()
    gap.iloc[10, gap.columns.get_loc("wind_ms")] = np.nan
    out = C.witness(gap, {"witness_models": {"rh_pct": model}})
    assert out["rh_pct"].max() <= 100
    assert out["rh_pct"].iloc[10] == gap["rh_pct"].iloc[10]
    assert C.witness(power, {"witness_models": {}}) is power          # nothing configured: unchanged


def test_calibration_with_a_regression_witness_only_uses_the_fit_dates():
    power = _power()
    station = power.copy()
    station["rh_pct"] = power["rh_pct"] - 0.5 * power["temp_c"] + 10
    cfg = C.load_preparation_config()
    cfg["variables"]["rh_pct"]["reference_model"] = "regression"
    later = station.copy()
    later.loc["2022-06-01":, "rh_pct"] += 30                        # an "attack" after the fit window
    a = C.fit_reference_calibration(station, power, cfg, "2021-01-01", "2022-05-31")
    b = C.fit_reference_calibration(later, power, cfg, "2021-01-01", "2022-05-31")
    assert a["witness_models"]["rh_pct"]["coef"] == b["witness_models"]["rh_pct"]["coef"]


def test_rolling_gaps_are_causal_and_skip_rain():
    idx = pd.date_range("2024-01-01", periods=60, freq="D")
    r = pd.DataFrame(0.0, index=idx, columns=["temp_c", "rh_pct", "precip_mm"])
    r.loc["2024-02-01":, "rh_pct"] = 2.0
    r["precip_mm"] = 9.0                                            # rain never counts
    g = fusion.rolling_gaps(r, idx)
    assert (g.loc[:"2024-01-31"] == 0).all().all()                  # nothing before the shift
    assert g.loc["2024-02-07", "gap7"] == 2.0
    assert 0 < g.loc["2024-02-07", "gap30"] < 1                     # the month average lags behind
    assert (fusion.rolling_gaps(None, idx) == 0).all().all()


def test_rolling_gaps_are_scaled_by_the_station_s_own_training_gaps():
    idx = pd.date_range("2022-01-01", periods=800, freq="D")
    rng = np.random.default_rng(0)
    calm = pd.DataFrame({"temp_c": rng.normal(0, 1, 800)}, index=idx)
    noisy = calm * 2                                                # a station whose gaps are twice as large
    scored = idx[idx >= "2024-01-01"]
    a = fusion.rolling_gaps(calm, scored, scale_before=scored[0])
    b = fusion.rolling_gaps(noisy, scored, scale_before=scored[0])
    pd.testing.assert_frame_equal(a, b)                             # same evidence once scaled
    assert 0.3 < a["gap30"].median() < 1.0                          # clean days sit below the training 95th percentile
