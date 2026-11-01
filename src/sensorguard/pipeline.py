"""Wires the stages for file mode: clean data -> attack -> layer 1 -> preparation -> screen.

``run(site, spec)`` takes one development site and one attack description and
returns every intermediate table, so a GUI or a test can look at each stage:

    1. data         clean station series + NASA POWER witness (config/preparation.yaml)
    2. attack       one official attack (step, drift, replay) with exact labels
    3. layer 1      every day becomes a signed record; the attacker acts at the
                    position chosen in the threat model, then the real verifier
                    and the hash-chained ledger decide what gets through
    4. preparation  calibration + reference and temporal residuals, fitted on the
                    training years of what layer 1 let through
    5. screen       a plain threshold on a rolling mean of one residual

Where the attacker sits decides which layer has to catch the attack
(docs/03-threat-model.md):

    P1  at the station: the station signs the false values itself, so layer 1
        accepts everything and only the residuals can show the attack.
    P2  on the telemetry link, without the station key: a changed record fails
        its signature, a replayed record fails the sequence check.
    P3  in the pipeline, after verification: stored records are rewritten, so
        the ledger chain breaks at the first rewritten entry.

The screen in stage 5 is a placeholder so the chain can be tested end to end.
It is NOT detector S or M (src/sensorguard/detect/ is still empty).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sensorguard.attacks import official
from sensorguard.attacks.labels import empty_labels
from sensorguard.processing.calibrate import (
    fit_reference_calibration,
    load_preparation_config,
    read_cleaned_daily_table,
)
from sensorguard.processing.residuals.reference import apply_reference_residuals
from sensorguard.processing.residuals.temporal import apply_temporal_residuals, fit_temporal_model
from sensorguard.trust import record as rec
from sensorguard.trust import verify as vfy
from sensorguard.trust.enrolment import Registry, issue_certificate
from sensorguard.trust.keys import FileSecureElement, generate_root, sign_record
from sensorguard.trust.ledger import Ledger

REPO_ROOT = Path(__file__).resolve().parents[2]
PREPARATION_CONFIG = REPO_ROOT / "config" / "preparation.yaml"
SPLIT_CONFIG = REPO_ROOT / "config" / "split.yaml"

VARIABLES = ["temp_c", "rh_pct", "wind_ms", "precip_mm", "solar_mj_m2"]
LIMITS = {"rh_pct": (0, 100), "wind_ms": (0, None), "precip_mm": (0, None), "solar_mj_m2": (0, None)}
ATTACKS = ("none", "step", "drift", "replay")
POSITIONS = {
    "P1": "at the station (it signs the false values itself)",
    "P2": "on the telemetry link (no station key)",
    "P3": "in the pipeline, after verification (rewrites stored records)",
}
SENSOR_ID = 1
DAY = 86_400

# A missing value travels as the smallest int32, which no real reading can take.
_MISSING = -(2**31) / rec.SCALE


# --------------------------------------------------------------------------- inputs


@dataclass
class AttackSpec:
    """What to inject, and where the attacker sits."""

    attack: str = "none"                    # none | step | drift | replay
    variables: tuple[str, ...] = ("temp_c",)  # step and drift; replay copies the whole record
    onset: str = "2024-04-01"
    magnitude: float = 0.12
    sign: int = 1
    relative_to: str = "value"              # value | range | std
    length_days: int = 60                   # step: attacked days; replay: replayed days
    ramp_days: int = 30                     # drift
    hold_days: int = 30                     # drift
    source_offset_days: int = 7             # replay: copy the days this far back
    position: str = "P1"


# --------------------------------------------------------------------------- outputs


@dataclass
class TrustReport:
    log: pd.DataFrame          # one row per day: seq, sent, decision, reason, gap
    received: pd.DataFrame     # what the pipeline reads back from the ledger (NaN = rejected day)
    ledger_ok: bool
    ledger_first_broken: pd.Timestamp | None
    counts: dict[str, int]


@dataclass
class Preparation:
    calibration: dict[str, Any]
    temporal_model: dict[str, Any]
    reference: pd.DataFrame
    temporal: pd.DataFrame


@dataclass
class PipelineResult:
    site: str
    spec: AttackSpec
    coords: tuple[float, float]
    config: dict[str, Any]
    station: pd.DataFrame      # clean station series
    power: pd.DataFrame        # NASA POWER witness
    attack: official.AttackResult
    trust: TrustReport
    prep: Preparation
    seconds: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def labels(self) -> pd.DataFrame:
        return self.attack.labels


# --------------------------------------------------------------------------- stage 1: data


def load_config() -> dict[str, Any]:
    return load_preparation_config(PREPARATION_CONFIG, SPLIT_CONFIG)


def sites(config: dict[str, Any] | None = None) -> list[str]:
    return sorted((config or load_config())["sites"])


def _coords(power_file: str) -> tuple[float, float]:
    """Latitude and longitude written in the POWER file name, e.g. power_32.48_-109.93_..."""
    m = re.match(r"power_(-?\d+(?:\.\d+)?)_(-?\d+(?:\.\d+)?)_", power_file)
    if not m:
        raise ValueError(f"cannot read coordinates from {power_file!r}")
    return float(m.group(1)), float(m.group(2))


def load_site(site: str, config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, tuple[float, float]]:
    """Clean station and witness series on one complete daily calendar."""
    files = config["sites"][site]
    folder = REPO_ROOT / config["input_directory"]
    station = read_cleaned_daily_table(folder / files["station_file"])
    power = read_cleaned_daily_table(folder / files["power_file"])
    days = pd.date_range(min(station.index.min(), power.index.min()),
                         max(station.index.max(), power.index.max()), freq="D", name="date")
    return station.reindex(days), power.reindex(days), _coords(files["power_file"])


# --------------------------------------------------------------------------- stage 2: attack


def inject(station: pd.DataFrame, spec: AttackSpec) -> official.AttackResult:
    """Apply the attack to the station series only; the witness is out of reach."""
    if spec.attack == "none":
        return official.AttackResult(station.copy(), empty_labels(station.index), [])
    onset = pd.Timestamp(spec.onset)
    variables = list(spec.variables)
    if spec.attack == "step":
        return official.step_bias(station, variables, onset, spec.magnitude, spec.sign,
                                   spec.relative_to, spec.length_days, limits=LIMITS)
    if spec.attack == "drift":
        return official.drift(station, variables, onset, spec.magnitude, spec.ramp_days,
                              spec.hold_days, spec.sign, spec.relative_to, limits=LIMITS)
    if spec.attack == "replay":
        return official.replay(station, onset, spec.length_days, spec.source_offset_days)
    raise ValueError(f"unknown attack {spec.attack!r}, expected one of {ATTACKS}")


# --------------------------------------------------------------------------- stage 3: layer 1


def pack(values) -> bytes:
    """Payload for one day; NaN survives the trip as a reserved value."""
    return rec.encode_payload([_MISSING if pd.isna(v) else float(v) for v in values])


def unpack(payload: bytes) -> list[float]:
    values, _ = rec.decode_payload(payload)
    return [np.nan if v <= _MISSING + 0.5 / rec.SCALE else v for v in values]


def _ts(day: pd.Timestamp) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


def transmit(clean: pd.DataFrame, attack: official.AttackResult, position: str,
             coords: tuple[float, float]) -> TrustReport:
    """Sign every day at the station, let the attacker act, verify, store in the ledger."""
    if position not in POSITIONS:
        raise ValueError(f"unknown position {position!r}, expected one of {list(POSITIONS)}")
    days = clean.index
    labels = attack.labels
    hit = labels["attacked"].to_numpy()

    # Operator root, one enrolled station, the verifier and the ledger: the real objects.
    root = generate_root()
    registry = Registry(root.public_key())
    station_key = FileSecureElement.generate()
    registry.enrol(issue_certificate(
        root, sensor_id=SENSOR_ID, public_key=station_key.public_key(), position=coords,
        valid_from=_ts(days[0]) - DAY, valid_to=_ts(days[-1]) + 2 * DAY))
    verifier = vfy.Verifier(registry)
    ledger = Ledger()

    # At P1 the false values exist before signing; elsewhere the station signs the truth.
    signed_values = attack.series if position == "P1" else clean
    prev = rec.ZERO_HASH
    genuine: list[rec.Record] = []
    for seq, day in enumerate(days):
        r = rec.Record(sensor_id=SENSOR_ID, key_id=0, seq=seq, t_obs=_ts(day),
                       prev_hash=prev, payload=pack(signed_values.loc[day, VARIABLES]))
        r = sign_record(station_key, r)
        genuine.append(r)
        prev = r.digest()

    rows = []
    stored_day: list[pd.Timestamp] = []
    for i, day in enumerate(days):
        sent = "genuine"
        wire = genuine[i]
        if position == "P2" and hit[i]:
            if labels["attack"].iat[i] == "replay":
                src = days.get_loc(labels["source_date"].iat[i])
                wire, sent = genuine[src], "replayed"          # an old, validly signed record
            else:
                wire = rec.Record(**{**wire.__dict__, "payload": pack(attack.series.loc[day, VARIABLES])})
                sent = "tampered"                              # new values, old signature
        v = verifier.verify(wire.encode(), arrival_time=_ts(day) + DAY)
        if v.accepted:
            ledger.append(wire.encode())
            stored_day.append(day)
        rows.append({"date": day, "seq": wire.seq, "sent": sent, "decision": v.decision,
                     "reason": v.reason, "gap": v.gap})
    log = pd.DataFrame(rows).set_index("date")

    # P3: an intruder rewrites stored records of the attacked days, after verification.
    if position == "P3":
        for k, day in enumerate(stored_day):
            if labels.at[day, "attacked"]:
                e = ledger[k]
                old = rec.decode(e.payload)
                new = rec.Record(**{**old.__dict__, "payload": pack(attack.series.loc[day, VARIABLES])})
                ledger._entries[k] = type(e)(e.index, new.encode(), e.prev_hash, e.entry_hash)
                log.at[day, "sent"] = "rewritten in store"

    # What every later stage reads: the store, not the wire.
    received = pd.DataFrame(np.nan, index=days, columns=VARIABLES)
    for k in range(len(ledger)):
        r = rec.decode(ledger[k].payload)
        received.loc[stored_day[k]] = unpack(r.payload)
    received.index.name = "date"

    broken = ledger.first_broken()
    counts = {
        "records": len(days),
        "accepted": int((log["decision"] == vfy.ACCEPT).sum()),
        "flagged": int((log["decision"] == vfy.FLAG).sum()),
        "rejected": int((log["decision"] == vfy.REJECT).sum()),
        "gaps": int(log["gap"].sum()),
        "stored": len(ledger),
    }
    for reason, n in log.loc[log["reason"] != vfy.OK, "reason"].value_counts().items():
        counts[f"reason:{reason}"] = int(n)
    return TrustReport(log, received, broken is None,
                       None if broken is None else stored_day[broken], counts)


# --------------------------------------------------------------------------- stage 4: preparation


def prepare(received: pd.DataFrame, power: pd.DataFrame, config: dict[str, Any]) -> Preparation:
    """Fit on the training years of the received series, apply to every day."""
    split = config["split"]
    calibration = fit_reference_calibration(received, power, config, split["train_start"], split["train_end"])
    temporal_model = fit_temporal_model(received, config, split["train_start"], split["train_end"])
    return Preparation(
        calibration,
        temporal_model,
        apply_reference_residuals(received, power, calibration, config),
        apply_temporal_residuals(received, temporal_model, config),
    )


# --------------------------------------------------------------------------- stage 5: screen


def screen_score(residual: pd.Series, window: int) -> pd.Series:
    """Causal rolling mean of a standardised residual (window 1 = the residual itself)."""
    return residual.rolling(window, min_periods=max(1, window // 2)).mean()


def screen(result: PipelineResult, family: str = "reference", window: int = 7,
           threshold: float = 1.5) -> pd.DataFrame:
    """Placeholder check, per variable, over the validation period only.

    A day is flagged when |rolling mean of the residual| > threshold. Reports how
    much of the attack window is flagged, how late the first flag comes, and how
    often clean days are flagged. Not detector S or M.
    """
    residuals = result.prep.reference if family == "reference" else result.prep.temporal
    start = pd.Timestamp(result.config["split"]["validation_start"])
    attacked = result.labels["attacked"]
    hit_vars = {v for joined in result.labels.loc[attacked, "variables"].unique() for v in joined.split(";")}
    stored = result.trust.log["decision"] != vfy.REJECT
    in_attack = attacked.loc[start:]
    # Attacked days that layer 1 let through: the only ones the residuals can still catch.
    att_days = in_attack[in_attack & stored.loc[start:]].index
    clean_days = in_attack[~in_attack].index
    rows = []
    for var in VARIABLES:
        score = screen_score(residuals[var], window).loc[start:]
        flags = score.abs() > threshold
        first = flags.loc[att_days][flags.loc[att_days]].index.min() if len(att_days) else pd.NaT
        rows.append({
            "variable": var,
            "attacked": var in hit_vars,
            "attack_days_reached": len(att_days),
            "flagged_in_attack": float(flags.loc[att_days].mean()) if len(att_days) else np.nan,
            "days_to_first_flag": (first - att_days[0]).days if pd.notna(first) else np.nan,
            "false_alarm_rate": float(flags.loc[clean_days].mean()) if len(clean_days) else np.nan,
            "valid_days": int(score.notna().sum()),
        })
    return pd.DataFrame(rows).set_index("variable")


# --------------------------------------------------------------------------- saving


RUNS_DIR = REPO_ROOT / "results" / "pipeline_runs"


def run_name(result: PipelineResult) -> str:
    s = result.spec
    if s.attack == "none":
        return f"{result.site}_none"
    what = s.attack if s.attack == "replay" else f"{s.attack}-{'-'.join(s.variables)}-{'up' if s.sign > 0 else 'down'}"
    return f"{result.site}_{what}_{s.onset}_{s.position}"


def save(result: PipelineResult, folder: str | Path | None = None,
         screen_table: pd.DataFrame | None = None) -> Path:
    """Write every stage of one run as CSV files; returns the folder.

    attacked.csv   the station series after the attack (what the attacker produced)
    labels.csv     one row per day: attacked or not, which attack, size, replay source
    episodes.csv   one row per attack episode: onset, end, parameters
    received.csv   what got through layer 1 and was read back from the ledger
    layer1_log.csv one row per day: what was sent, ACCEPT / FLAG / REJECT, reason, gap
    residuals_reference.csv, residuals_temporal.csv   the standardised residuals
    screen.csv     the placeholder screen table, if given
    """
    from sensorguard.attacks.labels import episodes_table

    folder = Path(folder) if folder else RUNS_DIR / run_name(result)
    folder.mkdir(parents=True, exist_ok=True)
    result.attack.series.to_csv(folder / "attacked.csv")
    result.labels.to_csv(folder / "labels.csv")
    episodes_table(result.attack.episodes).to_csv(folder / "episodes.csv", index=False)
    result.trust.received.to_csv(folder / "received.csv")
    result.trust.log.to_csv(folder / "layer1_log.csv")
    result.prep.reference.to_csv(folder / "residuals_reference.csv")
    result.prep.temporal.to_csv(folder / "residuals_temporal.csv")
    if screen_table is not None:
        screen_table.to_csv(folder / "screen.csv")
    return folder


# --------------------------------------------------------------------------- end to end


def run(site: str, spec: AttackSpec, config: dict[str, Any] | None = None) -> PipelineResult:
    """All five stages on one site, with the time each stage took."""
    config = config or load_config()
    seconds: dict[str, float] = {}
    t = time.perf_counter()

    station, power, coords = load_site(site, config)
    seconds["data"], t = time.perf_counter() - t, time.perf_counter()

    attack = inject(station, spec)
    seconds["attack"], t = time.perf_counter() - t, time.perf_counter()

    trust = transmit(station, attack, spec.position, coords)
    seconds["layer 1"], t = time.perf_counter() - t, time.perf_counter()

    prep = prepare(trust.received, power, config)
    seconds["preparation"] = time.perf_counter() - t

    warnings = []
    train_end = pd.Timestamp(config["split"]["train_end"])
    if attack.labels.loc[:train_end, "attacked"].any():
        warnings.append(
            f"The attack starts before {train_end.date()}, inside the training years: the "
            "calibration learns part of the attack as normal. Put the onset in the validation year.")
    if spec.position == "P3" and trust.ledger_ok and attack.labels["attacked"].any():
        warnings.append("P3 rewrite left the ledger intact: this should not happen.")
    return PipelineResult(site, spec, coords, config, station, power, attack, trust, prep, seconds, warnings)
