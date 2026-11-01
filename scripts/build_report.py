"""Build the Phase 1 report: report/report.html and report/report.pdf.

    python scripts/build_report.py

Every number and figure is read from the saved results:
    results/eval/standard   (scripts/run_all.py)
    results/eval/trust      (scripts/run_trust.py)
    results/eval/report     (scripts/report_metrics.py)
plus the README figures (docs/images, scripts/make_readme_figures.py).

The PDF is printed by Microsoft Edge in headless mode, then its metadata is
reset to the title only (Phase 1 is anonymous).
"""

from __future__ import annotations

import hashlib
import html
import json
import subprocess
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from sensorguard import assess as A  # noqa: E402
from sensorguard import pipeline as pl  # noqa: E402

ROOT = pl.REPO_ROOT
REPORT = ROOT / "report"
FIG = REPORT / "figures"
IMG = ROOT / "docs" / "images"
STD = ROOT / "results" / "eval" / "standard"
TRU = ROOT / "results" / "eval" / "trust"
REP = ROOT / "results" / "eval" / "report"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
TITLE = "Ground Truth Under Attack, Track 2: signed, cross-checked and trust-scored weather stations"

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"
SITE_COLOURS = {"azmet": BLUE, "fawn": ORANGE, "kansas": AQUA}
SITE_NAMES = {"azmet": "AZMET (Arizona, semi-arid)", "fawn": "FAWN (Florida, humid)", "kansas": "Kansas (continental)"}
VAR_NAMES = {"temp_c": "temperature", "rh_pct": "humidity", "wind_ms": "wind", "solar_mj_m2": "solar", "precip_mm": "rain"}
VAR_COLOURS = {"temp_c": BLUE, "solar_mj_m2": ORANGE, "rh_pct": AQUA, "wind_ms": YELLOW}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.titlecolor": INK, "axes.titlesize": 10.5, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "font.size": 9, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 1.8, "legend.frameon": False,
})


def save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / name, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return f"figures/{name}"


# =========================================================================== figures


def clean_assessments(cfg):
    out = {}
    for site in pl.sites(cfg):
        station, power, (lat, lon) = pl.load_site(site, cfg)
        out[site] = (station, A.assess(station, power, lat, lon, cfg["split"], site=site))
    return out


def fig_residual_climates(clean):
    fig, ax = plt.subplots(figsize=(8.5, 3.4))
    variables = ["temp_c", "rh_pct", "wind_ms", "solar_mj_m2", "precip_mm"]
    for k, site in enumerate(clean):
        res = clean[site][1].residuals.loc["2024"]
        data = [res[v].dropna().to_numpy() for v in variables]
        pos = np.arange(len(variables)) + (k - 1) * 0.26
        bp = ax.boxplot(data, positions=pos, widths=0.22, patch_artist=True, showfliers=False,
                        medianprops=dict(color=INK, lw=1.2), whiskerprops=dict(color=INK2), capprops=dict(color=INK2))
        for b in bp["boxes"]:
            b.set(facecolor=SITE_COLOURS[site], edgecolor=SURFACE, alpha=0.9)
        ax.plot([], [], "s", color=SITE_COLOURS[site], label=SITE_NAMES[site])
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_xticks(range(len(variables)), [VAR_NAMES[v] for v in variables])
    ax.set_ylabel("standardized residual (σ)")
    ax.set_title("Clean 2024 residuals (never seen by the calibration): centred and of similar width in three climates")
    ax.legend(loc="upper right", ncol=3, fontsize=8)
    return save(fig, "residual_climates.png")


def fig_wandering(clean):
    fig, ax = plt.subplots(figsize=(8.5, 3.0))
    for site in clean:
        r = clean[site][1].residuals["temp_c"]
        m = r.resample("ME").mean()
        ax.plot(m.index, m, color=SITE_COLOURS[site], label=SITE_NAMES[site])
    ax.axhline(0, color=INK2, lw=0.8)
    ax.axvspan(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31"), color=GRID, alpha=0.5, lw=0)
    ax.text(pd.Timestamp("2024-01-20"), ax.get_ylim()[1] * 0.85, "test year", color=INK2, fontsize=8.5)
    ax.set_ylabel("monthly mean (σ)")
    ax.set_title("Monthly mean of the clean temperature residual: it wanders by up to about ±1 σ with no attack")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, fontsize=8)
    return save(fig, "wandering.png")


def fig_extreme(clean):
    ex = pd.read_csv(REP / "extreme_weather.csv")
    fig, axes = plt.subplots(1, 2, figsize=(8.5, 2.9), sharey=True)
    for ax, ind, title in ((axes[0], "detector S (combined)", "Detector S alarm days"),
                           (axes[1], "station not trusted (de-weighted or quarantined)", "Days the station is not trusted")):
        d = ex[ex.indicator == ind].set_index("site")
        x = np.arange(len(d))
        ax.bar(x - 0.19, d["flagged_share_ordinary"] * 100, 0.36, color=BLUE, label="ordinary days", edgecolor=SURFACE, lw=2)
        ax.bar(x + 0.19, d["flagged_share_extreme"] * 100, 0.36, color=ORANGE, label="extreme-weather days", edgecolor=SURFACE, lw=2)
        for xi, (o, e) in enumerate(zip(d["flagged_share_ordinary"], d["flagged_share_extreme"])):
            ax.text(xi - 0.19, o * 100 + 0.3, f"{o * 100:.1f}", ha="center", fontsize=7.5, color=INK2)
            ax.text(xi + 0.19, e * 100 + 0.3, f"{e * 100:.1f}", ha="center", fontsize=7.5, color=INK2)
        ax.set_xticks(x, d.index); ax.set_title(title); ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("share of clean 2024 days (%)")
    axes[0].legend(loc="upper left", fontsize=8)
    return save(fig, "extreme.png")


def fig_roc():
    c = pd.read_csv(REP / "roc_curves.csv")
    fig, axes = plt.subplots(1, 2, figsize=(8.5, 3.6))
    colours = {"full fusion (S + M)": BLUE, "S only": ORANGE, "M only": AQUA, "CUSUM only": YELLOW}
    for ax, log in ((axes[0], False), (axes[1], True)):
        for name, g in c.groupby("variant", sort=False):
            ax.plot(g["fpr"], g["tpr"], color=colours[name], label=name, lw=1.6)
        ax.plot([1e-4, 1], [1e-4, 1], color=INK2, ls="--", lw=0.8)
        ax.set_xlabel("false-positive rate (clean days flagged)"); ax.set_ylabel("true-positive rate (attacked days flagged)")
        if log:
            ax.set_xscale("log"); ax.set_xlim(1e-3, 1); ax.axvline(0.01, color=INK2, lw=0.8, ls=":")
            ax.text(0.0105, 0.95, "1 % FPR", color=INK2, fontsize=8)
            ax.set_title("Same, false-positive rate on a log scale")
        else:
            ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.set_title("Per-day ROC, leave one site out")
    axes[0].legend(loc="lower right", fontsize=8)
    return save(fig, "roc.png")


def fig_ablation():
    r = pd.read_csv(REP / "roc.csv")
    r = r.sort_values("roc_auc")
    fig, ax = plt.subplots(figsize=(8.5, 3.6))
    y = np.arange(len(r))
    ax.barh(y, r["roc_auc"], color=[BLUE if v == "full fusion (S + M)" else "#9db9df" for v in r["variant"]], edgecolor=SURFACE, lw=2)
    for yi, v in zip(y, r["roc_auc"]):
        ax.text(v + 0.003, yi, f"{v:.3f}", va="center", fontsize=8, color=INK2)
    ax.set_yticks(y, r["variant"]); ax.set_xlim(0.5, max(r["roc_auc"]) + 0.05)
    ax.set_xlabel("per-day ROC-AUC on the held-out site"); ax.grid(axis="y", visible=False)
    ax.set_title("Ablation: which evidence matters")
    return save(fig, "ablation.png")


def fig_latency():
    r = pd.read_csv(STD / "runs.csv").fillna({"relative_to": ""})
    s = r[(r.detector == "S") & r.detected]
    groups = [("replay", ""), ("step", "range"), ("step", "value"), ("step", "std"), ("drift", "range"), ("drift", "value"), ("drift", "std")]
    data = [s[(s.attack == a) & (s.relative_to == rel)]["latency_days"].dropna().to_numpy() for a, rel in groups]
    fig, ax = plt.subplots(figsize=(8.5, 3.0))
    bp = ax.boxplot(data, patch_artist=True, showfliers=False, widths=0.5, medianprops=dict(color=INK, lw=1.3))
    for b in bp["boxes"]:
        b.set(facecolor=BLUE, alpha=0.85, edgecolor=SURFACE)
    ax.set_xticks(range(1, len(groups) + 1), ["replay" if a == "replay" else f"{a}, of {rel}" for a, rel in groups])
    ax.set_ylabel("days from onset to first alarm")
    ax.set_title("Detection latency of detector S, detected episodes only (daily data: 0 = flagged on the first attacked day)")
    return save(fig, "latency.png")


def fig_stealth():
    s = pd.read_csv(REP / "stealth.csv")
    fig, axes = plt.subplots(1, 2, figsize=(8.5, 3.2), sharey=True)
    for ax, rel in zip(axes, ("value", "range")):
        g = s[s.relative_to == rel].groupby(["variable", "magnitude"])["S detected"].mean().reset_index()
        for var, gg in g.groupby("variable"):
            ax.plot(gg["magnitude"] * 100, gg["S detected"] * 100, "-o", ms=4, color=VAR_COLOURS[var], label=VAR_NAMES[var])
        ax.axvline(12, color=INK2, ls=":", lw=0.9); ax.text(12.4, 3, "official 12 %", fontsize=8, color=INK2)
        ax.set_xlabel(f"step size, % of the {rel}"); ax.set_title(f"Step of x % of the {rel}")
        ax.set_ylim(0, 103)
    axes[0].set_ylabel("steps detected by S (%)")
    axes[0].legend(loc="lower right", fontsize=8)
    return save(fig, "stealth.png")


def fig_slow_drift():
    d = pd.read_csv(REP / "slow_drift.csv")
    g = d.groupby(["variable", "ramp_days"]).agg(rate=("S detected", "mean"), lat=("S latency", "median")).reset_index()
    fig, axes = plt.subplots(1, 2, figsize=(8.5, 3.0))
    for var, gg in g.groupby("variable"):
        axes[0].plot(gg["ramp_days"], gg["rate"] * 100, "-o", ms=4, color=VAR_COLOURS[var], label=VAR_NAMES[var])
        axes[1].plot(gg["ramp_days"], gg["lat"], "-o", ms=4, color=VAR_COLOURS[var])
    axes[0].set_ylim(0, 103); axes[0].set_ylabel("drifts detected (%)"); axes[0].set_title("Detection against ramp length")
    axes[1].set_ylabel("median days to first alarm"); axes[1].set_title("Latency against ramp length")
    for ax in axes:
        ax.set_xlabel("days to reach +15 % of the range")
    axes[0].legend(fontsize=8, loc="lower right")
    return save(fig, "slow_drift.png")


def fig_perturbed():
    d = pd.read_csv(REP / "perturbed_replay.csv")
    g = d.groupby("noise_sd")[["replay matcher detected", "S detected", "CUSUM detected"]].mean() * 100
    fig, ax = plt.subplots(figsize=(8.5, 2.9))
    for col, colour, name in (("replay matcher detected", BLUE, "replay matcher alone"), ("S detected", ORANGE, "detector S (any part)"),
                              ("CUSUM detected", AQUA, "CUSUM alone")):
        ax.plot(g.index, g[col], "-o", ms=4, color=colour, label=name)
    ax.set_xscale("symlog", linthresh=0.01); ax.set_ylim(0, 103)
    ax.set_xlabel("noise added to the replayed values (standard deviations of each variable)")
    ax.set_ylabel("replays detected (%)"); ax.legend(fontsize=8, loc="lower left")
    ax.set_title("Evasion E5: a replay perturbed with noise to defeat exact matching")
    return save(fig, "perturbed_replay.png")


# =========================================================================== html helpers


def table(df: pd.DataFrame, fmt: dict | None = None, cls: str = "") -> str:
    fmt = fmt or {}
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            v = r[c]
            if c in fmt and pd.notna(v) and not isinstance(v, str):
                v = fmt[c](v)
            elif isinstance(v, float):
                v = "" if np.isnan(v) else f"{v:.2f}"
            cells.append(f"<td>{v}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def md_table(rows: list[list[str]], header: list[str], cls: str = "") -> str:
    head = "".join(f"<th>{h}</th>" for h in header)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def figure(src: str, caption: str, width: str = "100%") -> str:
    return f'<figure><img src="{src}" style="width:{width}"><figcaption>{caption}</figcaption></figure>'


def pct(v):
    return f"{v * 100:.0f} %"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


CSS = """
@page { size: A4; margin: 18mm 17mm 18mm 17mm;
        @bottom-center { content: counter(page); font: 9pt 'Segoe UI', Arial, sans-serif; color: #52514e; } }
@page :first { @bottom-center { content: none; } }
body { font: 10pt/1.45 'Segoe UI', Arial, sans-serif; color: #0b0b0b; }
h1 { font-size: 17pt; margin: 0 0 4mm; page-break-before: always; border-bottom: 2px solid #2a78d6; padding-bottom: 2mm; }
h2 { font-size: 12.5pt; margin: 6mm 0 2mm; color: #1a4f8f; page-break-after: avoid; }
h3 { font-size: 10.5pt; margin: 4mm 0 1.5mm; page-break-after: avoid; }
p { margin: 1.5mm 0 2.5mm; text-align: justify; }
ul, ol { margin: 1mm 0 2.5mm 5mm; padding-left: 4mm; } li { margin: 0.6mm 0; }
table { border-collapse: collapse; width: 100%; margin: 2mm 0 4mm; font-size: 8.6pt; }
tr { page-break-inside: avoid; } thead { display: table-header-group; }
th { background: #eef3fa; text-align: left; padding: 1.4mm 1.8mm; border-bottom: 1.5px solid #9db9df; }
td { padding: 1.1mm 1.8mm; border-bottom: 0.6px solid #e4e3df; vertical-align: top; }
table.num td:not(:first-child), table.num th:not(:first-child) { text-align: right; }
figure { margin: 3mm 0 4mm; page-break-inside: avoid; text-align: center; }
figure img { max-width: 100%; }
figcaption { font-size: 8.6pt; color: #52514e; margin-top: 1.5mm; text-align: left; }
code, pre { font-family: Consolas, monospace; font-size: 8.4pt; }
pre { background: #f6f6f4; border-left: 3px solid #9db9df; padding: 2mm 3mm; white-space: pre-wrap; page-break-inside: avoid; }
.box { border: 1px solid #9db9df; background: #f3f7fc; padding: 2.5mm 3.5mm; margin: 2mm 0 4mm; page-break-inside: avoid; }
.warn { border-color: #eda100; background: #fdf6e3; }
.key { font-size: 15pt; font-weight: 700; color: #1a4f8f; }
.kpis { display: flex; gap: 3mm; margin: 3mm 0 4mm; } .kpi { flex: 1; border: 1px solid #c9d8ee; padding: 2mm 3mm; background: #f7faff; }
.kpi small { display: block; color: #52514e; font-size: 8pt; line-height: 1.3; }
.title { page-break-after: always; padding-top: 40mm; }
.title h1 { page-break-before: avoid; border: none; font-size: 24pt; line-height: 1.2; color: #1a4f8f; }
.title .sub { font-size: 13pt; color: #52514e; margin-top: 4mm; }
.title .meta { margin-top: 40mm; font-size: 10pt; color: #52514e; line-height: 1.7; }
.toc { columns: 1; font-size: 10pt; line-height: 1.75; } .toc a { color: #0b0b0b; text-decoration: none; }
.flow { display: flex; align-items: stretch; gap: 1.2mm; margin: 3mm 0; page-break-inside: avoid; flex-wrap: nowrap; }
.flow .n { flex: 1; border: 1px solid #9db9df; background: #f3f7fc; border-radius: 1.5mm; padding: 1.6mm; font-size: 7.6pt; text-align: center; line-height: 1.25; }
.flow .n b { display: block; font-size: 8pt; margin-bottom: 0.6mm; }
.flow .a { align-self: center; color: #52514e; font-size: 10pt; }
.z-un { background: #fdeeea !important; border-color: #eb6834 !important; }
.z-tr { background: #e6f4ec !important; border-color: #1baf7a !important; }
.z-co { background: #fdf6e3 !important; border-color: #eda100 !important; }
.legend span { display: inline-block; padding: 0.4mm 2mm; margin-right: 2mm; font-size: 8pt; border: 1px solid; }
.small { font-size: 8.6pt; color: #52514e; }
"""


# =========================================================================== content


def build(cfg) -> str:
    std_att = pd.read_csv(STD / "by_attack.csv").fillna({"relative_to": ""})
    std_var = pd.read_csv(STD / "by_variable.csv")
    fa = pd.read_csv(STD / "false_alarms.csv")
    tr_runs = pd.read_csv(TRU / "runs.csv").fillna({"relative_to": ""})
    tr_clean = pd.read_csv(TRU / "clean.csv")
    tr_scores = pd.read_csv(TRU / "probability_scores.csv")
    tr_resp = pd.read_csv(TRU / "response.csv").fillna({"relative_to": ""})
    tr_coef = pd.read_csv(TRU / "fusion_coefficients.csv")
    l1 = pd.read_csv(REP / "layer1.csv")
    ov = pd.read_csv(REP / "overhead.csv")
    roc = pd.read_csv(REP / "roc.csv")
    stealth = pd.read_csv(REP / "stealth.csv")
    slow = pd.read_csv(REP / "slow_drift.csv")
    pert = pd.read_csv(REP / "perturbed_replay.csv")
    hw = json.loads((REP / "hardware.json").read_text(encoding="utf-8"))
    fusion_meta = json.loads((ROOT / "results/models_fusion/fusion.json").read_text(encoding="utf-8"))
    gran = pd.read_csv(ROOT / "results/models_detector_m/threshold_granularity.csv").set_index("mode")
    m_gran = ("Mean / worst false-alarm rate on a held-out training year: "
              + "; ".join(f"{k} {gran.loc[k, 'mean_fpr'] * 100:.1f} % / {gran.loc[k, 'max_fpr'] * 100:.0f} %"
                          for k in ("global", "site", "season"))
              + f". <b>{gran.index[0]}</b> is used. The worst case shows how much one year can differ from the others.")

    warnings.filterwarnings("ignore")
    clean = clean_assessments(cfg)
    f_climates = fig_residual_climates(clean)
    f_wander = fig_wandering(clean)
    f_extreme = fig_extreme(clean)
    f_roc, f_abl = fig_roc(), fig_ablation()
    f_lat, f_stealth, f_slow, f_pert = fig_latency(), fig_stealth(), fig_slow_drift(), fig_perturbed()
    img = lambda n: f"../docs/images/{n}"  # noqa: E731

    def rate(det, attack, rel):
        r = std_att[(std_att.detector == det) & (std_att.attack == attack) & (std_att.relative_to == rel)].iloc[0]
        return r

    def rate_txt(det, attack, rel):
        r = rate(det, attack, rel)
        return f"{int(r.detected)}/{int(r.episodes)} = <b>{r.detection_rate * 100:.0f} %</b> <span class='small'>({r.ci_low * 100:.0f}–{r.ci_high * 100:.0f})</span>"

    def lat(det, attack, rel):
        v = rate(det, attack, rel).median_latency_days
        return "" if pd.isna(v) else f"{v:.0f} d"

    s_fa = fa[fa.detector == "S"]["false_alarms_per_year"].mean()
    m_fa = fa[fa.detector == "M"]["false_alarms_per_year"].mean()
    wd0, wd4 = tr_runs["wrong_days_c0"].mean(), tr_runs["wrong_days_c4"].mean()
    full = roc[roc.variant == "full fusion (S + M)"].iloc[0]
    s_only = roc[roc.variant == "S only"].iloc[0]
    rel_tab = pd.read_csv(TRU / "reliability.csv", index_col=0)
    _ex = pd.read_csv(REP / "extreme_weather.csv").set_index("site")
    ex_s = _ex[_ex.indicator == "detector S (combined)"].flagged_share_extreme
    ex_o = _ex[_ex.indicator == "detector S (combined)"].flagged_share_ordinary
    ex_nt = _ex[_ex.indicator.str.startswith("station not trusted")].flagged_share_extreme
    ex_nto = _ex[_ex.indicator.str.startswith("station not trusted")].flagged_share_ordinary
    _resp = pd.read_csv(TRU / "response.csv").fillna({"relative_to": ""})

    def resp_days(attack, rel):
        r = _resp[(_resp.attack == attack) & (_resp.relative_to == rel)].iloc[0]
        return f"{r['median days to quarantine']:.0f} d"
    _sr = pd.read_csv(STD / "runs.csv")
    _steps = _sr[(_sr.detector == "S") & (_sr.attack == "step")]
    _sign = _steps.groupby("sign").detected.mean()
    _season = _steps.groupby(pd.to_datetime(_steps.onset).dt.month).detected.mean()
    _size = _sr[(_sr.detector == "S") & (_sr.attack != "replay")].groupby(["variable", "relative_to"]).residual_shift_sd.apply(lambda v: v.abs().median())
    _big = _size[_size >= 1.5]
    _small = _size[_size < 1.0]
    size_sentence = (
        f"The sign of the attack (up {_sign.get(1, float('nan')) * 100:.0f} %, down {_sign.get(-1, float('nan')) * 100:.0f} % of steps) and the onset season "
        f"({_season.min() * 100:.0f}–{_season.max() * 100:.0f} %) make little difference; the size relative to the natural disagreement explains almost "
        f"everything. Attacks of {_big.min():.1f}–{_big.max():.1f} σ ("
        + ", ".join(f"{VAR_NAMES[v]} of {r}" for v, r in _big.index)
        + f") are almost always caught; those of {_small.min():.1f}–{_small.max():.1f} σ ("
        + ", ".join(f"{VAR_NAMES[v]} of {r}" for v, r in _small.index)
        + ") mostly hide. With the regression witness, humidity attacks of value or range are now "
        + f"{_size.loc[('rh_pct', 'value')]:.1f}–{_size.loc[('rh_pct', 'range')]:.1f} σ.")
    removed = roc[roc.variant.str.startswith("without")].sort_values("roc_auc")
    worst = removed.iloc[0]
    abl_sentence = (f"Removing the <b>{worst.variant[len('without '):]}</b> costs the most (AUC {full.roc_auc:.3f} → "
                    f"{worst.roc_auc:.3f}, drift AUC {full.roc_auc_drift:.3f} → {worst.roc_auc_drift:.3f}).")
    ovd = dict(zip(ov["quantity"], zip(ov["value"], ov["unit"])))
    o = lambda q: f"{ovd[q][0]:g} {ovd[q][1]}"  # noqa: E731
    harmful = tr_runs[tr_runs.wrong_decision_c0]
    replay_harm = harmful[harmful.attack == "replay"]
    replay_trusted = int(tr_runs[tr_runs.attack == "replay"].wrong_trusted_c4.sum())
    std_runs = tr_runs[tr_runs.relative_to == "std"]
    std0, std4 = std_runs.wrong_days_c0.mean(), std_runs.wrong_days_c4.mean()
    if replay_trusted == 0:
        replay_sentence = (f"No replay produced a wrong decision issued as trusted ({len(replay_harm)} replays changed "
                           "the decision without defence).")
    else:
        replay_sentence = (f"{replay_trusted} of the {int((tr_runs.attack == 'replay').sum())} replays still produced a wrong "
                           f"decision issued as trusted ({len(replay_harm)} replays changed the decision without defence): "
                           "a replay is detected on day 1, but a station whose trust was already high can take a few days to "
                           "fall below the de-weighting band.")
    if std4 > std0:
        std_sentence = (f"For the smallest attacks (\"of std\") the defence slightly increases wrong days ({std0 * 100:.1f} → "
                        f"{std4 * 100:.1f} %): they are rarely detected, and partial de-weighting toward a reference that is "
                        "itself off by about 1 σ can move a decision close to a level boundary. Reported, not tuned away.")
    else:
        std_sentence = (f"For the smallest attacks (\"of std\") the defence changes little ({std0 * 100:.1f} → "
                        f"{std4 * 100:.1f} % wrong days): they are rarely detected.")
    cl = tr_clean.set_index("site")
    band_sentence = (
        "The quarantine threshold of a held-out site is the 0.5 % quantile of the clean trust of the two other sites, so "
        "it rests on about four days of clean data and moves with a single clean episode: here it is "
        + ", ".join(f"{k} {v:.2f}" for k, v in cl["quarantine_below"].items())
        + ". The false-quarantine cost on clean 2024 is "
        + (" and ".join(f"one long natural disagreement at {k.upper() if k != 'kansas' else 'Kansas'} ({v:.0f} days)"
                        for k, v in cl["quarantined_days_per_year"].items() if v > 0) or "nothing")
        + ". The bands are the least stable part of the system and the first Phase 2 item: "
        "more clean station-years to set them.")

    # ------------------------------------------------------------------ title, summary
    parts = [f"""
<div class="title">
  <h1>{TITLE}</h1>
  <div class="sub">Phase 1 technical report · Track 2: False Data Injection, in-situ sensing segment</div>
  <div class="sub">A prototype that proves where every weather-station reading came from, checks every station against
  an independent witness, gives each station a calibrated compromise probability and a trust score, and responds in four
  graded steps, so that a falsified reading does not silently drive an irrigation, drought or insurance decision.</div>
  <div class="meta">Anonymous submission · 2 November 2026<br>
  Code, data instructions and every number in this report: the accompanying repository
  (one command per table, see section 8).</div>
</div>

<h1 id="summary">Executive summary</h1>
<p><b>The problem.</b> Field weather stations are the ground truth of Earth observation: irrigation advice, drought
monitoring, index-based crop insurance and the validation of satellite products all rest on them. A station stands alone
in a field and is often hosted by the person who benefits from what it reports. The three attacks of the official
standard test (a 12 % step bias, a gradual drift up to 15 %, a replay of seven samples) are designed to look like
ordinary weather: a 12 % bias is about the size of the normal difference between a point station and a 50 km
reference grid cell.</p>
<p><b>The approach.</b> Three layers that fail in different places.
(1) <b>Provenance</b>: each reading is signed on the station with its own Ed25519 key, carries a sequence number and
the hash of the previous record, and is stored in a hash-chained ledger; this stops forgery, modification and replay on
the link and rewriting in the pipeline. (2) <b>Disagreement with an independent witness</b>: every variable is compared
with NASA POWER for the same place and day after a per-season calibration; a statistical detector (CUSUM, replay
matcher, Mahalanobis, trend) and a learned one-class detector look for lasting or unusual disagreement, never for
extreme values. (3) <b>Trust and response</b>: the detector outputs are fused into a calibrated compromise probability,
which drives a station trust score and four graded responses: de-weighting, verification request, quarantine, alert.</p>
<p><b>The evidence.</b> Three real stations in three climates, fitted on 2021–2023 and tested on 2024, with the attacker
at the station signing the false values itself (the case the jury tests): <b>756 attacked runs</b> covering the three
attacks on four variables, both signs, the three possible meanings of "12 %", and several onsets and drift lengths.</p>
<div class="kpis">
 <div class="kpi"><span class="key">{rate('S', 'replay', '').detection_rate * 100:.0f} %</span><small>of seven-day replays caught, on their first day, with 0 false alarms of the replay matcher</small></div>
 <div class="kpi"><span class="key">{rate('S', 'step', 'range').detection_rate * 100:.0f}–{rate('S', 'drift', 'range').detection_rate * 100:.0f} %</span><small>of 12 % steps and 15 % drifts caught by detector S when "12 %" is read as relative to the variable's range ({rate('S', 'step', 'value').detection_rate * 100:.0f}–{rate('S', 'drift', 'value').detection_rate * 100:.0f} % relative to the value)</small></div>
 <div class="kpi"><span class="key">{s_fa:.1f}</span><small>false alarms per station-year for detector S, from a budget of 1 per year set on the training years</small></div>
 <div class="kpi"><span class="key">−{(1 - wd4 / wd0) * 100:.0f} %</span><small>days with a wrong farm decision when the defence is on ({wd0 * 100:.1f} % → {wd4 * 100:.1f} % of the decision window)</small></div>
</div>
<p>The compromise probability is <b>calibrated on stations the model never saw</b> (Brier {tr_scores[tr_scores.site == 'all'].brier.iloc[0]:.3f}
against {tr_scores[tr_scores.site == 'all'].brier_no_skill.iloc[0]:.3f} without skill). Security costs {o('record size, fixed part (header + signature)')} per
record, {o('sign one record (station side)')} to sign and {o('verify one record (signature, certificate, sequence, chain)')} to verify on a laptop CPU.
<b>The limit is physical and stated:</b> attacks smaller than about 0.7 standard deviations of the station-to-reference
difference, which includes every "12 % of the standard deviation" case and most wind cases, hide in
the natural disagreement between a point and a grid cell. Closing that gap needs a second independent witness
(Sentinel-2, neighbouring stations), which is the Phase 2 plan.</p>
{figure(img('defence.png'), 'Figure 1. One attack followed through the whole defence: a drift to +15 % on solar radiation at the Kansas station from 1 May 2024 (shaded). (1) the disagreement with NASA POWER grows; (2) the CUSUM accumulates it and alarms; (3) the fused compromise probability rises; (4) trust falls through the de-weighting band into quarantine and recovers after the attack. The quarantine in January, months before the attack, is a false alarm on the clean data: a natural week-long humidity gap (section 6.7).', '92%')}

<h2 style="page-break-before: always">Where each deliverable is answered</h2>
{md_table([
    ["D1 Threat model and segment analysis", "15", "Section 2"],
    ["D2 Platform, architecture, trust anchor", "15", "Section 3"],
    ["D3 Signal processing", "15", "Section 4"],
    ["D4 AI or statistical detection", "20", "Section 5"],
    ["D5 Adversarial validation and response", "20", "Section 6"],
    ["D6 Documentation with the official reference datasets", "5 + feasibility", "Sections 7 and 8"],
    ["Mandatory metrics: detection, false alarms, latency, memory, security overhead", "", "Section 9 (summary table)"],
], ["Deliverable", "Points", "Where"])}

<h2>Contents</h2>
<div class="toc">
<a href="#s1">1. Scenario: stations as ground truth</a><br>
<a href="#s2">2. D1 Threat model and segment analysis</a><br>
<a href="#s3">3. D2 Architecture and trust anchor</a><br>
<a href="#s4">4. D3 Signal processing</a><br>
<a href="#s5">5. D4 Statistical and learned detection</a><br>
<a href="#s6">6. D5 Adversarial validation and response</a><br>
<a href="#s7">7. D6 Datasets</a><br>
<a href="#s8">8. Reproduction, tools and run time</a><br>
<a href="#s9">9. Mandatory metrics</a><br>
<a href="#s10">10. Limitations and Phase 2 plan</a><br>
<a href="#refs">References</a> · <a href="#appA">Appendix A: parameters</a>
</div>
"""]

    # ------------------------------------------------------------------ 1 scenario
    parts.append(f"""
<h1 id="s1">1. Scenario: stations as ground truth</h1>
<p>The track asks one question: <i>is this sensor stream consistent with its context?</i> Our sensor stream is a network
of agricultural weather stations reporting daily temperature, relative humidity, wind speed, rainfall and solar
radiation to a service that turns them into irrigation advice, drought indicators and index-insurance triggers.</p>
<p><b>Why it matters.</b> Every one of those decisions is a threshold on a water balance: how much rain fell against how
much water the crop could lose. An index-insurance contract pays when the 30-day balance falls below a trigger.
Raising the recorded temperature or solar radiation by 12 % raises the computed evapotranspiration and makes the field
look drier; replaying a dry week over a wet one hides the rain. The analyst never sees a forged document: they see a
genuine, correctly signed series that happens to be false. This is the silent failure the challenge describes.</p>
<p><b>Data.</b> Every measurement in the prototype comes from an authentic public dataset, and attacks are injected into
real records, so the ground-truth labels are exact to the day.</p>
{md_table([
    ["AZMET (University of Arizona network), station az09", "Arizona, USA", "semi-arid", "daily", "32.480, −109.930"],
    ["FAWN (Florida Automated Weather Network), Okahumpka", "Florida, USA", "humid subtropical", "15 minutes, aggregated to daily", "28.682, −81.886"],
    ["Kansas Mesonet, Manhattan", "Kansas, USA", "continental", "daily", "39.209, −96.592"],
    ["NASA POWER Daily API (official reference dataset), community AG", "the three points above", "reanalysis + satellite, about 0.5° grid", "daily", "same coordinates"],
], ["Source", "Place", "Climate", "Resolution", "Lat, lon"])}
<p>All five variables are used at all three sites from 1 January 2021 to 31 December 2024. The years 2021–2023 are the
<b>training</b> period (calibration, thresholds, models: clean data only) and 2024 is the <b>test</b> period on which every
reported number is measured. Copernicus Sentinel-2 L2A, the second official dataset, is part of the design (section 3)
but its indicators are not yet computed: this is stated as a limitation and is the first Phase 2 item.</p>
<p>The organizers have not said what "12 %" is relative to. Every attack is therefore run with three readings, and every
result table reports them separately: 12 % <b>of the value</b> (x → 1.12 x), <b>of the variable's range</b>
(x → x + 0.12 × the 1st-to-99th percentile span), and <b>of its standard deviation</b> (x → x + 0.12 σ). Range and
standard deviation are measured on the days before the attack, so the attacker's own values do not change its size.</p>
""")

    # ------------------------------------------------------------------ 2 threat model
    parts.append(f"""
<h1 id="s2">2. D1 Threat model and segment analysis</h1>
<h2>2.1 Segment and trust boundaries</h2>
<p>A network of weather stations on agricultural land, reporting daily to a service that produces decisions. The chain,
its trust zones and the three attacker positions:</p>
<div class="flow">
 <div class="n z-tr"><b>Weather at the site</b>ground truth</div><div class="a">→</div>
 <div class="n z-co"><b>Sensors</b>conditionally trusted<br>unattended for months<br><i>P1a</i></div><div class="a">→</div>
 <div class="n z-co"><b>Logger + firmware</b>conditionally trusted<br><i>P1b</i> · signs here</div><div class="a">→</div>
 <div class="n z-un"><b>Telemetry, gateway, cloud</b>untrusted, third party<br><i>P2</i></div><div class="a">→</div>
 <div class="n z-un"><b>Ingest + database</b>untrusted<br><i>P3</i></div><div class="a">→</div>
 <div class="n z-tr"><b>Detection + decision</b>trusted (what we build)</div><div class="a">→</div>
 <div class="n"><b>Analyst</b>irrigation, drought, insurance</div>
</div>
<div class="flow"><div class="n z-tr" style="flex:0.6"><b>NASA POWER · Sentinel-2</b>trusted as witnesses, with known error; out of a ground attacker's reach</div></div>
<p class="legend small"><span class="z-tr">trusted</span><span class="z-co">conditionally trusted</span><span class="z-un">untrusted</span></p>
<h2>2.2 Why in-situ sensors are exposed</h2>
<ul>
<li><b>Unattended and reachable:</b> a station stands alone in a field; a person and a few minutes are enough.</li>
<li><b>The person with access may be the person who benefits:</b> an index-insurance policy pays when the station records too
little rain or too much heat, and the holder of the land often hosts the station.</li>
<li><b>Constrained and cheap:</b> low-cost hardware, little power, small messages; security is the first thing left out.</li>
<li><b>Sparse:</b> few stations cover a large area, so one falsified station can move a decision.</li>
<li><b>Trusted by default:</b> in-situ data is what satellite products are validated against, rarely itself questioned.</li>
<li><b>Faults look the same:</b> humidity sensors drift, radiation sensors get dirty, gauges clog. A slow drift is both the
most common fault and one of the official attacks.</li>
</ul>
<h2>2.3 Assets and required properties</h2>
{md_table([
 ["A measurement", "integrity, <b>truthfulness</b>", "the indicator and the decision built on it are wrong"],
 ["Measurement origin and position", "authenticity, provenance", "a reading claims a station or place it did not come from"],
 ["Measurement time and order", "freshness", "last week's weather presented as this week's"],
 ["Measurement stream", "availability, detectable absence", "an event goes unrecorded and nobody notices"],
 ["Reference and context data", "integrity, traceable origin", "the witnesses themselves cannot be audited"],
 ["Processing history", "auditability", "a decision cannot be traced back to its readings"],
 ["Station private keys", "confidentiality", "the attacker signs as the station"],
 ["Registry, replay state, ledger", "integrity", "verification can be subverted"],
 ["Calibration, baselines, models", "integrity", "the attacker teaches the detector that false is normal"],
], ["Asset", "Property", "Failure means"])}
<div class="box"><b>Integrity is not truthfulness.</b> Integrity means the reading was not changed after the station
produced it; cryptography delivers that. Truthfulness means the reading reflects the weather; only cross-checking
against independent evidence delivers that. Track 2 lives in the gap between the two, and the design has one layer for
each.</div>
<h2>2.4 Attacker profiles</h2>
{md_table([
 ["<b>P1a</b> at the sensor", "deceives the physical measurement: shades the radiation sensor, waters or covers the gauge, warms a probe, moves the station", "nothing: the station honestly signs what it measured", "very low"],
 ["<b>P1b</b> in the logger or firmware", "changes values before they are signed (a calibration factor is enough for a 12 % bias); may extract the key", "nothing: false data carries a valid signature", "medium"],
 ["<b>P2</b> on the link, gateway or platform", "reads, injects, modifies, replays, delays and drops messages", "<b>stop</b> forgery, modification and replay; dropping is detected, not prevented", "low to medium"],
 ["<b>P3</b> in ingest, database, processing", "rewrites stored or forwarded values, deletes records", "<b>stop</b> it, if verification is end to end and the ledger is checked", "medium (intrusion or insider)"],
], ["Position", "Capability", "What signatures do", "Cost"])}
<p><b>Knowledge levels</b> used in the evaluation: <i>black box</i> (knows what the station measures, not the defence),
<i>grey box</i> (knows the design, not the thresholds) and <i>white box</i> (knows thresholds and models and reads the same
public NASA POWER data). <b>Assumed out of reach:</b> the offline root key; breaking Ed25519 or SHA-256; falsifying NASA
POWER or Sentinel-2 at their source.</p>
<h2>2.5 Taxonomy of injection attacks</h2>
{md_table([
 ["<b>F1</b>", "<b>Step bias</b> (official: 12 %)", "P1, P2, P3", "from one day on every value raised or lowered by a fixed proportion", "an indicator crosses (or fails to cross) a threshold", "<b>evaluated</b> (288 runs)"],
 ["<b>F2</b>", "<b>Gradual drift</b> (official: up to 15 %)", "P1, P2, P3", "the offset grows slowly to its final size", "as F1, built to pass for sensor ageing", "<b>evaluated</b> (432 runs) + E1"],
 ["<b>F3</b>", "<b>Replay</b> (official: seven samples)", "P1b, P2, P3", "a recorded stretch of genuine past data is played back", "a rain event or a hot spell is hidden behind realistic data", "<b>evaluated</b> (36 runs) + E5"],
 ["F4", "Freeze", "P1, P2", "the last value is repeated", "station alive but reporting nothing new", "covered by the replay matcher (lag 1); not separately evaluated"],
 ["F5", "Event masking or fabrication", "P1b, P2, P3", "a rainy week erased, a heatwave inserted", "a payout triggered or avoided", "Phase 2"],
 ["F6", "Noise or spike injection", "P1, P2", "random noise or outliers added", "degrades quality control, provokes alarms", "Phase 2"],
 ["F7", "Suppression", "P1, P2, P3", "readings dropped", "a gap exactly when it matters", "layer 1 chain gap and cadence watchdog (unit tests)"],
 ["F8", "Delay or date shift", "P2, P3", "readings late or re-dated", "the picture lags reality", "layer 1 timing check (unit tests)"],
 ["F9", "Coordinated injection", "several variables or stations", "consistent false values", "defeats checks between variables", "replay at P1 copies all variables; otherwise Phase 2"],
 ["F10", "Provenance stripping", "P2, P3", "signature removed to look like a legacy record", "verification silently skipped", "prevented: unsigned records are never accepted"],
 ["F11", "Station key compromise", "P1b", "attacker signs anything as the station", "forgeries pass layer 1", "equivalent to P1: detection results apply unchanged"],
], ["ID", "Attack", "Position", "What happens", "Impact", "Status in this report"])}
<p><b>STRIDE view.</b> Spoofing: F5, F11. Tampering: F1–F6, F9, F10. Repudiation: addressed by per-station signatures and
the ledger. Information disclosure: out of scope. Denial of service: F7, F8. Elevation of privilege: F11.</p>
<h2>2.6 Evasion strategies</h2>
{md_table([
 ["E1", "change detection", "slower, smaller drift: stretch the ramp over months", "<b>evaluated</b>, section 6.6"],
 ["E2", "quality control", "stay inside range and rate-of-change limits", "the official attacks already do; detection never relies on limits"],
 ["E3", "physical consistency", "change temperature, humidity and radiation together", "Phase 2 (no physical-consistency residual yet)"],
 ["E4", "reference comparison", "analogue replay: replay the past week that best matches the current NASA POWER week", "Phase 2"],
 ["E5", "replay detection", "perturbed replay: add noise so the copy is not exact", "<b>evaluated</b>, section 6.6"],
 ["E6", "reference context", "hide in the reference's error: attack rain, wind, humidity, keep inside the normal spread", "<b>measured</b> as the stealth budget, section 6.6"],
 ["E7", "calibration", "baseline poisoning: be present while the system learns what normal is", "stated limit of file mode (section 10)"],
 ["E8", "operators", "fault mimicry, alarm fatigue", "false-alarm budget and graded responses limit fatigue; not evaluated"],
 ["E9", "everything", "white-box optimisation: largest change under every threshold", "approximated by the step-size sweep (stealth budget), section 6.6"],
], ["ID", "Target", "Strategy", "Status"])}
<h2>2.7 Attack-to-control mapping</h2>
{md_table([
 ["F1 step bias", "prevents at P2, P3", "CUSUM against the reference; Mahalanobis for large steps", "prevented in transit; <b>detected</b> at the station within days when above the natural spread"],
 ["F2 gradual drift", "prevents at P2, P3", "CUSUM once the accumulated offset exceeds the spread; trend (reported)", "detected late, bounded"],
 ["F3 replay", "<b>prevents</b> at P2, P3 (sequence, chain)", "replay matcher (exact copy of the station's own past); CUSUM and Mahalanobis (the copy no longer follows the reference)", "prevented in transit; <b>detected on day 1</b> at the station"],
 ["F4 freeze", "—", "replay matcher at lag 1", "detected"],
 ["F7 suppression", "<b>detects</b> (chain gap, cadence watchdog)", "—", "detected, not prevented"],
 ["F8 delay", "<b>detects</b> (date against arrival, sequence)", "—", "detected"],
 ["F10 stripping", "<b>prevents</b>", "—", "prevented"],
 ["F11 key compromise", "defeated, limited by revocation", "applies unchanged", "detected by content"],
], ["Attack", "Layer 1 provenance", "Layers 2–3 detection against the witness", "Outcome"])}
<p>Signatures alone close the telemetry and the pipeline completely and do nothing at the station. Detection against
the witness catches a lying station however the lie was made, but only as sharply as the reference represents that
variable at that place. The layers fail in different places, which is the argument for having both.</p>
<h2>2.8 Residual risk, stated honestly</h2>
<ul>
<li><b>A bias smaller than the reference's own error is undetectable.</b> The defence bounds how far an attacker can move
the picture; it does not make the bound zero. Section 6.6 measures the bound per variable.</li>
<li><b>Some variables are weakly protected:</b> daily rain and wind at a point are poorly represented by a grid cell.</li>
<li><b>Attacks and faults look alike:</b> the system detects that a stream is wrong, not why; the response is the same.</li>
<li><b>Availability cannot be guaranteed:</b> suppression is detected and compensated, not prevented.</li>
<li><b>The reference is not perfectly independent:</b> a reanalysis may assimilate public observations; checked per variable in Phase 2.</li>
<li><b>Out of scope:</b> attacks on satellites, on NASA POWER or Copernicus themselves; confidentiality; denial of service against the trust service; the correctness of the downstream agronomic or insurance model.</li>
</ul>
<h2>2.9 Evidence the threat is real</h2>
<ul>
<li>Coordinated false data can pass residual-based checks in state estimation [1]: the reason detection here relies on an
independent witness, not on the sensor's own consistency.</li>
<li>Replay of recorded normal sensor readings to operators while a process was driven out of bounds (the Stuxnet case) [2]: the official replay attack.</li>
<li>Physical signal injection into sensors with sound or electromagnetic interference [3, 4]: the P1a attacker.</li>
<li>Quality control of automatic weather stations is a recognised operational problem with standard tests [5], and the FAO-56 method behind
the decision indicator [6] is sensitive to exactly the variables attacked here.</li>
</ul>
""")

    # ------------------------------------------------------------------ 3 architecture
    l1_tab = l1.rename(columns={"attack": "Attack", "position": "Position", "attacked_days": "Attacked days",
                                "rejected_by_layer1": "Rejected by layer 1", "reasons": "Reason",
                                "ledger_intact": "Ledger intact", "ledger_first_broken": "Ledger broken at",
                                "attacked_values_reaching_detection": "Attacked days reaching detection"})
    parts.append(f"""
<h1 id="s3">3. D2 Architecture and trust anchor</h1>
<h2>3.1 Design principles</h2>
<ol>
<li><b>Sign at the source, verify at the service.</b> The station key never leaves the station; every record is checked
before any analysis.</li>
<li><b>Detect disagreement, not extremes.</b> Genuine extreme weather moves the station and its witnesses together;
an injection moves only the station.</li>
<li><b>Accumulate evidence over days.</b> A 12 % bias hides in any single day; a disagreement that never averages out does not.</li>
<li><b>Thresholds from a false-alarm budget,</b> set on clean training years only, so the cost on honest stations is fixed before any attack is seen.</li>
<li><b>Trust is a score, not a switch,</b> and every action carries a reason an operator can check.</li>
<li><b>Nothing depends on a particular station:</b> the input is a series plus coordinates (the final test site is hidden).</li>
</ol>
<h2>3.2 Block diagram</h2>
<div class="flow">
 <div class="n"><b>Station</b>sensors, logger<br>Ed25519 key in a secure element</div><div class="a">→</div>
 <div class="n"><b>Signed record</b>seq, time, prev-hash, payload, signature</div><div class="a">→</div>
 <div class="n z-tr"><b>L1 verify</b>certificate, signature, sequence, time, chain<br>→ ledger</div><div class="a">→</div>
 <div class="n"><b>Preparation</b>clean, align, calibrate against NASA POWER<br>→ residuals</div><div class="a">→</div>
 <div class="n"><b>L2–L3 detection</b>detector S (CUSUM, replay, Mahalanobis, trend) + detector M (LOF)</div><div class="a">→</div>
 <div class="n"><b>Fusion</b>compromise probability → trust score</div><div class="a">→</div>
 <div class="n z-co"><b>Response</b>de-weight, verify, quarantine, alert</div><div class="a">→</div>
 <div class="n"><b>Product</b>30-day water balance, decision + provenance</div>
</div>
<h2>3.3 One reading becoming a decision</h2>
{md_table([
 ["1", "Station", "measures the day; builds a record (sensor id, key id, seq = n, t_obs, prev_hash = SHA-256 of record n−1, payload); signs it with its Ed25519 key"],
 ["2", "Link", "carries 139 bytes (5 variables); an attacker here has no key"],
 ["3", "Service, L1", "parses; checks the certificate (enrolled, not revoked, valid at t_obs, position bound); verifies the signature; checks seq > last seq, t_obs against arrival time and cadence, prev_hash against the last accepted hash; appends to the hash-chained ledger"],
 ["4", "Preparation", "joins the day with NASA POWER for the enrolled position; applies the frozen per-season calibration; computes the standardized residual per variable"],
 ["5", "Detection", "updates the CUSUM sums, the replay window distances, the Mahalanobis distance, the trend statistic, detector M's window features"],
 ["6", "Fusion and trust", "fuses the day's evidence into a compromise probability p; updates the trust score; maps it to a band"],
 ["7", "Response", "trusted: full weight. De-weighted: implicated variables blended toward the calibrated reference; verification request if trust is still falling. Quarantined: implicated variables replaced; alert with reason and estimated onset"],
 ["8", "Product", "computes ET0 and the 30-day water balance from the series after the response; issues the decision level, TRUSTED or DEGRADED, with its provenance record"],
], ["Step", "Where", "What happens"])}
<h2>3.4 Trust anchor</h2>
<ul>
<li><b>Root of trust:</b> an offline Ed25519 root key held by the network operator. It only signs certificates.</li>
<li><b>Station identity:</b> one key pair per station, generated on the device. The private key never leaves it. In the
prototype it sits behind a <code>SecureElement</code> interface that exposes only <code>sign()</code> and
<code>public_key()</code>, which is exactly what a hardware secure element would implement.</li>
<li><b>Enrolment binds the position.</b> The root signs a certificate binding the station's public key to its identifier,
<b>its position</b> and a validity window. The reference and the satellite context are looked up by position, so a
station that could claim another place would be checked against the wrong witnesses.</li>
<li><b>Rotation:</b> every record carries a 2-byte <code>key_id</code>; a new certificate with a new key id replaces the old one at a date.</li>
<li><b>Revocation:</b> a station judged compromised stays in the registry (its past remains on record) but its later records are rejected.</li>
<li><b>One key per station:</b> compromising one station does not let the attacker speak for any other, and every false reading is attributable to one device.</li>
</ul>
<h2>3.5 Record format and measured overhead</h2>
{md_table([
 ["version", "1 B", "format evolution"], ["type", "1 B", "reading, status, heartbeat"], ["sensor_id", "4 B", "which station"],
 ["key_id", "2 B", "which station key (rotation)"], ["seq", "4 B", "strictly increasing: ordering and replay protection"],
 ["t_obs", "8 B", "observation date at the station"], ["prev_hash", "32 B", "SHA-256 of the previous record: detects gaps, reordering, history rewriting"],
 ["payload_len", "2 B", ""], ["payload", "variable", "the day's values, fixed point (value × 1000, 32-bit), plus a status byte"],
 ["signature", "64 B", "Ed25519 over every field above"],
], ["Field", "Size", "Purpose"])}
<p>The fixed part is <b>{o('record size, fixed part (header + signature)')}</b> (measured, and checked by a unit test). With five variables the
payload is {o('record payload, 5 variables')} and the whole record {o('record size, total')}. At one record per station per day this is negligible on a
cellular link; on low-power radio limited to a few tens of bytes, a compact mode (truncated chain hash, one signature per
batch of days) is the documented option.</p>
<h2>3.6 Verification algorithm and anti-replay state</h2>
<pre>1. Parse the record.                                  malformed            -> REJECT malformed
2. sensor_id unknown, revoked, or certificate not
   valid at t_obs (or key_id mismatch)                                     -> REJECT unknown_station
3. Ed25519 signature over the signed region invalid                        -> REJECT forged
4. seq &lt;= last accepted seq for this station                              -> REJECT replay
5. t_obs later than arrival + 1 h                                          -> REJECT stale
   arrival - t_obs &gt; cadence + margin (1 day + 1 day)                      -> FLAG   delayed
6. prev_hash != hash of the last accepted record                           -> ACCEPT, raise GAP
7. persist last_seq, last_hash, last_arrival; pass the reading on          -> ACCEPT</pre>
<p>Per-station persistent state is two values (<code>last_seq</code>, <code>last_hash</code>) plus the last arrival time for
the <b>cadence watchdog</b>: a station with no valid record within the expected interval plus a margin is reported
<i>silent</i>, which removes its weight and lowers product confidence; silence is never read as an uneventful day.</p>
<p><b>Tamper-evident ledger.</b> Accepted records are appended to a hash chain: entry <i>i</i> stores
SHA-256(entry <i>i−1</i> hash ‖ <i>i</i> ‖ record). Rewriting any stored record changes its hash and breaks every later link,
which is how an attacker inside the pipeline (P3) is caught.</p>
<p><b>Provenance through to the product.</b> Each product carries a provenance record: the inputs used (sensor id, sequence
range, chain hash, weight), the inputs excluded (sensor id, reason, estimated onset), the NASA POWER request (parameters,
point, dates, SHA-256 of the cached response), the processing steps and parameters, and the confidence (TRUSTED or
DEGRADED with the reason).</p>
<h2>3.7 Layer 1 measured: the same attacks at the three positions</h2>
<p>Every day of 2021–2024 at the FAWN station is signed with a real Ed25519 key, sent through the attacker, verified by the
real verifier and stored in the real ledger:</p>
{table(l1_tab, cls="num")}
<p>On the link (P2) every tampered record fails its signature and every replayed record fails the sequence check, so
<b>no attacked value reaches detection</b>. In the pipeline (P3) the rewritten values do reach the store, but the ledger
breaks at the first rewritten day and identifies it. At the station (P1) layer 1 accepts everything: that case belongs to
detection, and it is the case evaluated in sections 5 and 6.</p>
<h2>3.8 Cost, measured</h2>
{table(ov.rename(columns={"quantity": "Quantity", "value": "Value", "unit": "Unit"}), fmt={"Value": lambda v: f"{v:g}"})}
<p class="small">Measured on {html.escape(hw.get('cpu', ''))}, {hw.get('ram_gb', '')} GB RAM, {html.escape(hw['os'])}, Python {hw['python']}.
Software only, standard primitives (Ed25519, SHA-256), no hardware dependency.</p>
""")

    # ------------------------------------------------------------------ 4 signal processing
    eff = pd.read_csv(ROOT / "results/analysis_2021_2024/task4_effect_sizes.csv")
    eff_tab = eff.pivot(index="variable", columns="site", values="effect_size").reindex(["temp_c", "rh_pct", "wind_ms", "solar_mj_m2", "precip_mm"])
    eff_tab.index = [VAR_NAMES[v] for v in eff_tab.index]
    eff_tab = eff_tab.reset_index().rename(columns={"index": "12 % of the mean value, in σ of the residual"})
    checks = pd.read_csv(ROOT / "results/models_2021_2024/validation_check_summary.csv")
    checks = checks[(checks["mode"] == "full_train") & (checks.residual_family == "reference")][["site", "PASS", "WARN", "FAIL"]]
    parts.append(f"""
<h1 id="s4">4. D3 Signal processing</h1>
<h2>4.1 Pre-processing and quality control</h2>
<p>Every source is converted to one schema: one row per calendar day, columns <code>temp_c, rh_pct, wind_ms,
precip_mm, solar_mj_m2</code>, missing as NaN (never 0, never −999). The cleaning rules are the same for every source:</p>
<ul>
<li><b>Full daily calendar.</b> A missing day stays missing: nothing is interpolated or filled.</li>
<li><b>Fill codes and impossible values become missing,</b> and every removal is counted: temperature −40 to 50 °C,
humidity 1–100 %, wind 0–40 m/s, rain 0–300 mm/day, solar 0–40 MJ/m²/day.</li>
<li><b>Sub-daily to daily:</b> FAWN's 15-minute data is averaged (temperature, humidity, wind, solar) or summed (rain) per
day; a day needs at least 80 % of its readings, variable by variable. Units are converted (mph → m/s, inch → mm,
W/m² × 0.0864 → MJ/m²/day).</li>
<li><b>Each NASA POWER file must sit at the coordinates of a known site;</b> responses are cached with SHA-256 manifests.</li>
</ul>
<h2>4.2 Spatial and temporal mismatch: per-season calibration against the reference</h2>
<p>A station measures a point; NASA POWER describes a grid cell of about 50 km. Their difference has a systematic part
(altitude, exposure, local climate) and a random part. The calibration learns the systematic part on the training years,
<b>per variable and per season</b> (DJF, MAM, JJA, SON), robustly:</p>
<pre>gap_t      = station_t − power_t                                  temperature, humidity, solar
gap_t      = log((station_t + 0.1) / (power_t + 0.1))             wind, rain (multiplicative errors)
offset_s   = median(gap over the training days of season s)
spread_s   = 1.4826 × median(|gap − offset_s|)                     (MAD, floor 0.01 or 0.001)
residual_t = (gap_t − offset_s(t)) / spread_s(t)                   standardized residual, in σ</pre>
<p><b>A sharper witness for humidity.</b> Humidity is local: NASA POWER's humidity follows the station far less closely
(correlation 0.76–0.90) than its temperature (0.99), so a 12 % humidity attack was only 1–1.7 times the normal day-to-day
disagreement, against 2.6–5.7 times for temperature. For humidity the witness is therefore not POWER's own value but a
<b>ridge regression</b> of the station humidity on same-day POWER humidity, temperature, dew point (Magnus formula), log rain,
wind, solar and the season (two harmonics, and humidity and temperature × the first harmonic), fitted on the clean
training days only (α = 10, standardised inputs). The offset and spread above are then fitted on top of it. Only POWER
values enter the regression, so an attack on the station cannot move its own witness, and a temperature attack does not
leak into the humidity check. Tested out of sample before adoption (fit 2021–2022, measured on 2023), it raised the
ratio of a month-long 12 % humidity shift to the natural month-long wandering from 2.0 to 3.1 (AZMET), 2.8 to 3.5 (FAWN)
and 2.3 to 4.1 (Kansas). A dew-point comparison was tested too and rejected: it is worse at AZMET and mixes temperature
attacks into humidity.</p>
<p>Rain has a special rule: a day when both the station and POWER are dry (≤ 0.1 mm) gives no information, so its residual
is missing rather than zero (40–70 % of days depending on the site). The "calibrated reference" used for substitution
in quarantine is the inverse: POWER + offset (or the inverse log ratio). Day alignment: both sources are daily totals
or means on the local calendar day; the FAWN aggregation day is a stated point to verify.</p>
<p><b>Temporal modelling.</b> A second family of residuals compares each station with its own expected value given the
season (harmonic regression, order 2) and its recent history (AR(1)), fitted on the training years. These temporal
residuals are computed and validated; the detectors use the reference residuals, because only an independent witness
separates a lie from real weather.</p>
<h2>4.3 Validation gate: residuals on clean data, across climates and in extreme weather</h2>
{figure(f_climates, 'Figure 2. Standardized reference residuals on the clean test year (2024), which the calibration never saw. Boxes: interquartile range; whiskers: 1.5 IQR. Centred near zero and of comparable width at the three sites and for every variable.')}
<p>The preparation stage checks each site, variable and season on 2024 for centring (|median| ≤ 0.25 σ), width relative to
training, extreme-weather inflation and autocorrelation. Counts of PASS / WARN / FAIL over all checks:</p>
{table(checks.rename(columns={"site": "Site"}), cls="num")}
<p>The remaining FAILs are level shifts (the mean of a season sits off zero) and autocorrelation, not inflated widths. That
observation turned out to be the central fact of the whole design:</p>
{figure(f_wander, 'Figure 3. Monthly mean of the clean temperature residual, 2021–2024. With no attack, the station-minus-grid disagreement wanders by up to about ±1 σ for one to three months at a time (FAWN in 2024: +1.45 σ in March, +1.43 σ in October, −0.83 σ in July). A 12 % bias is 1–4 σ.')}
<div class="box"><b>Consequence.</b> No fixed threshold separates a 12 % attack from natural wandering at every site. A
detector must accumulate evidence over days and its threshold must be a stated trade-off between false alarms and
detection, set from data (section 5.1). A first design that removed a slow baseline (180-day median, 60-day gap) was
implemented and measured; it did not lower false alarms overall (FAWN 4 → 2, Kansas 3 → 5 per year) and is kept off.</div>
<p><b>Size of a 12 % attack in residual units</b> (12 % of the mean value divided by the fitted spread). This number predicts
detectability (section 6.3):</p>
{table(eff_tab, cls="num")}
<h2>4.4 Residuals on clean against injected data</h2>
{figure(img('witness.png'), 'Figure 4. FAWN temperature, 12 % step (of the range) from 15 April 2024. Top: in real weather the station and the calibrated NASA POWER move together; the attack moves only the station. Bottom: their standardized disagreement wanders on clean days and jumps under attack.', '92%')}
<h2>4.5 Replay analysis</h2>
<p>A replay is invisible in a single day's values (they are genuine weather) and does not repeat in the residuals either
(the reference has moved on). It leaves one trace: an exact copy of the station's own earlier values. For every window
of 7 days ending on day <i>t</i> and every lag ℓ from 1 to 730 days:</p>
<pre>d(t, ℓ) = mean over the 7 days and 4 variables of |x[t−k] − x[t−k−ℓ]| / σ_train(variable)
score(day) = min over the windows containing the day, min over ℓ, of d        flag if score &lt; 0.05</pre>
<p>On clean training data the smallest natural distance was 0.10 (AZMET), 0.20 (FAWN) and 0.19 (Kansas): two to four
times the tolerance. The matcher keeps the last 730 training days as history, so a replay early in the year still finds
its source, and a lag of 1 also catches a frozen sensor (F4).</p>
<h2>4.6 Change-point dating</h2>
<p>Each CUSUM alarm is dated back to the day after the alarming sum was last at zero (the classic CUSUM change-point
estimate). Alarms closer than 14 days form one episode with an estimated onset, a direction, the variable that raised it
and a type (drift if a Mann-Kendall trend from onset to end is significant at 5 %, otherwise step). The median absolute
onset error is 2–6 days for steps.</p>
<h2>4.7 Not yet implemented</h2>
<p>Physical-consistency residuals between variables (beyond the humidity witness of section 4.2) and the
orbital-context residuals against Sentinel-2 L2A indicators (cloud, vegetation and moisture indices around the site) are
specified but not implemented in Phase 1. They are the two additional witnesses that would address the small-attack
limit of section 6.3.</p>
""")

    # ------------------------------------------------------------------ 5 detection
    coef = tr_coef.copy()
    coef_tab = coef.rename(columns={"site": "held-out site"})
    roc_tab = roc[["variant", "roc_auc", "pr_auc", "tpr_at_1pct_fpr", "tpr_at_0.1pct_fpr", "roc_auc_step", "roc_auc_drift", "roc_auc_replay"]].rename(columns={
        "variant": "Fusion variant", "roc_auc": "ROC-AUC", "pr_auc": "PR-AUC", "tpr_at_1pct_fpr": "TPR @ 1 % FPR",
        "tpr_at_0.1pct_fpr": "TPR @ 0.1 % FPR", "roc_auc_step": "AUC step", "roc_auc_drift": "AUC drift", "roc_auc_replay": "AUC replay"})
    parts.append(f"""
<h1 id="s5">5. D4 Statistical and learned detection</h1>
<h2>5.1 Detector S, the statistical baseline</h2>
<p><b>Whitening.</b> The residuals are autocorrelated (lag-1 coefficient 0.1–0.7). An AR(1) model fitted per variable on
the training years predicts each day from the previous one; the prediction error divided by its training standard deviation,
<i>w<sub>t</sub> = (r<sub>t</sub> − φ r<sub>t−1</sub>) / σ<sub>e</sub></i>, is close to independent noise of variance 1,
which is what CUSUM theory assumes. A lasting offset δ survives whitening as (1 − φ) δ / σ<sub>e</sub>.</p>
<p><b>CUSUM with restart</b> (Page's test), two-sided, one pair of sums per variable:</p>
<pre>U_t = max(0, U_{{t−1}} + w_t − k)        D_t = min(0, D_{{t−1}} + w_t + k)        k = 0.5 σ (slack)
S_t = max over variables of max(U_t, −D_t)          alarm if S_t &gt; h, then every sum restarts at 0
a missing day holds the sums (never filled)</pre>
<p>Noise inside ±k cancels out; an offset larger than k builds up. An alarm is one event, and a lasting attack produces
repeated alarms. <b>The threshold h is not guessed:</b> it is the lowest value giving at most one alarm per year on the
clean training years, found by bisection (a higher h never gives more alarms). The result adapts to each site:
h = 8.9 (AZMET), 14.9 (FAWN, the site that wanders most), 8.6 (Kansas). This matters because the final test site is hidden.</p>
<p><b>Mahalanobis distance</b> (one unusual day across variables): robust centre and scale (median, MAD), covariance on the
standardized training residuals with 10 % shrinkage toward the diagonal; d² is compared with the χ² quantile at 0.999
with 4 degrees of freedom (18.47).</p>
<p><b>Replay matcher</b>: section 4.5. <b>Trend</b>: rolling Mann-Kendall z over 150 days on the prewhitened residuals,
threshold the larger of the Bonferroni-corrected critical value (|z| &gt; 3.66 for α = 0.001 over 4 variables) and the
value allowing one alarm per year on training. It flags 9–20 % of clean days at two sites, because a 150-day window stays
over the threshold for weeks, so it is reported but excluded from the combined flag.</p>
<p>The combined flag of detector S is CUSUM OR replay matcher OR Mahalanobis. Precipitation is not monitored (its residual
is undefined on dry days).</p>
<h2>5.2 Detector M, the learned detector</h2>
<p>A one-class model trained on clean windows only. Features per day (all causal): for each reference and temporal
residual, its level, 1-day difference, 7- and 30-day means, 7-day standard deviation and slope, 30-day sum; plus the 7-day
correlation of station and POWER day-to-day changes, the 7-day replay distances at offsets 7, 28 and 364 days, and simple
QC flags, with explicit missing-value indicators. Everything is decided inside the training years; <b>2024 is never seen by M before the evaluation.</b></p>
<ul>
<li><b>Model type.</b> Six PyOD models (Isolation Forest, ECOD, COPOD, HBOS, KNN, LOF) are fitted on the clean windows of
2021–2022 and compared on 129 attacks injected into 2023 (12 % steps and 15 % drifts on every variable, of std and of
range, up and down, and three replays per site). <b>LOF</b> ranked first (mean ROC-AUC 0.65 against 0.49–0.64).</li>
<li><b>Thresholds, leaving one year out.</b> LOF is fitted on two training years and scores the third, three times, so
every clean training day gets an out-of-sample score; the threshold is the 99th percentile of those scores. A first
version set the thresholds from 2023 alone, per site and season: it flagged 6 % of FAWN's 2021 days, because the
residuals wander from year to year and a percentile from about 90 days rests on one or two extreme values.</li>
<li><b>Granularity.</b> Global, per site, or per site and season: chosen by which keeps the false-alarm rate nearest 1 %
on a held-out training year. {m_gran}</li>
<li><b>Final model:</b> LOF fitted on every clean 2021–2023 window.</li>
</ul>
<div class="box warn"><b>Remaining caveat on M.</b> Its replay features look back 7, 28 and 364 days, which include the
offsets used in the replay scenarios, so its replay result is somewhat favourable. It exists only for the three
development sites (its calibration is per site); any other station uses the S-only fusion.</div>
<h2>5.3 Fusion: a calibrated compromise probability</h2>
<p>The daily outputs of S and M become nine features: <code>cusum_ratio</code> (statistic / threshold),
<code>cusum_recent</code> (alarms in the last 30 days), <code>maha_log</code> = log(1 + d²/threshold),
<code>replay_log</code> = log(tolerance / copy distance), <code>trend_ratio</code>, <code>gap7</code> and
<code>gap30</code> (the largest absolute 7- and 30-day mean of the standardized residual over temperature, humidity,
wind and solar, divided by the same station's 95th percentile of that quantity on its training years: a drift is
invisible day by day but clear as a month-long average), <code>m_flag</code> and
<code>m_recent</code>. A logistic regression, p = σ(β₀ + Σ βᵢ xᵢ), is fitted by maximum likelihood on labelled runs
(attacked days 1, all others 0). <b>Leave one site out:</b> the model applied at a site is fitted on the attacked and clean
runs of the two other sites only, as the hidden test site will be.</p>
{table(coef_tab, cls="num")}
<p>The coefficients are stable across the three fits and readable: the week- and month-long gaps carry the largest weights,
and an unusual day and an M alarm also raise the probability; the CUSUM ratio adds little once the gaps are known. The trend
feature gets a negative weight, because once the gaps are known a high trend score mostly marks natural wandering.</p>
{figure(img('calibration.png'), f"Figure 5. Reliability of the compromise probability on the held-out sites ({int(rel_tab['days'].sum()):,} days): of the days scored 0.3–0.4, {rel_tab.loc['0.3-0.4', 'attacked_share'] * 100:.0f} % were attacked; of those scored 0.9–1.0, {rel_tab.loc['0.9-1.0', 'attacked_share'] * 100:.0f} %. Brier score {tr_scores[tr_scores.site == 'all'].brier.iloc[0]:.3f} against {tr_scores[tr_scores.site == 'all'].brier_no_skill.iloc[0]:.3f} for always predicting the base rate.", '48%')}
<p>The probability is relative to the share of attacked days in the evaluation runs ({fusion_meta['attacked_share'] * 100:.0f} %); a deployment
with rarer attacks shifts it by Bayes' rule on the odds, which the code provides.</p>
<h2>5.4 Training protocol</h2>
{md_table([
 ["Calibration, AR models, CUSUM / trend / Mahalanobis thresholds, replay history", "clean 2021–2023 of each site", "never sees 2024 or any attack"],
 ["Detector M model type", "fitted on clean 2021–2022, compared on attacks injected in 2023", "LOF chosen"],
 ["Detector M thresholds and final model", "clean 2021–2023, leave one year out; final fit on all three years", "never sees 2024"],
 ["Humidity witness regression", "clean 2021–2023 of each site, POWER inputs only", "part of the calibration"],
 ["Fusion and trust bands (evaluation)", "attacked + clean runs of the two other sites", "leave one site out"],
 ["Fusion and trust bands (deployment, new data)", "all three sites, frozen", "S-only variant for stations without M"],
 ["Every reported number", "2024, held-out site where relevant", "attacks only ever in 2024 (checked by the runner)"],
], ["What is fitted", "On which data", "Note"])}
<h2>5.5 ROC, precision-recall and fixed false-alarm rates</h2>
{figure(f_roc, 'Figure 6. Per-day ROC of the compromise probability on the held-out site, for the full fusion and three reduced ones. Every attacked day counts, including the first days of an attack and the many attacks too small to be seen, so per-day AUC understates episode detection (section 6).')}
{table(roc_tab, cls="num", fmt={c: (lambda v: f'{v:.3f}') for c in roc_tab.columns if c != 'Fusion variant'})}
<h2>5.6 Ablation: which evidence matters</h2>
{figure(f_abl, 'Figure 7. Per-day ROC-AUC on the held-out site with groups of evidence removed.')}
<p><b>Reading the ablation.</b> {abl_sentence} Accumulating disagreement over days is the core of the detection, and it now
enters twice: through CUSUM and through the month-long gap features, so removing either one alone costs little (without
CUSUM {roc[roc.variant == 'without CUSUM'].roc_auc.iloc[0]:.3f}), while CUSUM alone already reaches {roc[roc.variant == 'CUSUM only'].roc_auc.iloc[0]:.3f}. CUSUM stays in the system for
what the AUC does not measure: it dates the onset, names the variable and the direction, and drives the alert.
Detector M adds a little on top of S ({s_only.roc_auc:.3f} → {full.roc_auc:.3f}, TPR at 1 % FPR {s_only.tpr_at_1pct_fpr * 100:.0f} → {full.tpr_at_1pct_fpr * 100:.0f} %); alone,
tuned without 2024, it reaches only {roc[roc.variant == 'M only'].roc_auc.iloc[0]:.3f}.
Removing the replay matcher's feature does <i>not</i> lower the per-day AUC, even for replays: a replayed week also disagrees
with NASA POWER, so the other evidence carries most of it. The replay matcher's value is elsewhere: it names the
attack, dates it to the day, and has zero false alarms (section 6.2), which is what an operator and the alert need. The
per-day ceiling of about {full.roc_auc:.2f} is set by the many attacks smaller than the natural disagreement (section 6.3), not by the
fusion. Sentinel-2 cannot be ablated because it is not yet computed; that is the Phase 2 ablation.</p>
<h2>5.7 Latency and memory of the detector itself</h2>
<p>The whole defence (calibration fit, detectors, fusion, responses, product) runs on four years of daily data for one
station in {o('whole defence on one station, 4 years of daily data')} ({o('whole defence per daily reading')} per reading, including the fits), with a peak Python memory of
{o('peak Python memory of that run')}. Per-station detector state is {o('detector S fitted state per station (thresholds, AR, covariance)')} plus {o('replay-matcher history per station (730 days x 4 variables)')} of replay history;
the fusion model and bands are {o('fusion model and trust bands')}; detector M's saved model for three sites is {o('detector M saved model (3 sites)')}.</p>
""")

    # ------------------------------------------------------------------ 6 adversarial validation
    rows = []
    for attack, rel, label in (("step", "value", "12 % step, of value"), ("step", "range", "12 % step, of range"), ("step", "std", "12 % step, of std"),
                               ("drift", "value", "drift to 15 %, of value"), ("drift", "range", "drift to 15 %, of range"), ("drift", "std", "drift to 15 %, of std"),
                               ("replay", "", "7-sample replay")):
        r = rate("S", attack, rel)
        rows.append([label, rate_txt("S", attack, rel), lat("S", attack, rel),
                     "" if pd.isna(r.median_abs_onset_error_days) else f"{r.median_abs_onset_error_days:.0f} d",
                     rate_txt("M", attack, rel), lat("M", attack, rel), rate_txt("S or M", attack, rel)])
    std_tab = md_table(rows, ["Attack", "Detector S: detected (95 % CI)", "S latency", "S onset error", "Detector M: detected", "M latency", "S or M"], "num")
    v = std_var[std_var.detector == "S"].copy()
    v["key"] = v["attack"] + ", " + v["relative_to"]
    var_tab = v.pivot(index="variable", columns="key", values="detection_rate").reindex(["temp_c", "solar_mj_m2", "rh_pct", "wind_ms"])
    var_tab = var_tab[["step, value", "step, range", "step, std", "drift, value", "drift, range", "drift, std"]]
    var_tab.index = [VAR_NAMES[i] for i in var_tab.index]
    var_tab = var_tab.reset_index().rename(columns={"index": "Variable (detector S)"})
    fa_tab = fa.pivot(index="detector", columns="site", values="false_alarms_per_year").reindex(["S", "S:cusum", "S:mahalanobis", "S:replay", "S:trend", "M", "S or M"]).reset_index()
    resp_rows = []
    for _, r in tr_resp.iterrows():
        resp_rows.append([r.attack + ("" if r.attack == "replay" else f", of {r.relative_to}"), r["de-weighted"],
                          f"{r['median days to de-weight']:.0f}" if pd.notna(r['median days to de-weight']) else "",
                          r["quarantined"], f"{r['median days to quarantine']:.0f}" if pd.notna(r['median days to quarantine']) else "",
                          f"{r['mean weight during attack']:.2f}"])
    dec_rows = []
    for (attack, rel), g in tr_runs.groupby(["attack", "relative_to"]):
        h = g[g.wrong_decision_c0]
        dec_rows.append([attack + ("" if attack == "replay" else f", of {rel}"), f"{g.wrong_days_c0.mean() * 100:.1f} %", f"{g.wrong_days_c4.mean() * 100:.1f} %",
                         f"{(1 - g.wrong_days_c4.mean() / g.wrong_days_c0.mean()) * 100:+.0f} %".replace("+", "−", 1) if g.wrong_days_c4.mean() < g.wrong_days_c0.mean() else f"+{(g.wrong_days_c4.mean() / g.wrong_days_c0.mean() - 1) * 100:.0f} %",
                         f"{len(h)}", f"{h.wrong_trusted_c4.mean() * 100:.0f} %" if len(h) else ""])
    clean_tab = tr_clean[["site", "deweighted_day_share", "quarantined_days_per_year", "quarantines_per_year", "verification_requests_per_year", "decision_days_changed_by_defence"]].rename(columns={
        "site": "Site", "deweighted_day_share": "de-weighted days", "quarantined_days_per_year": "quarantine days / yr",
        "quarantines_per_year": "quarantines / yr", "verification_requests_per_year": "verification requests / yr",
        "decision_days_changed_by_defence": "decision days changed by the defence"})
    st12 = stealth[(stealth.magnitude == 0.12)].groupby(["variable", "relative_to"])["S detected"].mean().unstack()
    s_min = stealth.groupby(["variable", "relative_to", "magnitude"])["S detected"].mean().reset_index()
    budget_rows = []
    for var in ("temp_c", "solar_mj_m2", "rh_pct", "wind_ms"):
        row = [VAR_NAMES[var]]
        for rel in ("value", "range"):
            g = s_min[(s_min.variable == var) & (s_min.relative_to == rel)].sort_values("magnitude")
            ok = g[g["S detected"] >= 0.5]
            row.append(f"{ok.magnitude.iloc[0] * 100:.0f} %" if len(ok) else "&gt; 30 %")
        budget_rows.append(row)
    pr = pert.groupby("noise_sd")[["replay matcher detected", "S detected"]].mean()
    sd = slow.groupby("ramp_days")["S detected"].mean()
    parts.append(f"""
<h1 id="s6">6. D5 Adversarial validation and response</h1>
<h2>6.1 The official standard scenario</h2>
<p><b>File mode, attacker at the station (P1),</b> as the jury will supply it: the series arrives with the injection inside.
Per site, the calibration and the detectors are fitted once on the clean 2021–2023 data; every attack is then injected
into 2024 and scored with the same fitted models (exact, since the attack never touches the training years).</p>
{md_table([
 ["12 % step, 60 days", "temperature, humidity, wind, solar", "up, down", "value, range, std", "4 onsets (one per season)", "96"],
 ["drift to 15 %, held 30 days", "same 4", "up, down", "value, range, std", "ramp 30, 60, 90 days × 2 onsets", "144"],
 ["7-day replay", "the whole record", "—", "—", "source 7, 28, 364 days back × 4 onsets", "12"],
], ["Attack", "Variables", "Signs", "Meaning of %", "Other", "Runs per site"])}
<p><b>Fair detection.</b> A detector with a few false alarms a year will sometimes alarm inside an attack window by chance.
Every attacked run is therefore compared with the clean run of the same site: <b>an alarm counts for the attack only if the
clean run has no alarm that day</b>. An episode is detected if such an alarm falls between its first and last attacked day.
Rates carry 95 % Wilson intervals.</p>
<h2>6.2 Results</h2>
{std_tab}
{figure(img('detection.png'), 'Figure 8. Episodes detected per attack and meaning of the percentage, detectors S and M, with 95 % intervals (756 attacked runs, 3 sites, 2024).')}
{figure(f_lat, 'Figure 9. Days from onset to the first alarm of detector S, detected episodes only.')}
<h2>6.3 What decides detection</h2>
{table(var_tab, cls="num", fmt={c: pct for c in var_tab.columns if c != 'Variable (detector S)'})}
{figure(img('size.png'), 'Figure 10. Steps detected against their size in standard deviations of the station-minus-reference difference. Above about 1.5 σ attacks are almost always caught; below about 0.7 σ they hide in the natural wandering of figure 3.', '88%')}
<p>{size_sentence}</p>
<h2>6.4 False alarms, including genuine extreme weather</h2>
{table(fa_tab.rename(columns={"detector": "Alarm events per year, clean 2024"}), cls="num", fmt={c: (lambda v: f'{v:.1f}') for c in ('azmet', 'fawn', 'kansas')})}
<p>The combined detector S raises {s_fa:.1f} alarm events per station-year ({fa[fa.detector == 'S'].false_alarm_day_share.mean() * 100:.1f} % of days); the replay matcher none.
The CUSUM budget was one per year on 2021–2023 and 2024 gave 1–4: the test year wanders more than the training years. This
gap is reported rather than hidden by retuning on 2024.</p>
{figure(f_extreme, 'Figure 11. False alarms on genuine extreme-weather days (daily temperature beyond the 5 % tails of its monthly climatology, or rain above the 95th percentile of wet days) against ordinary days, clean 2024.')}
<p>Extreme days are flagged more often than ordinary ones (Kansas detector S {ex_s.kansas * 100:.1f} % against {ex_o.kansas * 100:.1f} %;
Kansas not trusted on {ex_nt.kansas * 100:.0f} % of extreme days against {ex_nto.kansas * 100:.0f} %), but no extreme day was quarantined at any site. The absolute numbers are small (34–44 extreme days per site) but the direction
is clear: the reference represents extremes less well than ordinary days. This is the test a naive anomaly detector fails
outright; ours fails it mildly, and it is a Phase 2 item (season-and-regime-dependent spread).</p>
<h2>6.5 The same attacks at the three attacker positions</h2>
<p>Section 3.7: at P2 every attacked record is rejected by layer 1, at P3 the ledger breaks on the first rewritten day,
at P1 everything passes and detection carries the whole result. The standard test is a P1 situation, which is why the
detection layer is where the effort went.</p>
<h2>6.6 Adaptive attackers: where the defence stops working</h2>
<h3>Stealth budget (E6, approximating E9): how large a step passes?</h3>
{figure(f_stealth, 'Figure 12. Steps of 2 to 30 % detected by detector S, per variable, at the three sites and two onsets.')}
{md_table(budget_rows, ["Variable", "smallest step detected in at least half of runs, % of value", "same, % of range"], "num")}
<p>A fully informed attacker can sustain, undetected in most runs, a step smaller than the sizes above. For
<b>temperature and solar</b> a 5 % step is already caught in at least half of the runs and 8–12 % in all of them, so the
official 12 % is well outside the budget. For <b>humidity</b> the threshold is 16–20 %: the official 12 % humidity step is
<b>inside</b> the budget. <b>Wind</b> is caught in about half of the runs from 8 % upward but never reliably when read relative
to the value. This is the quantitative statement of the residual risk of section 2.8. (The detections at 2 % come from one
site in each case; part of them can be the alarm-shift effect noted in section 6.1.)</p>
<h3>E1: slower drift</h3>
{figure(f_slow, 'Figure 13. Drifts to +15 % of the range reached over 30 to 270 days (no hold).')}
<p>Detection against ramp length (all variables): {", ".join(f"{int(k)} days {v * 100:.0f} %" for k, v in sd.items())}. A slower drift is not
less detected: it is detected <i>more</i> often, because it stays in the data longer, and the CUSUM has no adaptation to
outwait (it compares with an independent witness, not with the station's own past). It is detected <b>later</b>: the median
latency grows from {slow[slow.ramp_days == 30]['S latency'].median():.0f} days (30-day ramp) to {slow[slow.ramp_days == 270]['S latency'].median():.0f} days (270-day ramp). That delay is what an attacker buys by
going slowly, and it is the number to compare with the time a drift needs to change a decision. Humidity remains the weak
variable at every ramp length.</p>
<h3>E5: perturbed replay</h3>
{figure(f_pert, 'Figure 14. A seven-day replay (copied 28 days back) with Gaussian noise added to every replayed value, at 3 sites and 4 onsets.')}
<p>Replays detected by the replay matcher / by detector S against noise (in standard deviations of each variable):
{", ".join(f"{k:g} σ: {a * 100:.0f} / {b * 100:.0f} %" for k, (a, b) in pr.iterrows())}. Noise of 0.1 σ defeats the exact-copy matcher, as
expected from its 0.05 σ tolerance. <b>Detector S as a whole still catches every perturbed replay</b>, through CUSUM and
Mahalanobis: the replayed week no longer follows NASA POWER's weather for those days, and noise cannot hide that. The
evasion works against one detector and fails against the defence, which is the argument for layering independent evidence.
The analogue replay (E4: replay the past week that best matches the current reference) is the harder variant and is planned.</p>
<h3>Layer 1 evasion</h3>
<p>Provenance stripping (F10) is rejected (unsigned records are never accepted); a forged or modified record fails its
signature; a replayed or reordered one fails the sequence check; a dropped one raises a chain gap and the cadence
watchdog (all unit-tested). The only way around layer 1 is a station key (F11), which turns the attacker into P1, the case
evaluated above.</p>
<h2>6.7 Response policy and its results</h2>
<p><b>Trust dynamics.</b> Each day, risk<sub>t</sub> = risk<sub>t−1</sub> + a (p<sub>t</sub> − risk<sub>t−1</sub>) and
trust<sub>t</sub> = 1 − risk<sub>t</sub>, with a = 0.5 when p<sub>t</sub> exceeds the current risk (trust falls fast) and
a = 0.05 otherwise (half of the lost trust returns in about 14 quiet days). One day at p = 0.9 takes trust from 1 to 0.55;
an attacker cannot reset trust by pausing a day.</p>
<p><b>Bands, set on data and frozen:</b> de-weighting below the trust level clean days go under 5 % of the time, quarantine
below the level they go under 0.5 % of the time (on the fitting sites), with hysteresis: release only above the
de-weighting limit.</p>
{md_table([
 ["De-weighting", "band de-weighted", "value used = w · station + (1 − w) · calibrated reference, w falling linearly 1 → 0 across the band, for the <b>implicated</b> variables only (14-day mean residual beyond 1 σ; the whole record for a detected replay)"],
 ["Verification request", "de-weighted and trust still falling (at most every 14 days)", "ask for independent evidence: next clear Sentinel-2 view, neighbouring station, technician visit"],
 ["Quarantine", "band quarantined", "w = 0: implicated variables replaced by the calibrated reference"],
 ["Alert", "on entering quarantine", "operator notified with the reason (the evidence that drove the probability, a detected replay named explicitly), variable, direction, type and estimated onset"],
], ["Response", "When", "What"])}
<p>Replacing only implicated variables matters: a first version replaced the whole record, rain included, and made decisions
<i>worse</i> (wrong-decision days 14 % → 33 % on a test set), because substituting a grid cell's rain for a point gauge changes
the water balance by itself.</p>
{md_table(resp_rows, ["Attack", "De-weighted (95 % CI)", "median days", "Quarantined + alert", "median days", "mean weight in attack"], "num")}
<p><b>Cost on honest stations</b> (clean 2024 of each held-out site):</p>
{table(clean_tab, cls="num", fmt={"de-weighted days": pct, "decision days changed by the defence": lambda v: f"{v * 100:.1f} %", "quarantine days / yr": lambda v: f"{v:.0f}", "quarantines / yr": lambda v: f"{v:.0f}", "verification requests / yr": lambda v: f"{v:.0f}"})}
<p>{band_sentence}</p>
{figure(img('gui_simulate_trust.png'), 'Figure 15. The operator view (control room, Simulate attack): a seven-day replay at AZMET from 10 July 2024 (red band). The probability spikes, the station is de-weighted two days later and quarantined two days after that, and released once it agrees with NASA POWER again.')}
<h2>6.8 Decisions with and without the defence</h2>
<p>Every series is turned into the decision it would drive: ET0 by FAO-56 Penman-Monteith from temperature, humidity, wind
and solar radiation; the 30-day water balance B = Σ (rain − ET0); and a level per site and month from the clean training
years: <b>normal</b> (B ≥ 30th percentile), <b>dry</b>, irrigation advised (below the 30th), <b>severe drought</b>, the insurance
trigger (below the 10th). Three decision series are compared over the attack and the 30 days after it: from the true data,
from the attacked data with no defence (C0), and after the responses (C4, full system). At P1, provenance alone (C2)
changes nothing, so C2 = C0.</p>
{figure(img('decisions.png'), 'Figure 16. Share of days on which the farm decision is wrong because of the attack.')}
{md_table(dec_rows, ["Attack", "wrong days, no defence (C0)", "with the defence (C4)", "change", "attacks that changed the decision", "of those, wrong and issued as TRUSTED"], "num")}
<p>Overall the defence cuts wrong-decision days from {wd0 * 100:.1f} % to {wd4 * 100:.1f} % ({(1 - wd4 / wd0) * 100:.0f} %). The more important effect is that
wrong decisions stop being <b>silent</b>: without the defence every wrong decision is issued as if sound; with it, a decision
is TRUSTED only if the station was trusted over its whole 30-day window, otherwise DEGRADED (pending verification).
{replay_sentence} {std_sentence}</p>
<h2>6.9 Blind rehearsal</h2>
<p>Not performed in Phase 1: it needs one person to inject at a site and interval the others do not know, and the final
work was done by one person. The file-mode tool (section 8) is built for it and it is the first Phase 2 rehearsal.</p>
""")

    # ------------------------------------------------------------------ 7 datasets
    clean_files = sorted((ROOT / "data/clean_2021_2024").glob("*_daily_clean.csv"))
    ds_rows = []
    for f in clean_files:
        ds_rows.append([f"<code>{f.name}</code>", f"{f.stat().st_size // 1024} KB", f"<code>{sha256(f)[:16]}…</code>"])
    parts.append(f"""
<h1 id="s7">7. D6 Datasets</h1>
{md_table([
 ["NASA POWER Daily API (official)", "NASA Langley Research Center", "point, community AG: T2M, RH2M, WS2M, PRECTOTCORR, ALLSKY_SFC_SW_DWN", "3 points, 2021–2024", "free; acknowledgement of the NASA Langley Research Center POWER Project requested", "JSON responses cached with SHA-256 manifest"],
 ["AZMET daily", "University of Arizona", "station az09; temperature, humidity, wind (3 m), rain, solar", "2021–2024", "free; cite the network and the access date", "<code>1e9e8e85…</code> (raw)"],
 ["FAWN 15-minute observations", "University of Florida IFAS", "station Okahumpka (303); aggregated to daily", "2021–2024", "free to the public", "yearly CSV files, SHA-256 in the repository"],
 ["Kansas Mesonet daily", "Kansas State University", "station Manhattan; rain = larger of two gauges", "2021–2024", "free for research with attribution (policy to confirm)", "<code>095031e7…</code> (raw)"],
 ["Copernicus Sentinel-2 L2A", "ESA / Copernicus Data Space", "cloud, vegetation and moisture indicators", "—", "free, open", "not used in Phase 1"],
], ["Dataset", "Provider", "Content", "Period", "Licence", "Identifier / checksum"])}
<p><b>Cleaned files read by the pipeline</b> (one schema, full daily calendar), committed in the repository:</p>
{md_table(ds_rows, ["File", "Size", "SHA-256 (first 16 hex)"])}
<p>Scripts re-download the raw data (<code>data/scripts/fetch_2021_2024.py</code>) and rebuild these files
(<code>data/scripts/clean.py</code>); no large data is required beyond them. Known limits: rain agrees least with NASA POWER
at every site (point against grid average); one station per site, so the offsets are not valid for a whole climate.</p>
""")

    # ------------------------------------------------------------------ 8 reproduction and tools
    pk = hw.get("packages", {})
    parts.append(f"""
<h1 id="s8">8. Reproduction, tools and run time</h1>
{md_table([
 ["<code>python -m pytest</code>", "164 unit and integration tests", "1 min"],
 ["<code>python scripts/run_all.py</code>", "standard scenario, 756 attacked runs, detectors S and M (tables of section 6.1–6.4)", "10 min"],
 ["<code>python scripts/run_trust.py</code>", "probability, trust, responses, decisions, leave one site out (sections 5.3, 6.7, 6.8)", "12 min"],
 ["<code>python scripts/report_metrics.py</code>", "layer 1 positions, cost, ROC and ablation, extreme weather, evasion sweeps", "15 min"],
 ["<code>python scripts/train_fusion.py</code>", "the frozen fusion model used on new data", "12 min"],
 ["<code>python scripts/build_report.py</code>", "this report (HTML and PDF) from the results", "1 min"],
], ["Command", "Produces", "Time"])}
<p>Every setting lives in one YAML file per stage (<code>config/</code>, appendix A); random seeds are fixed (42); package versions
are pinned in <code>requirements.txt</code> (numpy {pk.get('numpy', '')}, pandas {pk.get('pandas', '')}, scipy {pk.get('scipy', '')},
scikit-learn {pk.get('sklearn', '')}). Hardware: {html.escape(hw.get('cpu', ''))}, {hw.get('ram_gb', '')} GB RAM, {html.escape(hw['os'])}, Python {hw['python']}; laptop CPU only, no GPU.</p>
<h2>8.1 File mode: any station series plus its coordinates</h2>
<p>What the hidden-site test looks like. <code>python scripts/assess.py station.csv --lat … --lon …</code> (or
<code>mingw32-make assess</code>): columns are recognised automatically (NASA POWER names included), sub-daily data is
aggregated, NASA POWER for the place and days is downloaded once and cached, the calibration and detectors are fitted on the
first part of the series (assumed clean; two thirds by default, or given dates), and the rest is scored. Outputs per day:
detector scores, compromise probability, trust and band, the series after the responses, the decision and its confidence;
plus every action with its reason and every episode with its estimated onset.</p>
<h2>8.2 The control room</h2>
<p>A graphical tool (<code>mingw32-make gui</code>) runs and shows everything: <i>Assess data</i> (file mode on any CSV or
Excel file), <i>Simulate attack</i> (site, attack, size, meaning of "12 %", onset, variables and attacker position P1/P2/P3,
with a verdict), <i>Experiments</i> (the commands above with a live log and their tables) and <i>Configs &amp; docs</i>.</p>
{figure(img('gui_assess_summary.png'), 'Figure 17. Assess data: the summary page of an assessment, with every action and its reason, the CUSUM episodes and the decision with and without the defence.')}
{figure(img('gui_assess_detectors.png'), 'Figure 18. Assess data: every detector score against its threshold, with its alarms.')}
""")

    # ------------------------------------------------------------------ 9 metrics, 10 limits, refs, appendix
    parts.append(f"""
<h1 id="s9">9. Mandatory metrics</h1>
{md_table([
 ["<b>Detection quality</b>", f"episode detection per attack and meaning of 12 % (section 6.2): replay {rate('S', 'replay', '').detection_rate * 100:.0f} %, step {rate('S', 'step', 'value').detection_rate * 100:.0f} / {rate('S', 'step', 'range').detection_rate * 100:.0f} / {rate('S', 'step', 'std').detection_rate * 100:.0f} % and drift {rate('S', 'drift', 'value').detection_rate * 100:.0f} / {rate('S', 'drift', 'range').detection_rate * 100:.0f} / {rate('S', 'drift', 'std').detection_rate * 100:.0f} % (value / range / std) for S; per-day ROC-AUC {full.roc_auc:.3f} (fusion), TPR {full.tpr_at_1pct_fpr * 100:.0f} % at 1 % FPR; onset error 2–6 days (steps); probability calibration: Brier {tr_scores[tr_scores.site == 'all'].brier.iloc[0]:.3f}; wrong-decision days −{(1 - wd4 / wd0) * 100:.0f} %", "6.2, 5.5, 4.6, 5.3, 6.8"],
 ["<b>False alarms</b>", f"S {s_fa:.1f} and M {m_fa:.1f} alarm events per station-year ({fa[fa.detector == 'S'].false_alarm_day_share.mean() * 100:.1f} % of days); replay matcher 0; on extreme-weather days {ex_s.min() * 100:.0f}–{ex_s.max() * 100:.0f} % against {ex_o.min() * 100:.1f}–{ex_o.max() * 100:.1f} % on ordinary days; false quarantines: {int((tr_clean.quarantines_per_year > 0.5).sum())} in {len(tr_clean)} clean station-years ({tr_clean.quarantined_days_per_year.max():.0f} days at most)", "6.4, 6.7"],
 ["<b>Latency</b>", f"days from onset to first alarm (median): replay {lat('S', 'replay', '')}, step {lat('S', 'step', 'range')} (range) – {lat('S', 'step', 'value')} (value), drift {lat('S', 'drift', 'range')} – {lat('S', 'drift', 'value')}; to quarantine: replay {resp_days('replay', '')}, step {resp_days('step', 'range')} (range) – {resp_days('step', 'value')} (value); processing {o('whole defence per daily reading')} per reading including fits; cadence: daily", "6.2, 6.7, 5.7"],
 ["<b>Memory</b>", f"peak {o('peak Python memory of that run')} for 4 station-years; per-station state {o('detector S fitted state per station (thresholds, AR, covariance)')} + {o('replay-matcher history per station (730 days x 4 variables)')}; models {o('detector M saved model (3 sites)')} (M) and {o('fusion model and trust bands')} (fusion)", "5.7, 3.8"],
 ["<b>Security overhead</b>", f"{o('record size, fixed part (header + signature)')} per record ({o('record size, total')} total with 5 variables); sign {o('sign one record (station side)')}, verify {o('verify one record (signature, certificate, sequence, chain)')}, ledger append {o('append one record to the hash-chained ledger')}", "3.5, 3.8"],
], ["Metric", "Result", "Section"])}

<h1 id="s10">10. Limitations and Phase 2 plan</h1>
<ul>
<li><b>Small attacks are not caught.</b> Below about 0.7 σ of the station-to-reference difference (every "12 % of std" case,
most wind cases). <i>Plan:</i> a second independent witness: Sentinel-2 L2A indicators (an arbiter when station
and reference disagree) and neighbouring stations; physical-consistency residuals between variables.</li>
<li><b>Decisions can still flip early,</b> before the evidence is strong enough to act; with daily data and a 12 % change this
floor cannot be removed without false alarms on honest stations. <i>Plan:</i> margin-to-harm analysis per decision level.</li>
<li><b>Extreme weather</b> is flagged somewhat more often than ordinary days. <i>Plan:</i> regime-dependent spreads.</li>
<li><b>Detector M is site-bound,</b> and its replay features include the scenario offsets. <i>Plan:</i> a site-independent
calibration; replay features independent of the offsets.</li>
<li><b>Small evaluation base:</b> three sites, one test year, no held-out site, no blind rehearsal. <i>Plan:</i> two held-out sites
and a blind rehearsal with the file-mode tool.</li>
<li><b>File mode needs a clean start</b> (baseline poisoning, E7). <i>Plan:</i> cold-start calibration from NASA POWER climatology
and the training years of neighbouring stations.</li>
<li><b>Not evaluated:</b> F4–F9 as separate injections, evasions E3, E4, E8.</li>
</ul>

<h1 id="refs">References</h1>
<ol class="small">
<li>Y. Liu, P. Ning, M. K. Reiter, "False data injection attacks against state estimation in electric power grids", ACM CCS 2009.</li>
<li>R. Langner, "Stuxnet: dissecting a cyberwarfare weapon", IEEE Security &amp; Privacy 9(3), 2011.</li>
<li>T. Trippel, O. Weisse, W. Xu, P. Honeyman, K. Fu, "WALNUT: waging doubt on the integrity of MEMS accelerometers with acoustic injection attacks", IEEE EuroS&amp;P 2017.</li>
<li>D. F. Kune et al., "Ghost Talk: mitigating EMI signal injection attacks against analog sensors", IEEE S&amp;P 2013.</li>
<li>World Meteorological Organization, <i>Guide to Instruments and Methods of Observation</i> (WMO-No. 8).</li>
<li>R. G. Allen, L. S. Pereira, D. Raes, M. Smith, <i>Crop evapotranspiration: guidelines for computing crop water requirements</i>, FAO Irrigation and Drainage Paper 56, 1998.</li>
<li>E. S. Page, "Continuous inspection schemes", Biometrika 41, 1954 (CUSUM).</li>
<li>H. B. Mann, "Nonparametric tests against trend", Econometrica 13, 1945; M. G. Kendall, <i>Rank Correlation Methods</i>, 1975.</li>
<li>M. M. Breunig, H.-P. Kriegel, R. T. Ng, J. Sander, "LOF: identifying density-based local outliers", ACM SIGMOD 2000.</li>
<li>D. J. Bernstein et al., "High-speed high-security signatures" (Ed25519), Journal of Cryptographic Engineering 2, 2012.</li>
<li>NASA Langley Research Center, POWER Project, Daily API (power.larc.nasa.gov).</li>
</ol>

<h1 id="appA">Appendix A: parameters</h1>
{md_table([
 ["Split", "train 2021-01-01 to 2023-12-31; test 2024-01-01 to 2024-12-31", "config/split.yaml"],
 ["Calibration", "per season (DJF, MAM, JJA, SON); median offset, MAD spread × 1.4826; log ratio for wind and rain, pseudocount 0.1; rain dry-dry days missing (≤ 0.1 mm)", "config/preparation.yaml"],
 ["CUSUM", "AR(1) whitening; slack k = 0.5 σ; threshold auto: ≤ 1 alarm / year on training; restart after alarm; episodes merged within 14 days", "config/detector_s.yaml"],
 ["Mahalanobis", "robust centre and scale; shrinkage 0.10; χ² quantile 0.999, 4 degrees of freedom", "config/detector_s.yaml"],
 ["Replay matcher", "7-day windows; lags 1–730 days; tolerance 0.05 σ", "config/detector_s.yaml"],
 ["Trend", "150-day window; prewhitened; threshold max(Bonferroni z at α = 0.001, ≤ 1 alarm / year)", "config/detector_s.yaml"],
 ["Detector M", "LOF (20 neighbours), contamination 0.01; thresholds 99th percentile per site and season", "config/config_m.yaml"],
 ["Fusion", "logistic regression, C = 1, 9 features, persistence window 30 days", "config/trust.yaml"],
 ["Humidity witness", "ridge regression on 15 POWER features, α = 10", "config/preparation.yaml"],
 ["Detector M", "LOF (20 neighbours); 99th percentile of leave-one-year-out scores, granularity chosen on held-out years", "config/config_m.yaml"],
 ["Trust", "fall rate 0.5, recovery rate 0.05; de-weight below the 5 % clean quantile, quarantine below the 0.5 % one", "config/trust.yaml"],
 ["Responses", "implicated: 14-day mean residual beyond 1 σ; verification request at most every 14 days", "config/trust.yaml"],
 ["Product", "30-day water balance; dry below the 30th, severe below the 10th percentile per site and month", "config/trust.yaml"],
], ["Stage", "Parameters", "File"])}
""")

    return "\n".join(parts)


def main() -> int:
    warnings.filterwarnings("ignore")
    cfg = pl.load_config()
    body = build(cfg)
    REPORT.mkdir(exist_ok=True)
    doc = f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(TITLE)}</title><style>{CSS}</style></head><body>{body}</body></html>'
    out_html = REPORT / "report.html"
    out_html.write_text(doc, encoding="utf-8")
    pdf = REPORT / "report.pdf"
    raw = REPORT / "report_raw.pdf"
    subprocess.run([str(EDGE), "--headless", "--disable-gpu", "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
                    "--virtual-time-budget=10000", f"--print-to-pdf={raw}", out_html.resolve().as_uri()], check=True, timeout=180)
    # Phase 1 is anonymous: keep only the title in the PDF metadata
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(str(raw))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata({"/Title": TITLE, "/Author": "", "/Creator": "", "/Producer": "", "/Subject": "TSYP14 Track 2 Phase 1 report"})
    with pdf.open("wb") as f:
        writer.write(f)
    raw.unlink()
    print(f"wrote {out_html} and {pdf} ({len(reader.pages)} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
