"""Verification, per-station replay state, and the cadence watchdog.

This is layer L1: it decides, for each arriving record, ACCEPT / FLAG / REJECT
from provenance alone -- signature, sequence, hash chain and timing -- before
any signal analysis. It catches forgery, modification and replay in transit or
in the pipeline, and (through the chain and the watchdog) suppression of
records. It is blind to a station that is itself compromised or physically
deceived: that data is validly signed, and L2/L3 must catch it.

The algorithm (from the architecture note):

    1. Parse. Malformed                               -> REJECT malformed
    2. sensor_id unknown / revoked / cert not valid   -> REJECT unknown_station
    3. signature invalid                              -> REJECT forged
    4. seq <= last accepted seq                       -> REJECT replay
    5. t_obs implausible vs arrival and cadence       -> REJECT stale / FLAG delayed
    6. prev_hash != last accepted hash                -> ACCEPT, raise gap
    7. persist seq and hash; pass the reading on      -> ACCEPT

Per-station persistent state is two values, ``last_seq`` and ``last_hash``
(plus the last arrival time, for the watchdog).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import record as rec
from .enrolment import Registry
from .keys import verify_signature

# Verdict reasons.
OK = "ok"
MALFORMED = "malformed"
UNKNOWN_STATION = "unknown_station"
FORGED = "forged"
REPLAY = "replay"
STALE = "stale"
DELAYED = "delayed"
GAP = "gap"

ACCEPT = "accept"
FLAG = "flag"
REJECT = "reject"

DAY = 86_400                        # seconds


@dataclass
class StationState:
    """The two-value replay state for one station, plus last arrival for cadence."""

    last_seq: int = -1
    last_hash: bytes = rec.ZERO_HASH
    last_arrival: int = -1


@dataclass
class Verdict:
    """The outcome of verifying one record."""

    decision: str                   # ACCEPT / FLAG / REJECT
    reason: str
    gap: bool = False               # a record was accepted but the chain skipped
    record: rec.Record | None = None

    @property
    def accepted(self) -> bool:
        return self.decision in (ACCEPT, FLAG)


@dataclass
class Verifier:
    """Stateful L1 verifier over a registry of enrolled stations."""

    registry: Registry
    cadence: int = DAY              # expected interval between a station's records
    margin: int = DAY               # grace before a late/early record is rejected
    future_margin: int = 3600       # how far ahead of arrival t_obs may sit
    state: dict[int, StationState] = field(default_factory=dict)

    def _state(self, sensor_id: int) -> StationState:
        return self.state.setdefault(sensor_id, StationState())

    def verify(self, raw: bytes, arrival_time: int) -> Verdict:
        # 1. parse
        try:
            record = rec.decode(raw)
        except rec.MalformedRecord:
            return Verdict(REJECT, MALFORMED)

        # 2. known, not revoked, certificate valid at observation time
        cert = self.registry.active_certificate(record.sensor_id, record.t_obs)
        if cert is None or cert.key_id != record.key_id:
            return Verdict(REJECT, UNKNOWN_STATION, record=record)

        # 3. signature
        if not verify_signature(cert.public_key, record.signature, record.signed_region()):
            return Verdict(REJECT, FORGED, record=record)

        st = self._state(record.sensor_id)

        # 4. replay / reorder: the sequence counter must strictly increase
        if record.seq <= st.last_seq:
            return Verdict(REJECT, REPLAY, record=record)

        # 5. timing versus arrival and the expected cadence
        if record.t_obs > arrival_time + self.future_margin:
            return Verdict(REJECT, STALE, record=record)        # dated in the future
        age = arrival_time - record.t_obs
        delayed = age > self.cadence + self.margin

        # 6. hash chain: a mismatch means one or more records are missing
        gap = record.prev_hash != st.last_hash

        # 7. persist and accept
        st.last_seq = record.seq
        st.last_hash = record.digest()
        st.last_arrival = arrival_time
        if delayed:
            return Verdict(FLAG, DELAYED, gap=gap, record=record)
        if gap:
            return Verdict(ACCEPT, GAP, gap=True, record=record)
        return Verdict(ACCEPT, OK, record=record)

    def silent_stations(self, now: int) -> list[int]:
        """Enrolled, non-revoked stations with no valid record within the expected
        interval plus the margin. Silence is reported, never read as a quiet day."""
        silent = []
        for sensor_id, st in self.state.items():
            if self.registry.is_revoked(sensor_id):
                continue
            if st.last_arrival < 0 or now - st.last_arrival > self.cadence + self.margin:
                silent.append(sensor_id)
        return sorted(silent)
