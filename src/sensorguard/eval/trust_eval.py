"""Step 4 evaluation: compromise probability, trust, responses and the with/without comparison.

Two passes.

Pass 1, per site (same scenario grid and same fits as eval/runner.py): score
the clean validation year and every attacked run with detector S and detector
M, and keep the daily fusion features (detect/fusion.py) with the labels.

Pass 2, leave one site out.  For each site H:

1. fit the fusion (logistic regression) on the runs of the OTHER sites;
2. compute the trust on the clean runs of the other sites and set the band
   limits from it (detect/trust_score.py), then freeze them;
3. at H, for the clean run and for every attacked run: probability -> trust ->
   band -> weight -> the series used downstream (response/policy.py) -> the
   water balance and decision level (product/water_balance.py);
4. compare three decision series over the attack and the 30 days after it:
       truth  from the clean station series
       C0     from the attacked series, no defence
       C4     from the attacked series after de-weighting and quarantine

Nothing measured at H was used to fit anything applied at H.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from sensorguard import pipeline as pl
from sensorguard.detect import fusion, statistical, trust_score
from sensorguard.detect.trust_score import DEWEIGHTED, QUARANTINED, TRUSTED
from sensorguard.eval import metrics
from sensorguard.eval.runner import load_eval_config, scenarios
from sensorguard.processing.residuals.reference import apply_reference_residuals
from sensorguard.product import water_balance as wb
from sensorguard.response import policy

TRUST_CONFIG = pl.REPO_ROOT / "config" / "trust.yaml"


def load_trust_config(path: str | Path = TRUST_CONFIG) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


# --------------------------------------------------------------------------- pass 1


def _m_flags(series, power, site, index):
    from sensorguard.detect import learned
    return learned.predict_detector_m(series, power, site)["is_anomaly"].reindex(index).fillna(0).astype(int)


def collect_site(site: str, scenario_list, ecfg, prep_cfg, tcfg, progress=print) -> dict[str, Any]:
    split = prep_cfg["split"]
    station, power, (lat, _lon) = pl.load_site(site, prep_cfg)
    prep = pl.prepare(station, power, prep_cfg)
    model = statistical.fit(prep.reference, station, split)
    days = int(tcfg["fusion"]["persistence_days"])
    with_m = bool(ecfg.get("include_detector_m", True))

    def score(series, reference):
        res = statistical.score(model, reference, series)
        m = _m_flags(series, power, site, res.daily.index) if with_m else None
        return res, fusion.features(res.daily, res.params, m, days, reference)

    vs = split["validation_start"]
    keep_from = pd.Timestamp(vs) - pd.Timedelta(days=60)   # residual history for the implicated-variable window
    clean_res, clean_x = score(station, prep.reference)
    runs = []
    t0 = time.perf_counter()
    for k, sc in enumerate(scenario_list, 1):
        attack = pl.inject(station, sc.spec(ecfg))
        reference = apply_reference_residuals(attack.series, power, prep.calibration, prep_cfg)
        res, x = score(attack.series, reference)
        ep = attack.episodes[0]
        runs.append({"scenario": sc, "x": x, "y": attack.labels["attacked"].reindex(x.index).astype(bool),
                     "episodes": res.episodes, "onset": ep.onset, "end": ep.end,
                     "reference": reference.loc[keep_from:], "replay": res.daily["replay_flag"]})
        if k % 50 == 0 or k == len(scenario_list):
            progress(f"[{site}] pass 1: {k}/{len(scenario_list)} runs, {time.perf_counter() - t0:.0f} s")
    return {"site": site, "station": station, "power": power, "lat": lat, "prep": prep,
            "clean_x": clean_x, "clean_episodes": clean_res.episodes, "runs": runs,
            "clean_reference": prep.reference.loc[keep_from:], "clean_replay": clean_res.daily["replay_flag"]}


# --------------------------------------------------------------------------- pass 2


def _stack(sites: list[dict]) -> tuple[pd.DataFrame, pd.Series]:
    xs, ys = [], []
    for s in sites:
        xs.append(s["clean_x"]); ys.append(pd.Series(False, index=s["clean_x"].index))
        for r in s["runs"]:
            xs.append(r["x"]); ys.append(r["y"])
    return pd.concat(xs, ignore_index=True), pd.concat(ys, ignore_index=True)


def _decisions(series: pd.DataFrame, lat: float, levels: pd.DataFrame, tcfg) -> pd.Series:
    p = tcfg["product"]
    return wb.decision_levels(wb.water_balance(series, lat, p["window_days"], p["elevation_m"]), levels)


def _worse(band: pd.Series, clean_band: pd.Series, levels: tuple[str, ...]) -> pd.Series:
    """Days where the attacked run is in one of ``levels`` while the clean run is not."""
    return band.isin(levels) & ~clean_band.reindex(band.index).isin(levels)


def evaluate_site(h: dict, others: list[dict], tcfg, prep_cfg) -> dict[str, Any]:
    fc, tc, pc = tcfg["fusion"], tcfg["trust"], tcfg["product"]
    x_fit, y_fit = _stack(others)
    fm = fusion.fit(x_fit, y_fit, c=float(fc["regularization_c"]))
    clean_trust_fit = pd.concat([trust_score.trust_series(fm.probability(o["clean_x"]), tc["fall_rate"], tc["recovery_rate"])
                                 for o in others])
    bands = trust_score.fit_bands(clean_trust_fit, tc["deweight_clean_share"], tc["quarantine_clean_share"])

    split = prep_cfg["split"]
    station, power, lat, prep = h["station"], h["power"], h["lat"], h["prep"]
    levels = wb.fit_levels(wb.water_balance(station, lat, pc["window_days"], pc["elevation_m"]).loc[split["train_start"]:split["train_end"]],
                           pc["dry_quantile"], pc["severe_quantile"])
    ref_cal = policy.calibrated_reference(power, prep.calibration, prep_cfg)
    truth = _decisions(station, lat, levels, tcfg)
    ecfg = load_eval_config()

    rc = tcfg["response"]

    def chain(series: pd.DataFrame, x: pd.DataFrame, episodes, reference, replay):
        p = fm.probability(x)
        trust = trust_score.trust_series(p, tc["fall_rate"], tc["recovery_rate"])
        band = trust_score.band_series(trust, bands)
        w = policy.weights(trust, band, bands)
        imp = policy.implicated(reference, replay.astype(bool), rc["implicated_days"], rc["implicated_sd"])
        used = policy.apply(series, ref_cal, w, imp)
        acts = policy.actions(trust, band, fm.contributions(x), episodes, tcfg["response"]["verification_every_days"])
        return p, trust, band, w, used, acts

    # clean run: the cost of the defence on an honest station
    cp, ctrust, cband, _cw, cused, cacts = chain(station, h["clean_x"], h["clean_episodes"],
                                                 h["clean_reference"], h["clean_replay"])
    vstart, vend = split["validation_start"], split["validation_end"]
    years = len(cband) / 365.25
    c4_clean = _decisions(cused, lat, levels, tcfg).loc[vstart:vend]
    t = truth.loc[vstart:vend]
    valid = t.notna() & c4_clean.notna()
    clean_row = {
        "site": h["site"], **bands.as_dict(),
        "deweighted_day_share": float((cband == DEWEIGHTED).mean()),
        "quarantined_days_per_year": float((cband == QUARANTINED).sum() / years),
        "quarantines_per_year": float((cacts["action"] == "quarantine").sum() / years),
        "verification_requests_per_year": float((cacts["action"] == "verification request").sum() / years),
        "decision_days_changed_by_defence": float((c4_clean[valid] != t[valid]).mean()),
    }

    rows, probs = [], [pd.DataFrame({"p": cp.to_numpy(), "y": 0, "site": h["site"]})]
    example = None
    for r in h["runs"]:
        sc = r["scenario"]
        attack = pl.inject(station, sc.spec(ecfg))
        p, trust, band, w, used, acts = chain(attack.series, r["x"], r["episodes"], r["reference"], r["replay"])
        probs.append(pd.DataFrame({"p": p.to_numpy(), "y": r["y"].astype(int).to_numpy(), "site": h["site"]}))
        onset, end = r["onset"], r["end"]
        judge_end = end + pd.Timedelta(days=int(pc["judge_after_days"]))
        win = slice(onset, min(judge_end, pd.Timestamp(vend)))
        dw = _worse(band, cband, (DEWEIGHTED, QUARANTINED)).loc[onset:end]
        qu = _worse(band, cband, (QUARANTINED,)).loc[onset:end]
        c0 = _decisions(attack.series, lat, levels, tcfg).loc[win]
        c4 = _decisions(used, lat, levels, tcfg).loc[win]
        tw = truth.loc[win]
        ok = tw.notna() & c0.notna() & c4.notna()
        wrong0 = (c0[ok] != tw[ok]); wrong4 = (c4[ok] != tw[ok])
        # Product confidence: TRUSTED only if the station was trusted on every
        # day of the window behind the decision; otherwise DEGRADED (pending
        # verification).  A wrong decision issued as TRUSTED is the attacker's win.
        trusted_window = (band == TRUSTED).astype(float).rolling(int(pc["window_days"]), min_periods=1).min().astype(bool)
        silent4 = wrong4 & trusted_window.reindex(wrong4.index).fillna(True)
        rows.append({
            "site": h["site"], "scenario": sc.name, "attack": sc.attack, "variable": sc.variable,
            "relative_to": sc.relative_to, "sign": sc.sign,
            "max_probability_in_attack": float(p.loc[onset:end].max()),
            "min_trust_in_attack": float(trust.loc[onset:end].min()),
            "deweighted": bool(dw.any()),
            "days_to_deweight": float((dw[dw].index.min() - onset).days) if dw.any() else np.nan,
            "quarantined": bool(qu.any()),
            "days_to_quarantine": float((qu[qu].index.min() - onset).days) if qu.any() else np.nan,
            "mean_weight_in_attack": float(w.loc[onset:end].mean()),
            "wrong_decision_c0": bool(wrong0.any()), "wrong_decision_c4": bool(wrong4.any()),
            "wrong_trusted_c4": bool(silent4.any()),
            "wrong_trusted_days_c4": float(silent4.mean()) if ok.any() else np.nan,
            "wrong_days_c0": float(wrong0.mean()) if ok.any() else np.nan,
            "wrong_days_c4": float(wrong4.mean()) if ok.any() else np.nan,
        })
        if example is None and sc.attack == "step" and sc.variable == "temp_c" and sc.sign > 0 \
                and sc.relative_to == "value" and sc.onset.endswith("04-15"):
            example = {"site": h["site"], "scenario": sc.name, "actions": acts,
                       "daily": pd.DataFrame({"probability": p, "trust": trust, "band": band, "weight": w,
                                              "decision_truth": truth.reindex(p.index),
                                              "decision_c0": _decisions(attack.series, lat, levels, tcfg).reindex(p.index),
                                              "decision_c4": _decisions(used, lat, levels, tcfg).reindex(p.index)})}
    return {"rows": rows, "clean": clean_row, "probs": pd.concat(probs, ignore_index=True),
            "coefficients": {"site": h["site"], **fm.coefficients()}, "example": example}


# --------------------------------------------------------------------------- tables


def _share(s: pd.Series) -> str:
    k, n = int(s.sum()), int(s.size)
    lo, hi = metrics.wilson(k, n)
    return f"{k}/{n} = {k / n:.0%} ({lo:.0%}-{hi:.0%})"


def tables(runs: pd.DataFrame) -> dict[str, pd.DataFrame]:
    keys = ["attack", "relative_to"]
    g = runs.groupby(keys)
    response = pd.DataFrame({
        "episodes": g.size(),
        "de-weighted": g["deweighted"].apply(_share),
        "median days to de-weight": g["days_to_deweight"].median(),
        "quarantined": g["quarantined"].apply(_share),
        "median days to quarantine": g["days_to_quarantine"].median(),
        "mean weight during attack": g["mean_weight_in_attack"].mean(),
    }).reset_index()
    decision = pd.DataFrame({
        "episodes": g.size(),
        "C0 wrong decision (no defence)": g["wrong_decision_c0"].apply(_share),
        "C4 wrong decision (full system)": g["wrong_decision_c4"].apply(_share),
        "C4 wrong AND issued as TRUSTED": g["wrong_trusted_c4"].apply(_share),
        "C0 wrong days": g["wrong_days_c0"].mean(),
        "C4 wrong days": g["wrong_days_c4"].mean(),
        "C4 wrong TRUSTED days": g["wrong_trusted_days_c4"].mean(),
    }).reset_index()
    harmful = runs[runs["wrong_decision_c0"]]
    hg = harmful.groupby(keys)
    prevented = pd.DataFrame({
        "attacks that changed the decision without defence": hg.size(),
        "still wrong with the full system": hg["wrong_decision_c4"].apply(_share),
        "wrong AND issued as TRUSTED": hg["wrong_trusted_c4"].apply(_share),
    }).reset_index()
    by_variable = runs[runs["attack"] != "replay"].groupby(["variable", "attack"]).agg(
        episodes=("deweighted", "size"), deweighted=("deweighted", "mean"), quarantined=("quarantined", "mean"),
        wrong_c0=("wrong_decision_c0", "mean"), wrong_c4=("wrong_decision_c4", "mean"),
        wrong_trusted_c4=("wrong_trusted_c4", "mean")).reset_index()
    return {"response": response, "decision": decision, "prevented": prevented, "by_variable": by_variable}


def run(output_directory: str | Path | None = None, sites: list[str] | None = None, limit: int | None = None,
        progress=print) -> dict[str, Any]:
    tcfg = load_trust_config()
    ecfg = load_eval_config()
    prep_cfg = pl.load_config()
    out = Path(output_directory or pl.REPO_ROOT / tcfg["output_directory"])
    out.mkdir(parents=True, exist_ok=True)
    grid = scenarios(ecfg)[:limit] if limit else scenarios(ecfg)
    t0 = time.perf_counter()
    collected = [collect_site(s, grid, ecfg, prep_cfg, tcfg, progress) for s in (sites or pl.sites(prep_cfg))]
    results = []
    for i, h in enumerate(collected):
        progress(f"[{h['site']}] pass 2: fit on {[o['site'] for o in collected if o is not h]}, evaluate here")
        results.append(evaluate_site(h, [o for j, o in enumerate(collected) if j != i], tcfg, prep_cfg))
    runs = pd.DataFrame([row for r in results for row in r["rows"]])
    clean = pd.DataFrame([r["clean"] for r in results])
    coefs = pd.DataFrame([r["coefficients"] for r in results])
    probs = pd.concat([r["probs"] for r in results], ignore_index=True)
    rel = fusion.reliability(probs["p"], probs["y"], int(tcfg["fusion"]["reliability_bins"]))
    prob_scores = pd.DataFrame([{"site": s, **fusion.scores(g["p"], g["y"])} for s, g in probs.groupby("site")]
                               + [{"site": "all", **fusion.scores(probs["p"], probs["y"])}])
    t = tables(runs)
    runs.to_csv(out / "runs.csv", index=False)
    clean.to_csv(out / "clean.csv", index=False)
    coefs.to_csv(out / "fusion_coefficients.csv", index=False)
    rel.to_csv(out / "reliability.csv")
    prob_scores.to_csv(out / "probability_scores.csv", index=False)
    for name, frame in t.items():
        frame.to_csv(out / f"{name}.csv", index=False)
    ex = next((r["example"] for r in results if r["example"] is not None), None)
    if ex is not None:
        ex["daily"].to_csv(out / f"example_{ex['site']}_{ex['scenario']}.csv")
        ex["actions"].to_csv(out / f"example_{ex['site']}_{ex['scenario']}_actions.csv", index=False)
    md = [
        "# Trust score, responses and decisions (leave one site out)\n",
        f"Runs: {len(runs)} attacked + {len(clean)} clean site-years. Run time {(time.perf_counter() - t0) / 60:.1f} min.\n",
        "## Compromise probability on the held-out site\n", prob_scores.to_markdown(index=False, floatfmt=".3f"), "",
        "Reliability (all held-out days):\n", rel.to_markdown(floatfmt=".3f"), "",
        "## Cost on honest stations (clean 2024)\n", clean.to_markdown(index=False, floatfmt=".3f"), "",
        "## Responses during the attack\n", t["response"].to_markdown(index=False, floatfmt=".2f"), "",
        "## Decisions: without (C0) and with (C4) the defence\n", t["decision"].to_markdown(index=False, floatfmt=".2f"), "",
        "Of the attacks that changed the decision without defence:\n", t["prevented"].to_markdown(index=False), "",
        "## Per variable\n", t["by_variable"].to_markdown(index=False, floatfmt=".2f"), "",
        "## Fusion coefficients (one model per held-out site)\n", coefs.to_markdown(index=False, floatfmt=".2f"), "",
    ]
    if ex is not None:
        md += [f"## Example actions: {ex['site']} {ex['scenario']}\n", ex["actions"].to_markdown(index=False, floatfmt=".2f")]
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    progress(f"written to {out}")
    return {"runs": runs, "clean": clean, "reliability": rel, "probability_scores": prob_scores, **t}
