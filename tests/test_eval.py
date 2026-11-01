"""Evaluation metrics: fair detection, latency, false alarms, Wilson interval, scenario grid."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sensorguard.eval import metrics
from sensorguard.eval.runner import load_eval_config, scenarios

DAYS = pd.date_range("2024-01-01", periods=40, freq="D")


def _flags(on_days):
    f = pd.Series(0, index=DAYS)
    f.iloc[list(on_days)] = 1
    return f


def test_alarm_that_also_fires_without_the_attack_is_not_a_detection():
    clean = _flags([12])
    attacked = _flags([12])
    out = metrics.episode_outcome(attacked, clean, DAYS[10], DAYS[20])
    assert not out["detected"]
    assert np.isnan(out["latency_days"])


def test_new_alarm_inside_the_window_is_a_detection_with_its_latency():
    clean = _flags([12])
    attacked = _flags([12, 15])
    out = metrics.episode_outcome(attacked, clean, DAYS[10], DAYS[20])
    assert out["detected"]
    assert out["latency_days"] == 5.0


def test_alarm_after_the_episode_ends_does_not_count():
    out = metrics.episode_outcome(_flags([25]), _flags([]), DAYS[10], DAYS[20])
    assert not out["detected"]


def test_alarm_events_count_runs_once():
    assert metrics.alarm_events(_flags([1, 2, 3, 10, 20, 21])) == 3
    assert metrics.alarm_events(_flags([])) == 0
    assert metrics.alarm_events(_flags([0])) == 1


def test_false_alarms_per_year_scales_with_length():
    f = pd.Series(0, index=pd.date_range("2024-01-01", periods=366, freq="D"))
    f.iloc[[10, 11, 100]] = 1
    out = metrics.false_alarms(f)
    assert out["false_alarms_per_year"] == pytest.approx(2 * 365.25 / 366)
    assert out["false_alarm_day_share"] == pytest.approx(3 / 366)


def test_wilson_interval():
    lo, hi = metrics.wilson(5, 10)
    assert lo < 0.5 < hi
    lo, hi = metrics.wilson(10, 10)
    assert hi == 1.0 and 0.6 < lo < 0.75          # 10/10 is not proof of 100 %
    assert np.isnan(metrics.wilson(0, 0)[0])


def test_onset_error_skips_episodes_present_in_the_clean_run():
    clean = [{"first_alarm": "2024-01-13", "start": "2024-01-05"}]
    attacked = clean + [{"first_alarm": "2024-01-16", "start": "2024-01-12"}]
    err = metrics.onset_error(attacked, DAYS[10], DAYS[20], clean)
    assert err == 1.0                              # estimated 12 Jan, true 11 Jan


def test_scenario_grid_stays_in_the_validation_year():
    ecfg = load_eval_config()
    grid = scenarios(ecfg)
    assert len({s.name for s in grid}) == len(grid)
    for s in grid:
        assert s.onset.startswith("2024-")
    n_var = len(ecfg["variables"]) * len(ecfg["signs"]) * len(ecfg["relative_to"])
    expected = (n_var * (len(ecfg["step"]["onsets"]) + len(ecfg["drift"]["ramp_days"]) * len(ecfg["drift"]["onsets"]))
                + len(ecfg["replay"]["source_offset_days"]) * len(ecfg["replay"]["onsets"]))
    assert len(grid) == expected
