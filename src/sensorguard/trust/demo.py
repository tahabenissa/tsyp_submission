"""A runnable demo of layer 1: send records, watch them get caught.

This is not a test and not part of the product; it is a readable transcript for
the team and the jury. It sets up a real root key, a real station key and the
verifier, sends a few honest signed records (all accepted), then performs each
of the attacks L1 exists to stop and prints the verdict.

    python -m sensorguard.trust.demo                 # honest stream + every attack
    python -m sensorguard.trust.demo --attack replay  # just one attack
    python -m sensorguard.trust.demo --attack forged|modified|replay|dropped|silent

Nothing here touches the network or the disk.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from . import record as rec
from . import verify as vfy
from .enrolment import Registry, issue_certificate
from .keys import FileSecureElement, generate_root, sign_record

DAY = 86_400
T0 = int(datetime(2023, 7, 1, tzinfo=timezone.utc).timestamp())
POS = (35.68, 10.10)
SENSOR_ID = 1

ATTACKS = ("forged", "modified", "replay", "dropped", "silent")


def _day(t_obs: int) -> str:
    return datetime.fromtimestamp(t_obs, tz=timezone.utc).strftime("%Y-%m-%d")


def _show(label: str, verdict: vfy.Verdict, note: str = "") -> None:
    decision = verdict.decision.upper()
    gap = "  GAP RAISED" if verdict.gap else ""
    print(f"  {label:<10} -> {decision:<6} {verdict.reason:<16}{gap}  {note}")


class Station:
    """A station building a correct, signed hash chain (the honest sender)."""

    def __init__(self, se: FileSecureElement, sensor_id: int = SENSOR_ID, key_id: int = 0):
        self.se = se
        self.sensor_id = sensor_id
        self.key_id = key_id
        self.seq = 0
        self.t = T0
        self.prev = rec.ZERO_HASH

    def emit(self, values=(28.4, 41.0, 22.6), advance=True) -> rec.Record:
        r = rec.Record(
            sensor_id=self.sensor_id,
            key_id=self.key_id,
            seq=self.seq,
            t_obs=self.t,
            prev_hash=self.prev,
            payload=rec.encode_payload(list(values)),
        )
        r = sign_record(self.se, r)
        if advance:
            self.seq += 1
            self.t += DAY
            self.prev = r.digest()
        return r


def build() -> tuple[Registry, FileSecureElement, Station, vfy.Verifier]:
    """Set up the operator root, enrol one station, return the verifier too."""
    root = generate_root()
    registry = Registry(root.public_key())
    se = FileSecureElement.generate()
    cert = issue_certificate(
        root,
        sensor_id=SENSOR_ID,
        public_key=se.public_key(),
        position=POS,
        valid_from=T0 - 365 * DAY,
        valid_to=T0 + 365 * DAY,
        key_id=0,
    )
    registry.enrol(cert)
    print("setup:")
    print("  root key created (offline operator)")
    print("  station key generated on device (private key never leaves it)")
    print(f"  enrolled: station {SENSOR_ID} at {POS}, certificate signed by root")
    return registry, se, Station(se), vfy.Verifier(registry)


def honest_stream(station: Station, verifier: vfy.Verifier, n: int = 3) -> None:
    print(f"\nhonest stream ({n} daily records, each signed by the station):")
    for _ in range(n):
        r = station.emit()
        v = verifier.verify(r.encode(), arrival_time=r.t_obs)
        _show(f"{_day(r.t_obs)}", v, f"seq {r.seq}")


def attack_forged(_registry, se, station, verifier) -> None:
    impostor = FileSecureElement.generate()
    r = Station(impostor).emit()                      # claims station 1, signs with its own key
    v = verifier.verify(r.encode(), arrival_time=r.t_obs)
    _show("[forged]", v, "impostor's signature does not match the enrolled key")


def attack_modified(_registry, se, station, verifier) -> None:
    r = station.emit()
    raw = bytearray(r.encode())
    raw[rec.HEADER_SIZE] ^= 0xFF                      # flip a payload byte after signing
    v = verifier.verify(bytes(raw), arrival_time=r.t_obs)
    _show("[modified]", v, "one changed byte breaks the signature")


def attack_replay(_registry, se, station, verifier) -> None:
    first = station.emit()
    verifier.verify(first.encode(), arrival_time=first.t_obs)          # accepted once
    verifier.verify(station.emit().encode(), arrival_time=station.t)   # a later record too
    v = verifier.verify(first.encode(), arrival_time=station.t)        # resend the old one
    _show("[replay]", v, f"seq {first.seq} <= last accepted seq")


def attack_dropped(_registry, se, station, verifier) -> None:
    verifier.verify(station.emit().encode(), arrival_time=station.t)   # record accepted
    station.emit()                                                     # next record SUPPRESSED
    r = station.emit()
    v = verifier.verify(r.encode(), arrival_time=r.t_obs)              # the one after the hole
    _show("[dropped]", v, "prev_hash mismatch: a record is missing")


def attack_silent(_registry, se, station, verifier) -> None:
    r = station.emit()
    verifier.verify(r.encode(), arrival_time=r.t_obs)
    now = r.t_obs + 3 * DAY                                            # 3 days of silence
    silent = verifier.silent_stations(now=now)
    caught = SENSOR_ID in silent
    print(f"  {'[silent]':<10} -> {'SILENT' if caught else 'ok':<6} "
          f"{'watchdog':<16}  no valid record for 3 days -> station {silent} reported silent")


RUNNERS = {
    "forged": attack_forged,
    "modified": attack_modified,
    "replay": attack_replay,
    "dropped": attack_dropped,
    "silent": attack_silent,
}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Layer-1 provenance demo: send records, see them caught.")
    ap.add_argument("--attack", choices=(*ATTACKS, "all"), default="all",
                    help="which attack to run (default: all, after an honest stream)")
    args = ap.parse_args(argv)

    print("=" * 68)
    print("Layer 1 (provenance) demo — identity, integrity, order, suppression")
    print("=" * 68)

    if args.attack == "all":
        _, se, station, verifier = build()
        honest_stream(station, verifier)
        print("\nnow the attacks L1 must catch (each on a fresh station):")
        for name in ATTACKS:
            _, se, station, verifier = build_quiet()
            RUNNERS[name](None, se, station, verifier)
    else:
        print()
        _, se, station, verifier = build()
        print()
        RUNNERS[args.attack](None, se, station, verifier)

    print("\n(reminder: L1 proves a record is authentic and in order. A station that is")
    print(" itself hacked signs valid records — catching that is L2/L3, not L1.)")


def build_quiet() -> tuple[Registry, FileSecureElement, Station, vfy.Verifier]:
    """Same as build() but without printing the setup block (used in the 'all' loop)."""
    import io
    import contextlib

    with contextlib.redirect_stdout(io.StringIO()):
        return build()


if __name__ == "__main__":
    main()
