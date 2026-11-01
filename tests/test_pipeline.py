"""End to end on one site: data -> attack -> layer 1 -> preparation -> screen."""

import numpy as np
import pandas as pd
import pytest

from sensorguard import pipeline as p

ONSET = pd.Timestamp("2024-04-01")


@pytest.fixture(scope="module")
def config():
    return p.load_config()


def test_missing_values_survive_the_signed_payload():
    values = [21.5, np.nan, 0.0, -3.25, 12.0]
    back = p.unpack(p.pack(values))
    assert np.isnan(back[1])
    assert back[0] == 21.5 and back[2] == 0.0 and back[3] == -3.25 and back[4] == 12.0


def test_no_attack_passes_untouched(config):
    r = p.run("fawn", p.AttackSpec("none"), config)
    assert r.trust.counts["rejected"] == 0 and r.trust.ledger_ok
    # FAWN has missing days: they stay missing, everything else arrives to 3 decimals
    pd.testing.assert_frame_equal(r.trust.received, r.station[p.VARIABLES], atol=1e-3, check_freq=False)
    assert not r.warnings


def test_p1_step_is_signed_and_accepted_so_only_residuals_can_see_it(config):
    r = p.run("azmet", p.AttackSpec("step", ("temp_c",), str(ONSET.date()), position="P1"), config)
    assert r.trust.counts["accepted"] == len(r.station) and r.trust.ledger_ok
    window = r.labels["attacked"]
    assert window.sum() == 60
    # the false values reached the analysis ...
    np.testing.assert_allclose(r.trust.received.loc[window, "temp_c"],
                               r.attack.series.loc[window, "temp_c"], atol=1e-3)
    # ... and push the temperature residual up inside the window
    res = r.prep.reference["temp_c"]
    assert res[window].mean() > res.loc["2024-01-01":][~window].mean() + 1


def test_p2_tampered_records_are_rejected_as_forged(config):
    r = p.run("azmet", p.AttackSpec("step", ("temp_c",), str(ONSET.date()), position="P2"), config)
    window = r.labels["attacked"]
    assert (r.trust.log.loc[window, "reason"] == "forged").all()
    assert r.trust.received.loc[window].isna().all().all()       # nothing false got through
    after = r.trust.log.loc[window[window].index[-1] + pd.Timedelta(days=1)]
    assert after["gap"]                                           # the chain shows the hole
    assert p.screen(r).loc["temp_c", "attack_days_reached"] == 0


def test_p2_replay_is_rejected_by_the_sequence_check(config):
    spec = p.AttackSpec("replay", onset=str(ONSET.date()), length_days=7, source_offset_days=28, position="P2")
    r = p.run("kansas", spec, config)
    window = r.labels["attacked"]
    assert (r.trust.log.loc[window, "reason"] == "replay").all()
    assert r.trust.counts["rejected"] == 7


def test_p3_store_rewrite_breaks_the_ledger_at_the_onset(config):
    spec = p.AttackSpec("drift", ("solar_mj_m2",), str(ONSET.date()), magnitude=0.15, position="P3")
    r = p.run("kansas", spec, config)
    assert r.trust.counts["rejected"] == 0                       # it happened after verification
    assert not r.trust.ledger_ok
    assert r.trust.ledger_first_broken == ONSET


def test_attack_in_training_years_is_warned(config):
    r = p.run("azmet", p.AttackSpec("step", ("temp_c",), "2022-06-01"), config)
    assert any("training" in w for w in r.warnings)


def test_save_writes_every_stage(config, tmp_path):
    r = p.run("azmet", p.AttackSpec("step", ("temp_c",), str(ONSET.date())), config)
    folder = p.save(r, tmp_path / "run", screen_table=p.screen(r))
    names = {f.name for f in folder.iterdir()}
    assert {"attacked.csv", "labels.csv", "episodes.csv", "received.csv", "layer1_log.csv",
            "residuals_reference.csv", "residuals_temporal.csv", "screen.csv"} <= names
    back = pd.read_csv(folder / "labels.csv", index_col=0, parse_dates=True)
    assert back["attacked"].sum() == 60
    assert p.run_name(r) == "azmet_step-temp_c-up_2024-04-01_P1"
