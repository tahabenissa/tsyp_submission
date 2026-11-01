"""Fusion, trust score, responses and the water-balance product (step 4)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sensorguard.detect import fusion, trust_score
from sensorguard.detect.trust_score import DEWEIGHTED, QUARANTINED, TRUSTED, Bands
from sensorguard.product import water_balance as wb
from sensorguard.response import policy

DAYS = pd.date_range("2024-01-01", periods=60, freq="D")


# --------------------------------------------------------------------------- trust


def test_trust_falls_fast_and_recovers_slowly():
    p = pd.Series(0.0, index=DAYS)
    p.iloc[10] = 0.9
    t = trust_score.trust_series(p, fall_rate=0.5, recovery_rate=0.05)
    assert t.iloc[9] == 1.0
    assert t.iloc[10] == pytest.approx(0.55)
    # one quiet day gives back only 5 % of the lost trust
    assert t.iloc[11] == pytest.approx(1 - 0.45 * 0.95)
    # half of the loss comes back in about 14 quiet days
    assert 1 - t.iloc[10 + 14] == pytest.approx(0.45 * 0.95 ** 14)


def test_bands_from_clean_trust_quantiles():
    clean = pd.Series(np.linspace(0, 1, 1001))
    b = trust_score.fit_bands(clean, 0.05, 0.005)
    assert b.deweight == pytest.approx(0.05)
    assert b.quarantine == pytest.approx(0.005)


def test_quarantine_release_needs_trust_back_above_the_deweight_limit():
    bands = Bands(deweight=0.6, quarantine=0.3)
    t = pd.Series([0.9, 0.5, 0.2, 0.4, 0.55, 0.65, 0.5], index=DAYS[:7])
    b = trust_score.band_series(t, bands).tolist()
    assert b == [TRUSTED, DEWEIGHTED, QUARANTINED, QUARANTINED, QUARANTINED, TRUSTED, DEWEIGHTED]


# --------------------------------------------------------------------------- responses


def test_weight_is_one_when_trusted_zero_in_quarantine_linear_between():
    bands = Bands(deweight=0.6, quarantine=0.2)
    t = pd.Series([0.9, 0.4, 0.1], index=DAYS[:3])
    band = trust_score.band_series(t, bands)
    w = policy.weights(t, band, bands)
    assert w.tolist() == pytest.approx([1.0, 0.5, 0.0])


def test_only_implicated_variables_are_replaced():
    station = pd.DataFrame({"temp_c": 30.0, "precip_mm": 5.0}, index=DAYS[:3])
    reference = pd.DataFrame({"temp_c": 20.0, "precip_mm": 0.0}, index=DAYS[:3])
    imp = pd.DataFrame({"temp_c": True, "precip_mm": False}, index=DAYS[:3])
    used = policy.apply(station, reference, pd.Series([1.0, 0.5, 0.0], index=DAYS[:3]), imp)
    assert used["temp_c"].tolist() == [30.0, 25.0, 20.0]
    assert used["precip_mm"].tolist() == [5.0, 5.0, 5.0]


def test_implicated_uses_recent_residuals_and_replay_implicates_everything():
    res = pd.DataFrame({"temp_c": 0.0, "rh_pct": 0.0, "precip_mm": 3.0}, index=DAYS)
    res.iloc[30:, 0] = 2.0
    replay = pd.Series(False, index=DAYS)
    replay.iloc[50] = True
    imp = policy.implicated(res, replay, days=14, sd=1.0)
    assert not imp["temp_c"].iloc[29] and imp["temp_c"].iloc[45]
    assert not imp["rh_pct"].iloc[45]
    assert not imp["precip_mm"].iloc[45]          # rain never, unless replay
    assert imp.iloc[50].all()


def test_quarantine_raises_one_alert_with_a_reason():
    bands = Bands(deweight=0.6, quarantine=0.3)
    t = pd.Series([0.9, 0.5, 0.45, 0.2, 0.2, 0.7], index=DAYS[:6])
    band = trust_score.band_series(t, bands)
    contrib = pd.DataFrame({"cusum_ratio": 3.0, "maha_log": 0.1}, index=DAYS[:6])
    acts = policy.actions(t, band, contrib, verification_every_days=14)
    assert (acts["action"] == "alert").sum() == 1
    assert (acts["action"] == "quarantine").sum() == 1
    assert (acts["action"] == "release").sum() == 1
    assert (acts["action"] == "verification request").sum() == 1   # day 2: de-weighted and falling
    assert "CUSUM" in acts.loc[acts["action"] == "alert", "reason"].iloc[0]


# --------------------------------------------------------------------------- fusion


def test_fusion_probability_rises_with_the_evidence():
    rng = np.random.default_rng(0)
    n = 2000
    y = pd.Series(rng.random(n) < 0.2)
    x = pd.DataFrame({f: rng.normal(0, 1, n) for f in fusion.FEATURES})
    x["cusum_ratio"] += 2.0 * y
    model = fusion.fit(x, y)
    low = x.iloc[:1].assign(cusum_ratio=-2.0)
    high = x.iloc[:1].assign(cusum_ratio=4.0)
    assert model.probability(high).iloc[0] > 0.8 > 0.1 > model.probability(low).iloc[0]
    assert model.contributions(high).iloc[0].idxmax() == "cusum_ratio"


def test_prior_shift_moves_the_odds():
    p = pd.Series([0.5])
    assert fusion.prior_shift(p, 0.5, 0.5).iloc[0] == pytest.approx(0.5)
    assert fusion.prior_shift(p, 0.5, 0.1).iloc[0] == pytest.approx(0.1)


def test_reliability_and_scores_on_perfectly_calibrated_data():
    rng = np.random.default_rng(1)
    p = pd.Series(rng.random(20000))
    y = pd.Series(rng.random(20000) < p)
    table = fusion.reliability(p, y, 10)
    assert np.allclose(table["mean_probability"], table["attacked_share"], atol=0.03)
    s = fusion.scores(p, y)
    assert s["brier"] < s["brier_no_skill"]


# --------------------------------------------------------------------------- product


def _weather(temp=25.0, rh=50.0, wind=2.0, solar=22.0, rain=0.0, days=DAYS):
    return pd.DataFrame({"temp_c": temp, "rh_pct": rh, "wind_ms": wind, "solar_mj_m2": solar, "precip_mm": rain}, index=days)


def test_et0_is_plausible_and_responds_the_right_way():
    summer = pd.date_range("2024-07-01", periods=5, freq="D")
    base = wb.et0_fao56(_weather(days=summer), latitude=32.0).iloc[0]
    assert 4.0 < base < 8.0                        # mm/day, warm sunny day
    assert wb.et0_fao56(_weather(temp=30.0, days=summer), 32.0).iloc[0] > base
    assert wb.et0_fao56(_weather(rh=90.0, days=summer), 32.0).iloc[0] < base
    assert wb.et0_fao56(_weather(solar=10.0, days=summer), 32.0).iloc[0] < base


def test_water_balance_and_levels():
    df = _weather(rain=0.0)
    b = wb.water_balance(df, 32.0, window_days=30)
    assert b.iloc[:29].isna().all() and b.iloc[29] < 0
    levels = pd.DataFrame({"dry": -50.0, "severe": -100.0}, index=range(1, 13))
    bal = pd.Series([0.0, -60.0, -150.0, np.nan], index=DAYS[:4])
    assert wb.decision_levels(bal, levels).tolist()[:3] == [0.0, 1.0, 2.0]
    assert np.isnan(wb.decision_levels(bal, levels).iloc[3])
