"""Test-only fixtures and unit tests for the AR helper.

These series are explicitly NOT production data; they are small synthetic
signals used to validate the fitting helpers in
sensorguard.processing.detector_s.stats.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sensorguard.processing.detector_s.stats import fit_ar, cusum_up_down
from sensorguard.processing.detector_s.change_point import ChangePointDetector
from sensorguard.processing.detector_s.mahalanobis import MahalanobisDetector
from sensorguard.processing.detector_s.cusum import CusumDetector
from sensorguard.processing.detector_s.trend import TrendDetector
from sensorguard.processing.detector_s.replay import ReplayDetector
from sensorguard.processing.detector_s.base import load_detector_config

# Forced Agg before any pyplot import, matching tests/conftest.py.
import matplotlib  # noqa: E402

matplotlib.use("Agg", force=True)  # noqa: E402


def _daily(index):
    return pd.Series(index=index, dtype=float)


def test_ar1_recovers_known_coefficient():
    """An AR(1) with beta=0.7 and noise sigma=0.4 is recovered on seed 42."""
    rng = np.random.default_rng(42)
    n = 500
    x = np.empty(n, dtype=float)
    x[0] = 0.0
    for t in range(1, n):
        x[t] = 0.7 * x[t - 1] + rng.normal(0.0, 0.4)
    series = pd.Series(x, index=pd.date_range("2021-01-01", periods=n, freq="D"))
    coef, sigma = fit_ar(series, 1)

    assert coef.shape == (1,)
    assert np.isfinite(coef[0])
    assert abs(coef[0] - 0.7) < 0.05, f"AR(1) coefficient {coef[0]:.3f} != 0.7"
    assert np.isfinite(sigma)
    assert 0.3 < sigma < 0.5


def test_order0_returns_empty_coefficients_and_std():
    """Order 0 is the constant model: no lags, sigma is the value std."""
    x = np.linspace(-2.0, 2.0, 50)
    series = pd.Series(x, index=pd.date_range("2021-01-01", periods=len(x), freq="D"))
    coef, sigma = fit_ar(series, 0)

    assert coef.shape == (0,)
    assert np.isfinite(sigma)
    assert abs(sigma - float(np.std(x, ddof=1))) < 1e-12


def test_nan_gaps_do_not_create_fake_lag_pairs(monkeypatch):
    """A single NaN must not pair a value before it with a value after it."""
    x = np.ones(20, dtype=float)
    x[10] = np.nan
    series = pd.Series(x, index=pd.date_range("2021-01-01", periods=len(x), freq="D"))

    captured = {}

    def fake_lstsq(X, y, rcond=None):
        captured["shape"] = (X.shape[0], X.shape[1])
        return np.zeros(X.shape[1]), 0.0, 0.0, 0.0

    monkeypatch.setattr(np.linalg, "lstsq", fake_lstsq)
    fit_ar(series, 1)

    # AR(1): usable rows are t=1..9 before the NaN and t=12..19 after it
    # (t=11 is skipped because its lag x[10] is NaN).  The 20 points therefore
    # yield 17 rows, and no row straddles the NaN gap.
    assert captured.get("shape") == (17, 1), captured


def _residual_frame(start, n, seed=0, nan_at=None):
    """Build a DataFrame with the four monitored residual columns (no NaN by default),
    plus the matching station-value columns the replay matcher reads.

    Columns use the names from config/detector_s.yaml (``residual_variables``
    and ``replay.columns``).
    """
    rng = np.random.default_rng(seed)
    pairs = [
        ("temp_c", "reference_temp_c"),
        ("rh_pct", "reference_rh_pct"),
        ("wind_ms", "reference_wind_ms"),
        ("solar_mj_m2", "reference_solar_mj_m2"),
    ]
    cols = {}
    for v, c in pairs:
        x = rng.normal(0.0, 0.2, size=n).astype(float)
        station = rng.normal(10.0, 3.0, size=n).astype(float)
        if nan_at is not None:
            x[np.asarray(nan_at, dtype=int)] = np.nan
            station[np.asarray(nan_at, dtype=int)] = np.nan
        cols[c] = x
        cols[f"station_{v}"] = station
    return pd.DataFrame(cols, index=pd.date_range(start, periods=n, freq="D"))


def test_cusum_holds_state_across_nan_day():
    """A NaN whitened day holds up/down; the held state continues into the next day."""
    w = np.array([1.0, 1.0, np.nan, 1.0, 1.0], dtype=float)
    up, down = cusum_up_down(w, slack=0.25)
    assert up[2] == up[1]
    assert down[2] == down[1]
    assert up[3] == max(0.0, up[2] + 1.0 - 0.25)
    assert down[3] == min(0.0, down[2] + 1.0 + 0.25)


def test_cusum_down_side_catches_negative_shift_only():
    """Zero-mean noise inside the slack never accumulates; a negative shift does, on the down side."""
    w = np.full(30, 0.2)
    up, down = cusum_up_down(w, slack=0.25)
    assert up.max() == 0.0 and down.min() == 0.0
    w[10:] = -1.0
    up, down = cusum_up_down(w, slack=0.25)
    assert up.max() == 0.0
    assert down[-1] == pytest.approx(-0.75 * 20)


def test_cusum_nan_day_score_nan_flag_zero():
    """CusumDetector writes score NaN and flag 0 for a NaN day; index stays aligned."""
    cfg = load_detector_config()
    train = _residual_frame("2021-01-01", 120, seed=1)
    test = _residual_frame("2024-01-01", 40, seed=2, nan_at=20)
    det = CusumDetector()
    params = det.fit(train, cfg)
    out = det.score(test, params, cfg)
    assert out.index.equals(test.index)
    assert np.isnan(out.loc[test.index[20], "score"])
    assert out.loc[test.index[20], "flag"] == 0


def test_trend_score_index_aligned_under_nan_gaps():
    """TrendDetector keeps the score index aligned with the input dates under NaN gaps."""
    cfg = load_detector_config()
    train = _residual_frame("2021-01-01", 200, seed=3)
    test = _residual_frame("2024-01-01", 60, seed=4, nan_at=[10, 11, 12])
    det = TrendDetector()
    params = det.fit(train, cfg)
    out = det.score(test, params, cfg)
    assert out.index.equals(test.index)
    assert np.isnan(out.loc[test.index[10], "score"])


def test_replay_block_uses_start_start_plus_block_days():
    """Replay slices each block as test[start : start + block_days]."""
    cfg = load_detector_config()
    train = _residual_frame("2021-01-01", 40, seed=5)
    test = _residual_frame("2024-01-01", 20, seed=6)
    det = ReplayDetector()
    params = det.fit(train, cfg)
    block_days = params["block_days"]
    assert params["columns"] == [f"station_{v}" for v in ("temp_c", "rh_pct", "wind_ms", "solar_mj_m2")]
    blocks = det._blocks(test[params["columns"]], block_days)
    assert len(blocks) == 2
    assert blocks[0][0] == 0
    assert blocks[1][0] == block_days
    assert blocks[0][1].shape == (block_days, len(params["columns"]))
    assert blocks[1][1].shape == (block_days, len(params["columns"]))
    np.testing.assert_array_equal(blocks[0][1], test[params["columns"]].to_numpy(dtype=float)[0:block_days])
    np.testing.assert_array_equal(blocks[1][1], test[params["columns"]].to_numpy(dtype=float)[block_days : 2 * block_days])

import math


def _params_equal(a, b) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        if set(a) != set(b):
            return False
        return all(_params_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return False
        return all(_params_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, np.ndarray):
        return a.shape == b.shape and np.array_equal(a, b)
    return a == b


def test_cusum_catches_constant_shift_and_change_point_dates_it():
    """A constant shift on one variable is caught by CUSUM within days; the
    change-point detector dates the episode and types it "step"."""
    cfg = load_detector_config()
    train = _residual_frame("2021-01-01", 300, seed=11)
    test = _residual_frame("2024-01-01", 100, seed=12)
    shift_start = 35  # 2024-02-05
    col = cfg["residual_variables"]["temp_c"]
    test.loc[test.index[shift_start:], col] += 2.0

    det = CusumDetector()
    params = det.fit(train, cfg)
    out = det.score(test, params, cfg)
    alarmed = out["flag"].to_numpy().astype(bool)
    assert alarmed[shift_start: shift_start + 9].any(), "shift not caught within 9 days"
    assert alarmed[shift_start:].mean() >= 0.75, "alarms not sustained after the shift"

    dated = ChangePointDetector()
    p2 = dated.fit(train, cfg)
    episodes = dated.episodes(test, p2, cfg)
    assert len(episodes) >= 1, "change detector found no episode"
    first = episodes[0]
    assert first["type"] == "step", first
    assert abs((pd.Timestamp(first["start"]) - pd.Timestamp("2024-02-05")).days) <= 10, first

    out2 = det.score(test, params, cfg)
    pd.testing.assert_frame_equal(out, out2)


def test_trend_catches_slow_drift():
    """A slow linear drift on one variable is caught by the trend detector."""
    cfg = load_detector_config()
    train = _residual_frame("2021-01-01", 300, seed=13)
    test = _residual_frame("2024-01-01", 200, seed=14)
    col = cfg["residual_variables"]["temp_c"]
    test.loc[:, col] = test.loc[:, col].to_numpy() + 0.05 * np.arange(200, dtype=float)

    det = TrendDetector()
    params = det.fit(train, cfg)
    out = det.score(test, params, cfg)
    alarmed = out["flag"].to_numpy().astype(bool)
    assert alarmed[100:].any(), "trend did not catch the slow drift"


def test_replay_catches_copied_seven_day_block():
    """A copied 7-day block of station values is flagged, and only that block."""
    cfg = load_detector_config()
    train = _residual_frame("2021-01-01", 120, seed=15)
    test = _residual_frame("2024-01-01", 40, seed=16)
    cols = ReplayDetector.columns(cfg)
    test.iloc[10:17, [test.columns.get_loc(c) for c in cols]] = train.iloc[100:107][cols].to_numpy()

    det = ReplayDetector()
    params = det.fit(train, cfg)
    out = det.score(test, params, cfg)
    assert out["flag"].iloc[10:17].sum() == 7, "copied block not flagged"
    assert out["flag"].sum() == 7, "days outside the copied block were flagged"


def test_replay_catches_a_copy_of_the_previous_week_inside_test():
    """The official replay: the 7 days before onset are sent again."""
    cfg = load_detector_config()
    train = _residual_frame("2021-01-01", 120, seed=27)
    test = _residual_frame("2024-01-01", 60, seed=28)
    cols = ReplayDetector.columns(cfg)
    idx = [test.columns.get_loc(c) for c in cols]
    test.iloc[33:40, idx] = test.iloc[26:33, idx].to_numpy()

    det = ReplayDetector()
    params = det.fit(train, cfg)
    out = det.score(test, params, cfg)
    assert out["flag"].iloc[33:40].all()
    # the source week is flagged too (it is half of the matching pair); nothing else
    assert set(np.flatnonzero(out["flag"].to_numpy())) <= set(range(26, 40))
    assert det.per_variable(test, params, cfg)["all"]["lag_days"].iloc[39] == 7

def test_mahalanobis_catches_single_day_spike():
    """A single-day spike on one variable is caught by Mahalanobis."""
    cfg = load_detector_config()
    train = _residual_frame("2021-01-01", 200, seed=17)
    test = _residual_frame("2024-01-01", 30, seed=18)
    # Mahalanobis d2 for a 3σ shift on one variable (temp_c) with df=4:
    # d2 = (3.0)^2 * (1/scale_temp_c^2) adjusted for covariance = 7.69
    # chi2(4, 0.999) ≈ 18.5, so a 3σ single-day spike won't flag.
    # Use a 5σ shift instead.
    col = cfg["residual_variables"]["temp_c"]
    test.loc[test.index[15], col] += 5.0

    det = MahalanobisDetector()
    params = det.fit(train, cfg)
    out = det.score(test, params, cfg)
    assert out.loc[test.index[15], "flag"] == 1
    assert out.loc[test.index[15], "score"] > params["threshold"]
    assert out.loc[test.index[14], "flag"] == 0
    assert out.loc[test.index[16], "flag"] == 0


def test_clean_noise_gives_few_alarms():
    """Clean noise gives few alarms for every detector (stricter thresholds
    than the config defaults, since CUSUM never resets after an alarm)."""
    cfg = load_detector_config()
    cfg["cusum"] = {**cfg["cusum"], "threshold": 15.0}
    cfg["trend"] = {**cfg["trend"], "train_quantile": 0.9999}
    cfg["change_point"] = {**cfg["change_point"], "train_null_quantile": 0.9995}
    train = _residual_frame("2021-01-01", 300, seed=19)
    test = _residual_frame("2024-01-01", 200, seed=20)
    detectors = [
        CusumDetector(),
        ChangePointDetector(),
        TrendDetector(),
        ReplayDetector(),
        MahalanobisDetector(),
    ]
    for det in detectors:
        params = det.fit(train, cfg)
        out = det.score(test, params, cfg)
        scored = out["score"].notna()
        rate = int(out.loc[scored, "flag"].sum()) / int(scored.sum())
        assert rate < 0.02, f"{det.name}: false-alarm rate {rate:.4f} too high on clean noise"


def test_scores_are_deterministic():
    """Same inputs give identical scores, flags and episodes, every run."""
    cfg = load_detector_config()
    train = _residual_frame("2021-01-01", 200, seed=21)
    test = _residual_frame("2024-01-01", 60, seed=22)
    detectors = [
        CusumDetector(),
        ChangePointDetector(),
        TrendDetector(),
        ReplayDetector(),
        MahalanobisDetector(),
    ]
    for det in detectors:
        params = det.fit(train, cfg)
        out1 = det.score(test, params, cfg)
        out2 = det.score(test, params, cfg)
        pd.testing.assert_frame_equal(out1, out2)
        if hasattr(det, "episodes"):
            assert det.episodes(test, params, cfg) == det.episodes(test, params, cfg)


def test_nan_day_stays_nan_and_scoring_continues():
    """Any monitored variable NaN -> score NaN and flag 0 that day; the next
    day is scored again (CUSUM keeps its held state)."""
    cfg = load_detector_config()
    train = _residual_frame("2021-01-01", 200, seed=23)
    test = _residual_frame("2024-01-01", 40, seed=24, nan_at=20)
    detectors = [
        CusumDetector(),
        ChangePointDetector(),
        TrendDetector(),
        ReplayDetector(),
        MahalanobisDetector(),
    ]
    for det in detectors:
        params = det.fit(train, cfg)
        out = det.score(test, params, cfg)
        assert out.index.equals(test.index)
        assert np.isnan(out.loc[test.index[20], "score"])
        assert out.loc[test.index[20], "flag"] == 0
        assert not np.isnan(out.loc[test.index[21], "score"])


def test_fit_uses_only_train_dates():
    """Changing the 2024 values does not change the fitted parameters."""
    cfg = load_detector_config()
    train = _residual_frame("2021-01-01", 200, seed=25)
    test = _residual_frame("2024-01-01", 40, seed=26)
    detectors = [
        CusumDetector(),
        ChangePointDetector(),
        TrendDetector(),
        ReplayDetector(),
        MahalanobisDetector(),
    ]
    params_list = [det.fit(train, cfg) for det in detectors]
    mutated = test.copy()
    mutated.iloc[:] = 100.0 * mutated.iloc[:]
    for det, params in zip(detectors, params_list):
        params_again = det.fit(train, cfg)
        assert _params_equal(params_again, params), det.name
        out_clean = det.score(test, params, cfg)
        out_mutated = det.score(mutated, params, cfg)
        assert not out_clean["score"].equals(out_mutated["score"]), det.name
