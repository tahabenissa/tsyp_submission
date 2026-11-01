"""Draw the figures of the README from the data and the saved results.

    python scripts/make_readme_figures.py

Reads results/eval/standard and results/eval/trust (run scripts/run_all.py and
scripts/run_trust.py first) and writes docs/images/*.png.
"""

from __future__ import annotations

import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from sensorguard import assess as A  # noqa: E402
from sensorguard import pipeline as pl  # noqa: E402

OUT = pl.REPO_ROOT / "docs" / "images"
# Reference palette, categorical slots 1-3 (validated colour-blind safe), text and surface tokens.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BAND = {"trusted": "#e6f4ec", "de-weighted": "#fdf1d6", "quarantined": "#fbe0de"}
ATTACK_SHADE = "#f3d6cf"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.titlecolor": INK, "axes.titlesize": 11, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "font.size": 9.5, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 1.6, "legend.frameon": False,
})


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("wrote", OUT / name)


# --------------------------------------------------------------------------- 1. the attacks


def fig_attacks(station):
    clean = station["temp_c"].loc["2024-03-01":"2024-07-31"]
    specs = [("12 % step bias (60 days)", pl.AttackSpec(attack="step", variables=("temp_c",), onset="2024-04-15", length_days=60)),
             ("Gradual drift up to 15 % (60-day ramp, held 30 days)", pl.AttackSpec(attack="drift", variables=("temp_c",), onset="2024-04-15", ramp_days=60, hold_days=30)),
             ("Seven-day replay (the week before is sent again)", pl.AttackSpec(attack="replay", onset="2024-05-20", length_days=7, source_offset_days=7))]
    fig, axes = plt.subplots(3, 1, figsize=(9, 7), sharex=True)
    for ax, (title, spec) in zip(axes, specs):
        a = pl.inject(station, spec)
        att = a.labels["attacked"].loc[clean.index]
        ax.axvspan(att[att].index.min(), att[att].index.max() + pd.Timedelta(days=1), color=ATTACK_SHADE, lw=0)
        ax.plot(clean.index, clean, color=INK2, lw=1.1, label="true reading")
        ax.plot(clean.index, a.series["temp_c"].loc[clean.index].where(att), color=ORANGE, lw=1.8, label="what the attacker sends")
        ax.set_title(title)
        ax.set_ylabel("°C")
    axes[0].legend(loc="upper left")
    fig.suptitle("The three official attacks, injected into a real station (FAWN, Florida, daily mean temperature, 2024)",
                 x=0.01, ha="left", fontsize=10, color=INK2)
    save(fig, "attacks.png")


# --------------------------------------------------------------------------- 2. why a witness


def fig_witness(station, power, lat, lon, cfg):
    spec = pl.AttackSpec(attack="step", variables=("temp_c",), onset="2024-04-15", relative_to="range", length_days=60)
    a = pl.inject(station, spec)
    r = A.assess(a.series, power, lat, lon, cfg["split"])
    win = slice("2024-02-01", "2024-08-31")
    att = a.labels["attacked"].loc[win]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 5.6), sharex=True)
    for ax in (ax1, ax2):
        ax.axvspan(att[att].index.min(), att[att].index.max() + pd.Timedelta(days=1), color=ATTACK_SHADE, lw=0)
    ax1.plot(r.reference_calibrated.loc[win].index, r.reference_calibrated.loc[win, "temp_c"], color=BLUE, lw=1.2, label="NASA POWER (calibrated to the station)")
    ax1.plot(a.series.loc[win].index, a.series.loc[win, "temp_c"], color=ORANGE, lw=1.2, label="station, attacked from 15 April")
    ax1.set_title("Real weather moves both together; the attack moves only the station")
    ax1.set_ylabel("°C"); ax1.legend(loc="lower right")
    res = r.residuals.loc[win, "temp_c"]
    ax2.plot(res.index, res, color=INK2, lw=0.7, alpha=0.7, label="daily residual")
    ax2.plot(res.index, res.rolling(14, min_periods=7).mean(), color=ORANGE, lw=2, label="14-day mean")
    ax2.axhspan(-1, 1, color=GRID, alpha=0.6, lw=0)
    ax2.set_title("Their disagreement (standardized residual): it wanders on clean days, jumps under attack")
    ax2.set_ylabel("σ"); ax2.legend(loc="upper left")
    save(fig, "witness.png")


# --------------------------------------------------------------------------- 3. the defence on one attack


def fig_defence(station, power, lat, lon, cfg):
    spec = pl.AttackSpec(attack="drift", variables=("solar_mj_m2",), onset="2024-05-01", relative_to="range", ramp_days=60, hold_days=30)
    a = pl.inject(station, spec)
    r = A.assess(a.series, power, lat, lon, cfg["split"])
    att = a.labels["attacked"].loc["2024"]
    s, e = att[att].index.min(), att[att].index.max() + pd.Timedelta(days=1)
    fig, axes = plt.subplots(4, 1, figsize=(9, 8.5), sharex=True)
    for ax in axes[:3]:
        ax.axvspan(s, e, color=ATTACK_SHADE, lw=0)
    res = r.residuals.loc["2024", "solar_mj_m2"]
    axes[0].plot(res.index, res.rolling(14, min_periods=7).mean(), color=ORANGE, lw=1.8)
    axes[0].set_title("1. Residual of solar radiation against NASA POWER (14-day mean, σ)")
    d = r.detectors
    axes[1].plot(d.index, d["cusum_score"], color=BLUE, lw=1.2)
    axes[1].axhline(r.thresholds["cusum"], color=INK2, ls="--", lw=1)
    alarms = d.index[d["cusum_flag"] == 1]
    axes[1].plot(alarms, d.loc[alarms, "cusum_score"], "o", ms=6, color=ORANGE, mec=SURFACE, mew=1.5)
    axes[1].text(d.index[5], r.thresholds["cusum"] * 1.03, "alarm threshold", color=INK2, fontsize=8.5, va="bottom")
    axes[1].set_title("2. CUSUM adds the offset up day after day; dots are alarms")
    axes[2].plot(r.probability.index, r.probability, color=AQUA, lw=1.2)
    axes[2].set_ylim(0, 1); axes[2].set_title("3. Compromise probability (all detectors fused)")
    for start, end, band in _band_runs(r.band):
        axes[3].axvspan(start, end, color=BAND[band], lw=0)
    axes[3].plot(r.trust.index, r.trust, color=INK, lw=1.8)
    for y, label, va in ((r.bands.deweight, "de-weight below", "bottom"), (r.bands.quarantine, "quarantine below", "top")):
        axes[3].axhline(y, color=INK2, ls="--", lw=0.9)
        axes[3].text(r.trust.index[-3], y + (0.01 if va == "bottom" else -0.01), label, color=INK2, fontsize=8.5, va=va, ha="right")
    # Label the responses to this attack only (first of each kind, from onset to 60 days after it), so the
    # labels do not collide; other responses still show as band colours.
    acts = r.actions[(r.actions["date"] >= s) & (r.actions["date"] <= e + pd.Timedelta(days=60))]
    offsets = {"verification request": (-40, -26), "quarantine": (0, -30), "release": (0, 16)}
    for kind, (dx, dy) in offsets.items():
        first = acts[acts["action"] == kind].head(1)
        for _, act in first.iterrows():
            axes[3].annotate(kind, (act["date"], act["trust"]), xytext=(dx, dy), textcoords="offset points",
                             ha="center", fontsize=8.5, color=INK, arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    axes[3].set_ylim(0, 1.05)
    axes[3].set_title("4. Trust score and band (green trusted, yellow de-weighted, red quarantined)")
    fig.suptitle("One attack followed through the defence: drift to +15 % on solar radiation, Kansas, from 1 May 2024 (shaded)",
                 x=0.01, ha="left", fontsize=10, color=INK2)
    save(fig, "defence.png")
    return r


def _band_runs(band):
    start, cur = band.index[0], band.iloc[0]
    for day, b in band.items():
        if b != cur:
            yield start, day, cur
            start, cur = day, b
    yield start, band.index[-1] + pd.Timedelta(days=1), cur


# --------------------------------------------------------------------------- 4. results


def fig_detection():
    t = pd.read_csv(pl.REPO_ROOT / "results/eval/standard/by_attack.csv").fillna({"relative_to": ""})
    groups = [("step", "value"), ("step", "range"), ("step", "std"), ("drift", "value"), ("drift", "range"), ("drift", "std"), ("replay", "")]
    labels = [f"step 12 %\nof {r}" if a == "step" else (f"drift 15 %\nof {r}" if a == "drift" else "7-day\nreplay") for a, r in groups]
    fig, ax = plt.subplots(figsize=(9, 3.8))
    x = np.arange(len(groups))
    for k, (det, colour, name) in enumerate((("S", BLUE, "detector S (statistical)"), ("M", ORANGE, "detector M (learned)"))):
        rows = [t[(t.detector == det) & (t.attack == a) & (t.relative_to == r)].iloc[0] for a, r in groups]
        rate = np.array([row.detection_rate for row in rows]) * 100
        lo = rate - np.array([row.ci_low for row in rows]) * 100
        hi = np.array([row.ci_high for row in rows]) * 100 - rate
        pos = x + (k - 0.5) * 0.38
        ax.bar(pos, rate, width=0.36, color=colour, label=name, edgecolor=SURFACE, linewidth=2)
        ax.errorbar(pos, rate, yerr=[lo, hi], fmt="none", ecolor=INK2, elinewidth=0.9, capsize=2)
        for px, v in zip(pos, rate):
            ax.text(px, 2, f"{v:.0f}", ha="center", va="bottom", fontsize=8, color=SURFACE, fontweight="bold")
    ax.set_xticks(x, labels); ax.set_ylim(0, 105); ax.set_ylabel("episodes detected (%)")
    ax.set_title("Detection of the official attacks, 3 sites, 2024 (bars: 95 % interval)")
    ax.legend(loc="upper left", ncol=2)
    ax.grid(axis="x", visible=False)
    save(fig, "detection.png")


def fig_size():
    r = pd.read_csv(pl.REPO_ROOT / "results/eval/standard/runs.csv")
    s = r[(r.detector == "S") & (r.attack == "step")]
    g = s.groupby(["variable", "relative_to"]).agg(size=("residual_shift_sd", lambda v: v.abs().median()), rate=("detected", "mean")).reset_index()
    names = {"temp_c": "temperature", "rh_pct": "humidity", "wind_ms": "wind", "solar_mj_m2": "solar"}
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.axvspan(0, 0.7, color=GRID, alpha=0.7, lw=0)
    ax.text(0.05, 103, "smaller than the natural\nstation-to-grid wandering", fontsize=8.5, color=INK2, va="top")
    ax.scatter(g["size"], g["rate"] * 100, s=60, color=BLUE, edgecolor=SURFACE, linewidth=1.5, zorder=3)
    nudge = {("solar_mj_m2", "range"): (-8, -11, "right"), ("temp_c", "range"): (-8, 4, "right"),
             ("temp_c", "std"): (-8, 6, "right"), ("rh_pct", "range"): (8, -3, "left"),
             ("wind_ms", "range"): (-8, -3, "right"), ("rh_pct", "std"): (7, 3, "left"),
             ("wind_ms", "std"): (7, -11, "left")}
    for _, row in g.iterrows():
        dx, dy, ha = nudge.get((row.variable, row.relative_to), (7, -3, "left"))
        ax.annotate(f"{names[row.variable]}, of {row.relative_to}", (row["size"], row.rate * 100), xytext=(dx, dy),
                    textcoords="offset points", fontsize=8, color=INK2, ha=ha)
    ax.set_xlabel("size of the 12 % step, in standard deviations of the station-minus-reference difference")
    ax.set_ylabel("steps detected by S (%)"); ax.set_ylim(0, 105); ax.set_xlim(0, 3.4)
    ax.set_title("What decides detection: the size of the attack against the natural disagreement")
    save(fig, "size.png")


def fig_reliability():
    t = pd.read_csv(pl.REPO_ROOT / "results/eval/trust/reliability.csv", index_col=0)
    fig, ax = plt.subplots(figsize=(4.8, 4.6))
    ax.plot([0, 1], [0, 1], color=INK2, ls="--", lw=1)
    ax.text(0.03, 0.95, "dashed line: perfectly calibrated", color=INK2, fontsize=8.5, va="top")
    ax.plot(t["mean_probability"], t["attacked_share"], "-o", color=BLUE, ms=6, mec=SURFACE, mew=1.5)
    ax.set_xlabel("probability given by the system"); ax.set_ylabel("share of those days really attacked")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_title("Calibration on sites the model never saw")
    save(fig, "calibration.png")


def fig_decisions():
    r = pd.read_csv(pl.REPO_ROOT / "results/eval/trust/runs.csv").fillna({"relative_to": ""})
    groups = [("replay", ""), ("step", "range"), ("step", "value"), ("drift", "range"), ("drift", "value"), ("step", "std"), ("drift", "std")]
    labels = ["replay" if a == "replay" else f"{a}, of {rel}" for a, rel in groups]
    c0 = [r[(r.attack == a) & (r.relative_to == rel)]["wrong_days_c0"].mean() * 100 for a, rel in groups]
    c4 = [r[(r.attack == a) & (r.relative_to == rel)]["wrong_days_c4"].mean() * 100 for a, rel in groups]
    fig, ax = plt.subplots(figsize=(9, 3.8))
    x = np.arange(len(groups))
    ax.bar(x - 0.19, c0, width=0.36, color=ORANGE, label="no defence", edgecolor=SURFACE, linewidth=2)
    ax.bar(x + 0.19, c4, width=0.36, color=BLUE, label="with the defence", edgecolor=SURFACE, linewidth=2)
    for px, v in zip(x - 0.19, c0):
        ax.text(px, v + 0.3, f"{v:.1f}", ha="center", fontsize=8, color=INK2)
    for px, v in zip(x + 0.19, c4):
        ax.text(px, v + 0.3, f"{v:.1f}", ha="center", fontsize=8, color=INK2)
    ax.set_xticks(x, labels); ax.set_ylabel("wrong-decision days (%)")
    ax.set_title("Days the farm decision is wrong because of the attack")
    ax.legend(loc="upper right"); ax.grid(axis="x", visible=False)
    save(fig, "decisions.png")


def main() -> int:
    warnings.filterwarnings("ignore")
    cfg = pl.load_config()
    fawn, fawn_power, (flat, flon) = pl.load_site("fawn", cfg)
    kansas, kansas_power, (klat, klon) = pl.load_site("kansas", cfg)
    fig_attacks(fawn)
    fig_witness(fawn, fawn_power, flat, flon, cfg)
    fig_defence(kansas, kansas_power, klat, klon, cfg)
    fig_detection()
    fig_size()
    fig_reliability()
    fig_decisions()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
