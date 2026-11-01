"""Every measurement the Phase 1 report needs beyond run_all.py and run_trust.py.

    python scripts/report_metrics.py            (about 15 minutes)

Writes results/eval/report/:
    layer1.csv            the same attacks at P1, P2, P3: what layer 1 rejects, ledger state
    overhead.csv          bytes per record, sign / verify / ledger time, defence CPU time per reading,
                          peak memory, model sizes
    roc.csv, roc_curves.csv, ablation.csv
                          per-day ROC / PR of the compromise probability, leave one site out,
                          for the full fusion and with feature groups removed
    extreme_weather.csv   false alarms on genuine extreme-weather days against ordinary days
    stealth.csv           step size sweep: detection against size (stealth budget, E9-style)
    slow_drift.csv        drift ramp-length sweep (evasion E1)
    perturbed_replay.csv  replay with added noise (evasion E5)
    hardware.json         machine and software versions
"""

from __future__ import annotations

import json
import pickle
import platform
import sys
import time
import timeit
import tracemalloc
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score, roc_curve

from sensorguard import assess as A
from sensorguard import pipeline as pl
from sensorguard.detect import fusion, statistical
from sensorguard.eval import metrics
from sensorguard.eval.runner import load_eval_config, scenarios
from sensorguard.eval.trust_eval import collect_site, load_trust_config
from sensorguard.processing.detector_s.cusum import CusumDetector
from sensorguard.processing.detector_s.mahalanobis import MahalanobisDetector
from sensorguard.processing.detector_s.replay import ReplayDetector
from sensorguard.processing.residuals.reference import apply_reference_residuals

OUT = pl.REPO_ROOT / "results" / "eval" / "report"
FAST = (CusumDetector, ReplayDetector, MahalanobisDetector)   # the combined flag of detector S
RNG = np.random.default_rng(42)


def log(msg):
    print(msg, flush=True)


# --------------------------------------------------------------------------- layer 1


def layer1(cfg):
    rows = []
    for attack, spec in (("step 12 % temp", dict(attack="step", variables=("temp_c",), onset="2024-04-15", length_days=60)),
                         ("replay 7 days", dict(attack="replay", onset="2024-04-15", length_days=7, source_offset_days=7))):
        for pos in ("P1", "P2", "P3"):
            r = pl.run("fawn", pl.AttackSpec(**spec, position=pos), cfg)
            att = r.labels["attacked"]
            rows.append({"attack": attack, "position": pos, "attacked_days": int(att.sum()),
                         "rejected_by_layer1": int((r.trust.log.loc[att, "decision"] == "reject").sum()),
                         "reasons": ", ".join(sorted(set(r.trust.log.loc[att & (r.trust.log["decision"] == "reject"), "reason"]))),
                         "ledger_intact": r.trust.ledger_ok,
                         "ledger_first_broken": None if r.trust.ledger_first_broken is None else str(r.trust.ledger_first_broken.date()),
                         "attacked_values_reaching_detection": int(r.trust.received.loc[att].notna().any(axis=1).sum())})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- overhead


def overhead(cfg):
    from sensorguard.trust import record as rec
    from sensorguard.trust import verify as vfy
    from sensorguard.trust.enrolment import Registry, issue_certificate
    from sensorguard.trust.keys import FileSecureElement, generate_root, sign_record
    from sensorguard.trust.ledger import Ledger

    root = generate_root(); reg = Registry(root.public_key()); key = FileSecureElement.generate()
    reg.enrol(issue_certificate(root, sensor_id=1, public_key=key.public_key(), position=(28.7, -81.9),
                                valid_from=0, valid_to=2_000_000_000))
    payload = pl.pack([21.3, 64.0, 2.1, 0.0, 18.4])
    r0 = sign_record(key, rec.Record(sensor_id=1, key_id=0, seq=0, t_obs=1_700_000_000, prev_hash=rec.ZERO_HASH, payload=payload))
    raw = r0.encode()
    n = 2000
    sign_us = timeit.timeit(lambda: sign_record(key, rec.Record(sensor_id=1, key_id=0, seq=0, t_obs=1_700_000_000,
                                                                prev_hash=rec.ZERO_HASH, payload=payload)), number=n) / n * 1e6

    def verify_many():
        v = vfy.Verifier(reg)
        prev = rec.ZERO_HASH
        recs = []
        for i in range(n):
            r = sign_record(key, rec.Record(sensor_id=1, key_id=0, seq=i, t_obs=1_700_000_000 + i * 86400, prev_hash=prev, payload=payload))
            prev = r.digest(); recs.append(r.encode())
        t = time.perf_counter()
        for i, b in enumerate(recs):
            v.verify(b, arrival_time=1_700_000_000 + i * 86400 + 3600)
        return (time.perf_counter() - t) / n * 1e6, recs
    verify_us, recs = verify_many()
    led = Ledger()
    t = time.perf_counter()
    for b in recs:
        led.append(b)
    ledger_us = (time.perf_counter() - t) / n * 1e6

    station, power, (lat, lon) = pl.load_site("kansas", cfg)
    tracemalloc.start()
    t = time.perf_counter()
    res = A.assess(station, power, lat, lon, cfg["split"], site="kansas")
    total_s = time.perf_counter() - t
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    state = {"calibration": None, "detector S": None}
    model = statistical.fit(res.residuals, station, cfg["split"])
    state_bytes = len(pickle.dumps([(d.name, {k: v for k, v in p.items() if k not in ("history", "train_history")}) for d, p in model.fitted]))
    history_bytes = len(pickle.dumps([p.get("history") for _d, p in model.fitted]))
    m_dir = pl.REPO_ROOT / "results" / "models_detector_m"
    m_size = sum(f.stat().st_size for f in m_dir.glob("*.pkl"))
    rows = [
        ("record size, fixed part (header + signature)", len(raw) - len(payload), "bytes"),
        ("record payload, 5 variables", len(payload), "bytes"),
        ("record size, total", len(raw), "bytes"),
        ("overhead relative to the payload", round((len(raw) - len(payload)) / len(payload), 2), "x"),
        ("sign one record (station side)", round(sign_us, 1), "µs"),
        ("verify one record (signature, certificate, sequence, chain)", round(verify_us, 1), "µs"),
        ("append one record to the hash-chained ledger", round(ledger_us, 1), "µs"),
        ("whole defence on one station, 4 years of daily data", round(total_s, 2), "s"),
        ("whole defence per daily reading", round(total_s / len(station) * 1000, 2), "ms"),
        ("peak Python memory of that run", round(peak / 2**20, 1), "MiB"),
        ("detector S fitted state per station (thresholds, AR, covariance)", state_bytes, "bytes"),
        ("replay-matcher history per station (730 days x 4 variables)", history_bytes, "bytes"),
        ("detector M saved model (3 sites)", round(m_size / 2**20, 2), "MiB"),
        ("fusion model and trust bands", A.FUSION_FILE.stat().st_size, "bytes"),
    ]
    return pd.DataFrame(rows, columns=["quantity", "value", "unit"])


# --------------------------------------------------------------------------- ROC, PR, ablation


VARIANTS = {
    "full fusion (S + M)": fusion.FEATURES,
    "S only": [f for f in fusion.FEATURES if not f.startswith("m_")],
    "M only": ["m_flag", "m_recent"],
    "CUSUM only": ["cusum_ratio", "cusum_recent"],
    "without CUSUM": [f for f in fusion.FEATURES if not f.startswith("cusum")],
    "without Mahalanobis": [f for f in fusion.FEATURES if f != "maha_log"],
    "without replay matcher": [f for f in fusion.FEATURES if f != "replay_log"],
    "without trend": [f for f in fusion.FEATURES if f != "trend_ratio"],
    "without rolling gaps": [f for f in fusion.FEATURES if not f.startswith("gap")],
}


def roc_ablation(collected):
    frames = []
    for c in collected:
        frames.append(c["clean_x"].assign(y=0, site=c["site"], attack="none", rel=""))
        for r in c["runs"]:
            sc = r["scenario"]
            frames.append(r["x"].assign(y=r["y"].astype(int).to_numpy(), site=c["site"], attack=sc.attack, rel=sc.relative_to))
    data = pd.concat(frames, ignore_index=True)
    rows, curves = [], []
    for name, feats in VARIANTS.items():
        p = pd.Series(np.nan, index=data.index)
        for site in data["site"].unique():
            fit_mask = data["site"] != site
            model = fusion.fit(data.loc[fit_mask], data.loc[fit_mask, "y"], feature_names=list(feats))
            p.loc[~fit_mask] = model.probability(data.loc[~fit_mask]).to_numpy()
        y = data["y"].to_numpy()
        fpr, tpr, _ = roc_curve(y, p)
        row = {"variant": name, "roc_auc": roc_auc_score(y, p), "pr_auc": average_precision_score(y, p),
               "tpr_at_1pct_fpr": float(np.interp(0.01, fpr, tpr)), "tpr_at_0.1pct_fpr": float(np.interp(0.001, fpr, tpr))}
        for attack in ("step", "drift", "replay"):
            m = (data["attack"] == attack) | (data["attack"] == "none") | (data["y"] == 0)
            m &= (data["attack"] == attack) | (data["y"] == 0)
            row[f"roc_auc_{attack}"] = roc_auc_score(y[m], p[m])
        rows.append(row)
        if name in ("full fusion (S + M)", "S only", "M only", "CUSUM only"):
            idx = np.unique(np.linspace(0, len(fpr) - 1, 400).astype(int))
            curves.append(pd.DataFrame({"variant": name, "fpr": fpr[idx], "tpr": tpr[idx]}))
        log(f"  {name}: AUC {row['roc_auc']:.3f}")
    return pd.DataFrame(rows), pd.concat(curves, ignore_index=True)


# --------------------------------------------------------------------------- extreme weather


def extreme_weather(cfg):
    rows = []
    for site in pl.sites(cfg):
        station, power, (lat, lon) = pl.load_site(site, cfg)
        res = A.assess(station, power, lat, lon, cfg["split"], site=site)
        train = station.loc[cfg["split"]["train_start"]:cfg["split"]["train_end"]]
        test = station.loc[res.detectors.index]
        clim = train.groupby(train.index.month)["temp_c"].agg(["mean", "std"])
        z = (test["temp_c"] - clim["mean"].reindex(test.index.month).to_numpy()) / clim["std"].reindex(test.index.month).to_numpy()
        wet = train["precip_mm"][train["precip_mm"] > 0.1]
        extreme = (z.abs() > 1.645) | (test["precip_mm"] > wet.quantile(0.95))
        d = res.detectors
        flags = {"detector S (combined)": d["flag"], "CUSUM": d["cusum_flag"], "Mahalanobis": d["mahalanobis_flag"],
                 "station not trusted (de-weighted or quarantined)": (res.band != "trusted").astype(int),
                 "station quarantined": (res.band == "quarantined").astype(int)}
        for name, f in flags.items():
            f = f.reindex(extreme.index).fillna(0).astype(bool)
            rows.append({"site": site, "indicator": name, "extreme_days": int(extreme.sum()), "ordinary_days": int((~extreme).sum()),
                         "flagged_share_extreme": float(f[extreme].mean()), "flagged_share_ordinary": float(f[~extreme].mean())})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- evasion sweeps


def _site_models(cfg):
    out = {}
    for site in pl.sites(cfg):
        station, power, coords = pl.load_site(site, cfg)
        prep = pl.prepare(station, power, cfg)
        model = statistical.fit(prep.reference, station, cfg["split"], detectors=FAST)
        clean = statistical.score(model, prep.reference, station)
        out[site] = (station, power, prep, model, clean)
    return out


def _detect(site_models, site, cfg, series, onset, end):
    station, power, prep, model, clean = site_models[site]
    ref = apply_reference_residuals(series, power, prep.calibration, cfg)
    res = statistical.score(model, ref, series)
    out = {}
    for name, col in (("S", "flag"), ("replay matcher", "replay_flag"), ("CUSUM", "cusum_flag")):
        o = metrics.episode_outcome(res.daily[col], clean.daily[col], onset, end)
        out[f"{name} detected"] = o["detected"]
        out[f"{name} latency"] = o["latency_days"]
    return out


def stealth(site_models, cfg):
    rows = []
    for site in site_models:
        station = site_models[site][0]
        for var in ("temp_c", "rh_pct", "wind_ms", "solar_mj_m2"):
            for rel in ("value", "range"):
                for mag in (0.02, 0.05, 0.08, 0.12, 0.16, 0.20, 0.30):
                    for onset in ("2024-04-15", "2024-09-01"):
                        a = pl.inject(station, pl.AttackSpec(attack="step", variables=(var,), onset=onset, magnitude=mag,
                                                             relative_to=rel, length_days=60))
                        ep = a.episodes[0]
                        rows.append({"site": site, "variable": var, "relative_to": rel, "magnitude": mag, "onset": onset,
                                     **_detect(site_models, site, cfg, a.series, ep.onset, ep.end)})
    return pd.DataFrame(rows)


def slow_drift(site_models, cfg):
    rows = []
    for site in site_models:
        station = site_models[site][0]
        for var in ("temp_c", "solar_mj_m2", "rh_pct", "wind_ms"):
            for ramp in (30, 60, 90, 180, 270):
                a = pl.inject(station, pl.AttackSpec(attack="drift", variables=(var,), onset="2024-01-15", magnitude=0.15,
                                                     relative_to="range", ramp_days=ramp, hold_days=0))
                ep = a.episodes[0]
                rows.append({"site": site, "variable": var, "ramp_days": ramp, **_detect(site_models, site, cfg, a.series, ep.onset, ep.end)})
    return pd.DataFrame(rows)


def perturbed_replay(site_models, cfg):
    rows = []
    for site in site_models:
        station = site_models[site][0]
        sd = station.loc[cfg["split"]["train_start"]:cfg["split"]["train_end"]].std()
        for noise in (0.0, 0.01, 0.03, 0.05, 0.1, 0.2, 0.4):
            for onset in ("2024-01-15", "2024-04-15", "2024-07-15", "2024-10-15"):
                a = pl.inject(station, pl.AttackSpec(attack="replay", onset=onset, length_days=7, source_offset_days=28))
                s = a.series.copy()
                att = a.labels["attacked"].to_numpy()
                for v in ("temp_c", "rh_pct", "wind_ms", "solar_mj_m2"):
                    s.loc[att, v] = s.loc[att, v] + RNG.normal(0, noise * sd[v], att.sum())
                ep = a.episodes[0]
                rows.append({"site": site, "noise_sd": noise, "onset": onset, **_detect(site_models, site, cfg, s, ep.onset, ep.end)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- main


def hardware():
    import subprocess
    info = {"python": sys.version.split()[0], "os": f"{platform.system()} {platform.release()} ({platform.version()})",
            "machine": platform.machine()}
    try:
        cpu = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_Processor).Name; [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,1)"],
                             capture_output=True, text=True, timeout=60).stdout.split("\n")
        info["cpu"], info["ram_gb"] = cpu[0].strip(), cpu[1].strip()
    except Exception:
        info["cpu"] = platform.processor()
    import matplotlib, numpy, pandas, scipy, sklearn
    info["packages"] = {m.__name__: m.__version__ for m in (numpy, pandas, scipy, sklearn, matplotlib)}
    return info


def main() -> int:
    warnings.filterwarnings("ignore")
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = pl.load_config()
    t0 = time.perf_counter()
    (OUT / "hardware.json").write_text(json.dumps(hardware(), indent=2), encoding="utf-8")
    log("layer 1 at P1, P2, P3"); layer1(cfg).to_csv(OUT / "layer1.csv", index=False)
    log("overhead"); overhead(cfg).to_csv(OUT / "overhead.csv", index=False)
    log("extreme weather"); extreme_weather(cfg).to_csv(OUT / "extreme_weather.csv", index=False)
    log("evasion sweeps"); sm = _site_models(cfg)
    stealth(sm, cfg).to_csv(OUT / "stealth.csv", index=False); log("  stealth done")
    slow_drift(sm, cfg).to_csv(OUT / "slow_drift.csv", index=False); log("  slow drift done")
    perturbed_replay(sm, cfg).to_csv(OUT / "perturbed_replay.csv", index=False); log("  perturbed replay done")
    log("ROC and ablation (collecting 756 runs, about 10 min)")
    tcfg, ecfg = load_trust_config(), load_eval_config()
    grid = scenarios(ecfg)
    collected = [collect_site(s, grid, ecfg, cfg, tcfg, log) for s in pl.sites(cfg)]
    roc, curves = roc_ablation(collected)
    roc.to_csv(OUT / "roc.csv", index=False); curves.to_csv(OUT / "roc_curves.csv", index=False)
    log(f"done in {(time.perf_counter() - t0) / 60:.1f} min -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
