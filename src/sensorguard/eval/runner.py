"""Official standard scenario: every attack at every site, scored by every detector.

For each development site:

1. Load the clean station series and its NASA POWER witness.
2. Fit the preparation (calibration) and detector S on the train years of the
   CLEAN series, once.  Score the clean validation year: that gives the false
   alarms, and the clean flags that make detection fair (eval/metrics.py).
3. For each scenario of config/evaluation.yaml: inject the attack (always in
   the validation year), recompute the residuals with the same calibration,
   score with the same fitted detectors, and record per detector whether the
   episode was detected, how fast, and the onset error.

File mode, attacker at the station (P1): the station signs its own false
values, so layer 1 accepts everything and the series reaches detection as
injected.  Layers 1 at positions P2/P3 is evaluated separately (the pipeline
GUI and tests/test_pipeline.py).

Outputs in ``output_directory``:
    runs.csv          one row per (site, scenario, detector)
    false_alarms.csv  one row per (site, detector) on the clean validation year
    by_attack.csv     standard-scenario table per attack type
    by_variable.csv   standard-scenario table per variable
    summary.md        the tables above, in Markdown, for the report
"""

from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from sensorguard import pipeline as pl
from sensorguard.detect import statistical
from sensorguard.eval import metrics
from sensorguard.processing.residuals.reference import apply_reference_residuals

EVAL_CONFIG = pl.REPO_ROOT / "config" / "evaluation.yaml"

# Detector S components reported on their own, then the combined flag.
S_PARTS = ("cusum", "replay", "mahalanobis", "trend")


@dataclass
class Scenario:
    attack: str
    variable: str            # "all" for replay
    sign: int
    relative_to: str
    onset: str
    ramp_days: int = 0
    source_offset_days: int = 0

    @property
    def name(self) -> str:
        if self.attack == "replay":
            return f"replay_back{self.source_offset_days}_{self.onset}"
        size = f"_ramp{self.ramp_days}" if self.attack == "drift" else ""
        return f"{self.attack}_{self.variable}_{'up' if self.sign > 0 else 'down'}_{self.relative_to}{size}_{self.onset}"

    def spec(self, ecfg: dict[str, Any]) -> pl.AttackSpec:
        if self.attack == "step":
            c = ecfg["step"]
            return pl.AttackSpec(attack="step", variables=(self.variable,), onset=self.onset,
                                 magnitude=c["magnitude"], sign=self.sign, relative_to=self.relative_to,
                                 length_days=c["length_days"])
        if self.attack == "drift":
            c = ecfg["drift"]
            return pl.AttackSpec(attack="drift", variables=(self.variable,), onset=self.onset,
                                 magnitude=c["magnitude"], sign=self.sign, relative_to=self.relative_to,
                                 ramp_days=self.ramp_days, hold_days=c["hold_days"])
        c = ecfg["replay"]
        return pl.AttackSpec(attack="replay", onset=self.onset, length_days=c["length_days"],
                             source_offset_days=self.source_offset_days)


def load_eval_config(path: str | Path = EVAL_CONFIG) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def scenarios(ecfg: dict[str, Any]) -> list[Scenario]:
    out: list[Scenario] = []
    for var in ecfg["variables"]:
        for sign in ecfg["signs"]:
            for rel in ecfg["relative_to"]:
                for onset in ecfg["step"]["onsets"]:
                    out.append(Scenario("step", var, sign, rel, onset))
                for ramp in ecfg["drift"]["ramp_days"]:
                    for onset in ecfg["drift"]["onsets"]:
                        out.append(Scenario("drift", var, sign, rel, onset, ramp_days=ramp))
    for offset in ecfg["replay"]["source_offset_days"]:
        for onset in ecfg["replay"]["onsets"]:
            out.append(Scenario("replay", "all", 0, "", onset, source_offset_days=offset))
    return out


# --------------------------------------------------------------------------- detectors


def _s_flags(result: statistical.DetectorSResult) -> dict[str, pd.Series]:
    flags = {f"S:{p}": result.daily[f"{p}_flag"] for p in S_PARTS if f"{p}_flag" in result.daily}
    flags["S"] = result.daily["flag"]
    return flags


def _m_flags(series: pd.DataFrame, power: pd.DataFrame, site: str, index: pd.DatetimeIndex) -> pd.Series:
    from sensorguard.detect import learned
    m = learned.predict_detector_m(series, power, site)
    return m["is_anomaly"].reindex(index).fillna(0).astype(int)


# --------------------------------------------------------------------------- one site


def run_site(site: str, scenario_list: list[Scenario], ecfg: dict[str, Any],
             prep_cfg: dict[str, Any], dcfg: dict[str, Any] | None = None,
             progress=print) -> tuple[list[dict], list[dict]]:
    split = prep_cfg["split"]
    train_end = pd.Timestamp(split["train_end"])
    station, power, _coords = pl.load_site(site, prep_cfg)
    prep = pl.prepare(station, power, prep_cfg)          # fitted on clean train years
    model = statistical.fit(prep.reference, station, split, dcfg)
    clean_s = statistical.score(model, prep.reference, station)
    index = clean_s.daily.index
    clean = _s_flags(clean_s)
    with_m = bool(ecfg.get("include_detector_m", True))
    if with_m:
        clean["M"] = _m_flags(station, power, site, index)
        clean["S or M"] = (clean["S"].astype(bool) | clean["M"].astype(bool)).astype(int)

    fa_rows = [{"site": site, "detector": d, **metrics.false_alarms(f)} for d, f in clean.items()]
    rows: list[dict] = []
    t0 = time.perf_counter()
    for k, sc in enumerate(scenario_list, 1):
        attack = pl.inject(station, sc.spec(ecfg))
        if attack.labels.loc[:train_end, "attacked"].any():
            raise ValueError(f"{sc.name}: the attack touches the train years; the shared fit would be invalid")
        ep = attack.episodes[0]
        reference = apply_reference_residuals(attack.series, power, prep.calibration, prep_cfg)
        res = statistical.score(model, reference, attack.series)
        flags = _s_flags(res)
        if with_m:
            flags["M"] = _m_flags(attack.series, power, site, index)
            flags["S or M"] = (flags["S"].astype(bool) | flags["M"].astype(bool)).astype(int)
        err = metrics.onset_error(res.episodes, ep.onset, ep.end, clean_s.episodes)
        size = float(reference.loc[attack.labels["attacked"], sc.variable].mean()) if sc.variable in reference else np.nan
        for det, f in flags.items():
            out = metrics.episode_outcome(f, clean[det], ep.onset, ep.end)
            rows.append({
                "site": site, "scenario": sc.name, **asdict(sc), "detector": det,
                "end": str(ep.end.date()), "attack_days": int((ep.end - ep.onset).days + 1),
                "residual_shift_sd": size,
                "detected": out["detected"], "latency_days": out["latency_days"],
                "attacked_days_flagged": out["attacked_days_flagged"],
                "onset_error_days": err if det in ("S", "S:cusum") else np.nan,
            })
        if k % 25 == 0 or k == len(scenario_list):
            progress(f"[{site}] {k}/{len(scenario_list)} scenarios, {time.perf_counter() - t0:.0f} s")
    return rows, fa_rows


# --------------------------------------------------------------------------- tables


def _rate(group: pd.DataFrame) -> pd.Series:
    n, k = len(group), int(group["detected"].sum())
    lo, hi = metrics.wilson(k, n)
    det = group[group["detected"]]
    return pd.Series({
        "episodes": n,
        "detected": k,
        "detection_rate": k / n if n else np.nan,
        "ci_low": lo, "ci_high": hi,
        "median_latency_days": det["latency_days"].median() if len(det) else np.nan,
        "median_abs_onset_error_days": det["onset_error_days"].abs().median() if det["onset_error_days"].notna().any() else np.nan,
    })


def tables(runs: pd.DataFrame, fa: pd.DataFrame) -> dict[str, pd.DataFrame]:
    by_attack = runs.groupby(["detector", "attack", "relative_to"]).apply(_rate, include_groups=False).reset_index()
    by_variable = runs[runs["attack"] != "replay"].groupby(["detector", "variable", "attack", "relative_to"]).apply(
        _rate, include_groups=False).reset_index()
    fa_summary = fa.groupby("detector").agg(
        false_alarms_per_station_year=("false_alarms_per_year", "mean"),
        worst_site=("false_alarms_per_year", "max"),
        day_share=("false_alarm_day_share", "mean")).reset_index()
    return {"by_attack": by_attack, "by_variable": by_variable, "false_alarm_summary": fa_summary}


def _fmt(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False, floatfmt=".2f")


def summary_markdown(t: dict[str, pd.DataFrame], runs: pd.DataFrame, fa: pd.DataFrame, seconds: float) -> str:
    main = ["S", "M", "S or M"]
    a = t["by_attack"]
    head = a[a["detector"].isin(main)].copy()
    head["rate (95% CI)"] = head.apply(lambda r: f"{int(r.detected)}/{int(r.episodes)} = {r.detection_rate:.0%} ({r.ci_low:.0%}-{r.ci_high:.0%})", axis=1)
    head = head[["detector", "attack", "relative_to", "rate (95% CI)", "median_latency_days", "median_abs_onset_error_days"]]
    v = t["by_variable"]
    var = v[(v["detector"] == "S")].pivot_table(index=["variable"], columns=["attack", "relative_to"], values="detection_rate")
    parts = [
        "# Standard scenario results (file mode, development sites)\n",
        f"Sites: {', '.join(sorted(runs['site'].unique()))}. Episodes per detector: {runs['scenario'].nunique() * runs['site'].nunique()}. "
        f"Fit on the train years, scored on the validation year. Run time {seconds / 60:.1f} min.\n",
        "## False alarms on the clean validation year\n", _fmt(t["false_alarm_summary"]), "",
        "Per site:\n", _fmt(fa.pivot(index="detector", columns="site", values="false_alarms_per_year").reset_index()), "",
        "## Detection per attack (S = detector S combined flag, M = detector M)\n", _fmt(head), "",
        "## Detector S detection rate per variable\n", var.to_markdown(floatfmt=".2f"), "",
        "## Detector S parts\n", _fmt(a[a["detector"].str.startswith("S:")][["detector", "attack", "relative_to", "detected", "episodes", "detection_rate", "median_latency_days"]]),
    ]
    return "\n".join(parts) + "\n"


def run_standard(output_directory: str | Path | None = None, sites: list[str] | None = None,
                 limit: int | None = None, progress=print) -> dict[str, pd.DataFrame]:
    ecfg = load_eval_config()
    prep_cfg = pl.load_config()
    out = Path(output_directory or pl.REPO_ROOT / ecfg["output_directory"])
    out.mkdir(parents=True, exist_ok=True)
    scenario_list = scenarios(ecfg)[: limit] if limit else scenarios(ecfg)
    t0 = time.perf_counter()
    all_rows, all_fa = [], []
    for site in sites or pl.sites(prep_cfg):
        rows, fa_rows = run_site(site, scenario_list, ecfg, prep_cfg, progress=progress)
        all_rows += rows
        all_fa += fa_rows
    runs = pd.DataFrame(all_rows)
    fa = pd.DataFrame(all_fa)
    t = tables(runs, fa)
    runs.to_csv(out / "runs.csv", index=False)
    fa.to_csv(out / "false_alarms.csv", index=False)
    t["by_attack"].to_csv(out / "by_attack.csv", index=False)
    t["by_variable"].to_csv(out / "by_variable.csv", index=False)
    (out / "summary.md").write_text(summary_markdown(t, runs, fa, time.perf_counter() - t0), encoding="utf-8")
    progress(f"written to {out}")
    return {"runs": runs, "false_alarms": fa, **t}
