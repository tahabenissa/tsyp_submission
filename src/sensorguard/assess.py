"""File mode: any station series + its coordinates in, everything the defence concludes out.

This is what runs on data the system has never seen (the jury's hidden site):

    station series ─► NASA POWER for the same place and days (downloaded and cached, or a file)
                   ─► calibration on the fit period ─► standardized residuals
                   ─► detector S (CUSUM, replay matcher, Mahalanobis, trend) [+ detector M at known sites]
                   ─► compromise probability ─► trust ─► band ─► responses
                   ─► series used downstream ─► 30-day water balance ─► decision level

Nothing depends on a particular station.  The calibration and detector S are
fitted on the fit period of the given series itself (assumed clean, as for any
new station that is enrolled), and the scoring period is analysed with them.
The fusion model and trust bands are the frozen ones trained on the three
development sites (scripts/train_fusion.py).  Detector M only exists for the
three development sites; elsewhere the "S only" fusion is used.

Used by the GUI (tools/sensorguard_gui.py) and the command line (scripts/assess.py).
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sensorguard import pipeline as pl
from sensorguard.detect import fusion, statistical, trust_score
from sensorguard.processing.detector_s.base import load_detector_config
from sensorguard.product import water_balance as wb
from sensorguard.response import policy

VARIABLES = ["temp_c", "rh_pct", "wind_ms", "precip_mm", "solar_mj_m2"]
MONITORED = ["temp_c", "rh_pct", "wind_ms", "solar_mj_m2"]
FUSION_FILE = pl.REPO_ROOT / "results" / "models_fusion" / "fusion.joblib"

# Column names recognised automatically (lower case, compared without spaces,
# dashes or underscores).  NASA POWER names are included, so a POWER export
# can be assessed directly.
ALIASES = {
    "temp_c": ["temp_c", "t2m", "temperature", "temp", "tavg", "tmean", "air_temp", "temperature_c", "tair"],
    "rh_pct": ["rh_pct", "rh2m", "humidity", "humidity_pct", "rh", "relative_humidity", "relhum"],
    "wind_ms": ["wind_ms", "ws2m", "wind", "wind_speed", "windspeed", "ws", "wind_m_s"],
    "precip_mm": ["precip_mm", "prectotcorr", "rain", "rain_mm", "precip", "precipitation", "prcp", "rainfall"],
    "solar_mj_m2": ["solar_mj_m2", "allsky_sfc_sw_dwn", "solar", "solar_mj_m2_day", "srad", "radiation", "rs"],
}
DATE_ALIASES = ["date", "day", "time", "datetime", "timestamp"]


def _norm(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def guess_columns(columns) -> dict[str, str | None]:
    """{our variable: the column that holds it, or None} from the column names."""
    lookup = {_norm(c): c for c in columns}
    out = {}
    for var, names in ALIASES.items():
        out[var] = next((lookup[_norm(n)] for n in names if _norm(n) in lookup), None)
    return out


def guess_date_column(columns) -> str | None:
    lookup = {_norm(c): c for c in columns}
    return next((lookup[n] for n in DATE_ALIASES if n in lookup), None)


def read_table(path: str | Path) -> pd.DataFrame:
    """Read a CSV (or Excel) file as it is, to show its columns before mapping."""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path)
    return pd.read_csv(path)


def to_daily(raw: pd.DataFrame, mapping: dict[str, str | None], date_column: str) -> pd.DataFrame:
    """Our schema: one row per calendar day, the five variables, NaN where missing.

    Sub-daily data is averaged per day (rain is summed).  Fill codes such as
    -999 become NaN.
    """
    df = raw.copy()
    df[date_column] = pd.to_datetime(df[date_column], errors="coerce")
    df = df.dropna(subset=[date_column]).set_index(date_column).sort_index()
    out = pd.DataFrame(index=df.index)
    for var in VARIABLES:
        col = mapping.get(var)
        out[var] = pd.to_numeric(df[col], errors="coerce") if col else np.nan
    out = out.mask(out <= -99)                                      # fill codes
    if out.index.normalize().has_duplicates:                        # sub-daily data
        agg = {v: ("sum" if v == "precip_mm" else "mean") for v in VARIABLES}
        out = out.groupby(out.index.normalize()).agg(agg)
    out.index = out.index.normalize()
    days = pd.date_range(out.index.min(), out.index.max(), freq="D", name="date")
    return out.reindex(days)


def reference_for(lat: float, lon: float, start, end, power_file: str | Path | None = None,
                  offline: bool = False) -> pd.DataFrame:
    """NASA POWER for the place and days, in our schema (downloaded once, then read from the cache)."""
    if power_file:
        raw = read_table(power_file)
        return to_daily(raw, guess_columns(raw.columns), guess_date_column(raw.columns) or raw.columns[0])
    from sensorguard import schema
    from sensorguard.data.power import fetch_power_daily
    p = fetch_power_daily(lat, lon, pd.Timestamp(start).strftime("%Y-%m-%d"), pd.Timestamp(end).strftime("%Y-%m-%d"),
                          offline=offline)
    p = p.rename(columns={schema.TEMP: "temp_c", schema.HUMIDITY: "rh_pct", schema.WIND: "wind_ms",
                          schema.RAIN: "precip_mm", schema.SOLAR: "solar_mj_m2"})
    p.index = pd.to_datetime(p.index).normalize()
    p.index.name = "date"
    return p[VARIABLES]


def default_periods(index: pd.DatetimeIndex) -> dict[str, str]:
    """Fit on the first two thirds (at least 180 days), score the rest."""
    n = len(index)
    cut = max(180, int(n * 2 / 3))
    cut = min(cut, n - 30)
    return {"train_start": str(index[0].date()), "train_end": str(index[cut - 1].date()),
            "validation_start": str(index[cut].date()), "validation_end": str(index[-1].date())}


# --------------------------------------------------------------------------- result


@dataclass
class Assessment:
    station: pd.DataFrame          # as given (our schema)
    reference: pd.DataFrame        # NASA POWER
    reference_calibrated: pd.DataFrame
    coords: tuple[float, float]
    periods: dict[str, str]
    variables: list[str]           # variables actually analysed
    residuals: pd.DataFrame        # standardized reference residuals, every day
    detectors: pd.DataFrame        # scoring period: <name>_score, <name>_flag, flag
    thresholds: dict[str, float]
    episodes: list[dict]           # CUSUM episodes: estimated onset, type, variable, direction
    features: pd.DataFrame
    probability: pd.Series
    trust: pd.Series
    band: pd.Series
    bands: trust_score.Bands
    weight: pd.Series
    implicated: pd.DataFrame
    used: pd.DataFrame             # series used downstream after the responses
    actions: pd.DataFrame
    balance: pd.DataFrame          # water balance as received and after the defence
    decisions: pd.DataFrame        # decision level as received, after the defence, product confidence
    fusion_variant: str
    seconds: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    labels: pd.DataFrame | None = None   # only when the attack is known (simulation)

    def summary(self) -> dict[str, Any]:
        s = self.periods
        days = self.band
        q = self.actions[self.actions["action"] == "quarantine"] if len(self.actions) else self.actions
        return {
            "scored": f"{s['validation_start']} to {s['validation_end']} ({len(days)} days)",
            "fitted on": f"{s['train_start']} to {s['train_end']}",
            "variables": ", ".join(self.variables),
            "fusion": self.fusion_variant,
            "lowest trust": f"{self.trust.min():.2f} on {self.trust.idxmin().date()}" if len(self.trust) else "-",
            "days trusted / de-weighted / quarantined": " / ".join(
                str(int((days == b).sum())) for b in (trust_score.TRUSTED, trust_score.DEWEIGHTED, trust_score.QUARANTINED)),
            "quarantines": int(len(q)),
            "CUSUM episodes": len(self.episodes),
            "replay days flagged": int(self.detectors.get("replay_flag", pd.Series(dtype=int)).sum()),
        }

    def save(self, folder: str | Path) -> Path:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        daily = pd.concat([self.detectors, self.probability.rename("probability"), self.trust,
                           self.band, self.weight, self.decisions], axis=1)
        daily.to_csv(folder / "daily.csv")
        self.actions.to_csv(folder / "actions.csv", index=False)
        pd.DataFrame(self.episodes).to_csv(folder / "episodes.csv", index=False)
        self.residuals.to_csv(folder / "residuals.csv")
        self.used.to_csv(folder / "series_used.csv")
        pd.Series(self.summary()).to_csv(folder / "summary.csv", header=["value"])
        return folder


# --------------------------------------------------------------------------- run


def load_fusion(path: str | Path = FUSION_FILE) -> dict[str, Any]:
    import joblib
    if not Path(path).is_file():
        raise FileNotFoundError(f"{path} is missing: run  python scripts/train_fusion.py  once (about 10 minutes).")
    return joblib.load(path)


def assess(station: pd.DataFrame, reference: pd.DataFrame, lat: float, lon: float,
           periods: dict[str, str] | None = None, site: str | None = None,
           labels: pd.DataFrame | None = None, progress=lambda msg: None) -> Assessment:
    """Run the whole defence on one station series.  ``site`` enables detector M (development sites only)."""
    from sensorguard.eval.trust_eval import load_trust_config

    t = time.perf_counter()
    seconds: dict[str, float] = {}
    warn: list[str] = []
    days = station.index.union(reference.index)
    station = station.reindex(days)[VARIABLES]
    reference = reference.reindex(days)[VARIABLES]
    periods = periods or default_periods(station.dropna(how="all").index)
    fit = slice(periods["train_start"], periods["train_end"])

    variables = [v for v in VARIABLES if station.loc[fit, v].notna().mean() > 0.5 and reference.loc[fit, v].notna().mean() > 0.5]
    monitored = [v for v in MONITORED if v in variables]
    if not monitored:
        raise ValueError("No usable variable: each needs values on more than half of the fit period, in the station and the reference.")
    dropped = [v for v in VARIABLES if v not in variables]
    if dropped:
        warn.append(f"Not analysed (too few values in the fit period): {', '.join(dropped)}")
    if len(station.loc[fit].dropna(how='all')) < 150:
        warn.append("The fit period has fewer than 150 days: thresholds will be unreliable.")

    # configs restricted to the variables present
    prep_cfg = pl.load_config()
    prep_cfg = copy.deepcopy(prep_cfg)
    prep_cfg["variables"] = {v: s for v, s in prep_cfg["variables"].items() if v in variables}
    prep_cfg["split"] = dict(periods)
    dcfg = load_detector_config()
    dcfg["monitored_variables"] = monitored
    dcfg["variables"] = variables
    dcfg["residual_variables"] = {v: f"reference_{v}" for v in variables}
    dcfg["replay"] = {**dcfg["replay"], "columns": {v: f"station_{v}" for v in monitored}}
    dcfg["change_point"] = {**dcfg["change_point"], "test_variables": monitored}
    tcfg = load_trust_config()

    progress("calibration against NASA POWER")
    prep = pl.prepare(station[variables], reference[variables], prep_cfg)
    seconds["calibration"], t = time.perf_counter() - t, time.perf_counter()

    progress("detector S")
    model = statistical.fit(prep.reference, station[variables], periods, dcfg)
    det = statistical.score(model, prep.reference, station[variables])
    seconds["detector S"], t = time.perf_counter() - t, time.perf_counter()

    m_flags = None
    from sensorguard.detect.learned import predict_detector_m
    if site is not None and len(variables) == len(VARIABLES):
        try:
            progress("detector M")
            m = predict_detector_m(station, reference, site)
            m_flags = m["is_anomaly"].reindex(det.daily.index).fillna(0).astype(int)
        except Exception as exc:  # unknown site or missing model files
            warn.append(f"Detector M not used: {exc}")
    seconds["detector M"], t = time.perf_counter() - t, time.perf_counter()

    progress("probability, trust and responses")
    saved = load_fusion()
    variant = "with_m" if m_flags is not None else "s_only"
    fm, bands = saved[variant]["model"], saved[variant]["bands"]
    x = fusion.features(det.daily, det.params, m_flags, int(tcfg["fusion"]["persistence_days"]), prep.reference)
    p = fm.probability(x)
    trust = trust_score.trust_series(p, tcfg["trust"]["fall_rate"], tcfg["trust"]["recovery_rate"])
    band = trust_score.band_series(trust, bands)
    w = policy.weights(trust, band, bands)
    rc = tcfg["response"]
    imp = policy.implicated(prep.reference, det.daily["replay_flag"].astype(bool), rc["implicated_days"], rc["implicated_sd"])
    ref_cal = policy.calibrated_reference(reference[variables], prep.calibration, prep_cfg).reindex(columns=VARIABLES)
    used = policy.apply(station, ref_cal, w, imp.reindex(columns=VARIABLES).fillna(False))
    acts = policy.actions(trust, band, fm.contributions(x), det.episodes, rc["verification_every_days"],
                          det.daily["replay_flag"])
    seconds["fusion and responses"], t = time.perf_counter() - t, time.perf_counter()

    progress("water balance and decision")
    pc = tcfg["product"]
    score = slice(periods["validation_start"], periods["validation_end"])
    balance = pd.DataFrame(index=station.index)
    decisions = pd.DataFrame(index=det.daily.index)
    if len(variables) == len(VARIABLES):
        b_rec = wb.water_balance(station, lat, pc["window_days"], pc["elevation_m"])
        b_def = wb.water_balance(used, lat, pc["window_days"], pc["elevation_m"])
        levels = wb.fit_levels(b_rec.loc[fit], pc["dry_quantile"], pc["severe_quantile"]).reindex(range(1, 13))
        overall = b_rec.loc[fit].dropna()
        levels["dry"] = levels["dry"].fillna(overall.quantile(pc["dry_quantile"]))
        levels["severe"] = levels["severe"].fillna(overall.quantile(pc["severe_quantile"]))
        balance["as received"], balance["with defence"] = b_rec, b_def
        decisions["decision_as_received"] = wb.decision_levels(b_rec, levels).loc[score]
        decisions["decision_with_defence"] = wb.decision_levels(b_def, levels).loc[score]
        trusted_window = (band == trust_score.TRUSTED).astype(float).rolling(int(pc["window_days"]), min_periods=1).min()
        decisions["confidence"] = np.where(trusted_window.reindex(decisions.index) >= 1, "TRUSTED", "DEGRADED")
    else:
        warn.append("Water balance needs all five variables: no decision product.")
    seconds["product"] = time.perf_counter() - t

    thresholds = {name: float(det.params[name]["threshold"]) for name in det.params if "threshold" in det.params[name]}
    return Assessment(station, reference, ref_cal, (lat, lon), dict(periods), variables, prep.reference,
                      det.daily, thresholds, det.episodes, x, p, trust, band, bands, w, imp, used, acts,
                      balance, decisions, variant, seconds, warn, labels)
