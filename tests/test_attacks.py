"""Same seed gives the same series and labels; each attack changes exactly the labelled days."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from sensorguard.attacks.labels import base_quantity, check_daily, empty_labels
from sensorguard.attacks.official import apply_scenario, drift, expand, main, replay, select, step_bias

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def clean() -> pd.DataFrame:
    """Three years of fake daily weather: a seasonal cycle plus noise."""
    days = pd.date_range("2020-01-01", periods=3 * 365, freq="D", name="date")
    t = np.arange(len(days))
    rng = np.random.default_rng(42)
    season = np.sin(2 * np.pi * t / 365.25)
    return pd.DataFrame(
        {
            "T2M": 18 + 8 * season + rng.normal(0, 2, len(t)),
            "RH2M": np.clip(60 - 15 * season + rng.normal(0, 8, len(t)), 5, 99),
            "WS2M": np.abs(3 + rng.normal(0, 1, len(t))),
        },
        index=days,
    )


ONSET = pd.Timestamp("2021-06-01")


# ----------------------------------------------------------------- input checks


def test_rejects_missing_days(clean):
    with pytest.raises(ValueError):
        check_daily(clean.drop(clean.index[10]).index)


def test_input_is_never_modified(clean):
    before = clean.copy()
    step_bias(clean, ["T2M"], ONSET)
    drift(clean, ["T2M"], ONSET, ramp_days=30)
    replay(clean, ONSET)
    pd.testing.assert_frame_equal(clean, before)


# ----------------------------------------------------------------- step


def test_step_changes_exactly_the_labelled_days(clean):
    res = step_bias(clean, ["T2M"], ONSET, magnitude=0.12, sign=1, length_days=60)
    attacked = res.labels["attacked"]
    assert attacked.sum() == 60
    assert attacked.idxmax() == ONSET
    np.testing.assert_allclose(res.series.loc[attacked, "T2M"], clean.loc[attacked, "T2M"] * 1.12)
    pd.testing.assert_series_equal(res.series.loc[~attacked, "T2M"], clean.loc[~attacked, "T2M"])
    # other variables untouched
    pd.testing.assert_frame_equal(res.series[["RH2M", "WS2M"]], clean[["RH2M", "WS2M"]])
    assert (res.labels.loc[attacked, "fraction"] == 0.12).all()
    assert (res.labels.loc[attacked, "attack"] == "step").all()
    assert (res.labels.loc[~attacked, "episode_id"] == -1).all()


def test_step_negative_sign(clean):
    res = step_bias(clean, ["T2M"], ONSET, sign=-1, length_days=10)
    days = res.labels.index[res.labels["attacked"]]
    np.testing.assert_allclose(res.series.loc[days, "T2M"], clean.loc[days, "T2M"] * 0.88)


def test_step_until_end_when_no_length(clean):
    res = step_bias(clean, ["T2M"], ONSET)
    assert res.labels["attacked"].sum() == len(clean.loc[ONSET:])


# ----------------------------------------------------------------- the three meanings of "12 %"


def test_three_meanings_of_12_percent(clean):
    hist = clean.loc[: ONSET - pd.Timedelta(days=1), "T2M"]
    days = pd.date_range(ONSET, periods=5, freq="D")
    for relative_to, expected in [
        ("value", clean.loc[days, "T2M"] * 0.12),
        ("range", pd.Series(0.12 * (hist.quantile(0.99) - hist.quantile(0.01)), index=days)),
        ("std", pd.Series(0.12 * hist.std(), index=days)),
    ]:
        res = step_bias(clean, ["T2M"], ONSET, relative_to=relative_to, length_days=5)
        offset = res.series.loc[days, "T2M"] - clean.loc[days, "T2M"]
        np.testing.assert_allclose(offset, expected, err_msg=relative_to)


def test_range_and_std_ignore_the_attacked_days(clean):
    """The size of the attack must be set by clean history only."""
    poisoned = clean.copy()
    poisoned.loc[ONSET:, "T2M"] += 100
    a = base_quantity(clean["T2M"], "std", ONSET)
    b = base_quantity(poisoned["T2M"], "std", ONSET)
    assert a.iloc[0] == b.iloc[0]


def test_value_origin_kelvin(clean):
    res = step_bias(clean, ["T2M"], ONSET, length_days=1, value_origin={"T2M": -273.15})
    x = clean.loc[ONSET, "T2M"]
    assert res.series.loc[ONSET, "T2M"] == pytest.approx(x + 0.12 * (x + 273.15))


def test_limits_clip_and_are_labelled(clean):
    res = step_bias(clean, ["RH2M"], ONSET, magnitude=0.5, length_days=200, limits={"RH2M": [0, 100]})
    assert res.series["RH2M"].max() <= 100
    assert res.labels["clipped"].any()
    assert not res.labels.loc[~res.labels["attacked"], "clipped"].any()


# ----------------------------------------------------------------- drift


@pytest.mark.parametrize("ramp", [30, 60, 90])
def test_drift_ramps_to_15_percent(clean, ramp):
    res = drift(clean, ["T2M"], ONSET, magnitude=0.15, ramp_days=ramp)
    f = res.labels.loc[res.labels["attacked"], "fraction"].to_numpy()
    assert len(f) == ramp
    assert 0 < f[0] < 0.15 / ramp + 1e-12
    assert f[-1] == pytest.approx(0.15)
    assert (np.diff(f) > 0).all()
    days = res.labels.index[res.labels["attacked"]]
    np.testing.assert_allclose(res.series.loc[days, "T2M"], clean.loc[days, "T2M"] * (1 + f))


def test_drift_hold(clean):
    res = drift(clean, ["T2M"], ONSET, ramp_days=30, hold_days=20)
    f = res.labels.loc[res.labels["attacked"], "fraction"].to_numpy()
    assert len(f) == 50
    assert (f[29:] == pytest.approx(0.15))


# ----------------------------------------------------------------- replay


def test_replay_copies_seven_genuine_days(clean):
    res = replay(clean, ONSET, length_days=7, source_offset_days=28)
    days = res.labels.index[res.labels["attacked"]]
    assert len(days) == 7 and days[0] == ONSET
    src = days - pd.Timedelta(days=28)
    np.testing.assert_array_equal(res.series.loc[days].to_numpy(), clean.loc[src].to_numpy())
    assert (res.labels.loc[days, "source_date"].to_numpy() == src.to_numpy()).all()
    assert res.labels.loc[~res.labels["attacked"], "source_date"].isna().all()


def test_replay_source_must_not_overlap(clean):
    with pytest.raises(ValueError):
        replay(clean, ONSET, length_days=7, source_offset_days=3)


def test_replay_needs_history(clean):
    with pytest.raises(ValueError):
        replay(clean, clean.index[3], length_days=7, source_offset_days=7)


# ----------------------------------------------------------------- labels


def test_overlapping_episodes_are_refused(clean):
    first = step_bias(clean, ["T2M"], ONSET, length_days=30)
    with pytest.raises(ValueError):
        drift(first.series, ["RH2M"], ONSET + pd.Timedelta(days=10), labels=first.labels)


def test_empty_labels_are_clean(clean):
    lab = empty_labels(clean.index)
    assert not lab["attacked"].any() and (lab["attack"] == "none").all()


# ----------------------------------------------------------------- scenarios and seeds


@pytest.mark.parametrize("name", ["step_12pct", "drift_15pct", "replay_7d"])
def test_same_seed_same_result(clean, name):
    cfg = yaml.safe_load((ROOT / "scenarios" / "standard" / f"{name}.yaml").read_text(encoding="utf-8"))
    runs = [r for r in expand(cfg) if r.get("variables") in (None, "T2M", "RH2M", "WS2M")]
    assert runs
    run = runs[0]
    a, b = apply_scenario(clean, run), apply_scenario(clean, run)
    pd.testing.assert_frame_equal(a.series, b.series)
    pd.testing.assert_frame_equal(a.labels, b.labels)
    other = apply_scenario(clean, {**run, "seed": run["seed"] + 1})
    assert other.episodes[0].onset != a.episodes[0].onset


def test_onset_leaves_clean_history(clean):
    for seed in range(20):
        res = apply_scenario(clean, {"attack": "step", "variables": "T2M", "length_days": 60,
                                     "min_history_days": 365, "seed": seed})
        assert res.labels["attacked"].iloc[:365].sum() == 0


def test_expand_counts_runs():
    cfg = yaml.safe_load((ROOT / "scenarios" / "standard" / "drift_15pct.yaml").read_text(encoding="utf-8"))
    runs = expand(cfg)
    assert len(runs) == 7 * 2 * 3 * 3 * 3
    assert len({r["run_id"] for r in runs}) == len(runs)


def test_command_line_is_reproducible(clean, tmp_path):
    csv = tmp_path / "site.csv"
    clean.to_csv(csv)
    scenario = str(ROOT / "scenarios" / "standard" / "replay_7d.yaml")
    for out in ("a", "b"):
        assert main(["--scenario", scenario, "--input", str(csv), "--out", str(tmp_path / out)]) == 0
    files = sorted(p.relative_to(tmp_path / "a") for p in (tmp_path / "a").rglob("*.csv"))
    assert len(files) == 3 * 3 * 2 + 1
    for f in files:
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes()


def test_run_names_are_readable():
    cfg = yaml.safe_load((ROOT / "scenarios" / "standard" / "drift_15pct.yaml").read_text(encoding="utf-8"))
    names = {r["run_id"] for r in expand(cfg)}
    assert "T2M-up-value-ramp30-seed0" in names
    assert "RH2M-down-std-ramp90-seed2" in names
    cfg = yaml.safe_load((ROOT / "scenarios" / "standard" / "replay_7d.yaml").read_text(encoding="utf-8"))
    assert {r["run_id"] for r in expand(cfg)} >= {"back7-seed0", "back364-seed2"}


def test_select_keeps_only_matching_runs():
    cfg = yaml.safe_load((ROOT / "scenarios" / "standard" / "step_12pct.yaml").read_text(encoding="utf-8"))
    runs = select(expand(cfg), "T2M,up,value")
    assert [r["run_id"] for r in runs] == ["T2M-up-value-seed0", "T2M-up-value-seed1", "T2M-up-value-seed2"]
    assert select(expand(cfg), None) == expand(cfg)
    assert select(expand(cfg), "nothing") == []


def test_clean_removes_old_runs(clean, tmp_path):
    csv = tmp_path / "site.csv"
    clean.to_csv(csv)
    scenario = str(ROOT / "scenarios" / "standard" / "replay_7d.yaml")
    out = tmp_path / "out"
    main(["--scenario", scenario, "--input", str(csv), "--out", str(out)])
    (out / "old-run").mkdir()
    main(["--scenario", scenario, "--input", str(csv), "--out", str(out), "--only", "back7", "--clean"])
    assert sorted(p.name for p in out.iterdir() if p.is_dir()) == ["back7-seed0", "back7-seed1", "back7-seed2"]
