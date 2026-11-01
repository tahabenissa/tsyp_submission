"""Forged, modified, replayed and missing records.

Exercises the L1 trust layer end to end: the record format, the key/secure-element
boundary, root-signed enrolment with revocation and validity, the seven-step
verifier, the cadence watchdog and the tamper-evident ledger. No network, no
files except a tmp keystore; runs in well under a second.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sensorguard import trust
from sensorguard.trust import ledger as ledger_mod
from sensorguard.trust import record as rec
from sensorguard.trust import verify as vfy

DAY = 86_400
T0 = 1_700_000_000          # a fixed arbitrary "now" in unix seconds
POS = (35.68, 10.10)


# --- helpers ---------------------------------------------------------------

def make_station(registry, root, sensor_id=1, key_id=0, valid_from=0, valid_to=T0 + 10 * DAY):
    """Generate a station key, enrol it, and return its secure element."""
    se = trust.FileSecureElement.generate()
    cert = trust.issue_certificate(
        root,
        sensor_id=sensor_id,
        public_key=se.public_key(),
        position=POS,
        valid_from=valid_from,
        valid_to=valid_to,
        key_id=key_id,
    )
    registry.enrol(cert)
    return se


class Chain:
    """A station building a correct hash chain of signed records."""

    def __init__(self, se, sensor_id=1, key_id=0, start_seq=0, t_start=T0):
        self.se = se
        self.sensor_id = sensor_id
        self.key_id = key_id
        self.seq = start_seq
        self.t = t_start
        self.prev = rec.ZERO_HASH
        self.last = None

    def next(self, values=(20.0, 50.0), advance=True):
        r = rec.Record(
            sensor_id=self.sensor_id,
            key_id=self.key_id,
            seq=self.seq,
            t_obs=self.t,
            prev_hash=self.prev,
            payload=rec.encode_payload(list(values)),
        )
        r = trust.sign_record(self.se, r)
        if advance:
            self.seq += 1
            self.t += DAY
            self.prev = r.digest()
            self.last = r
        return r


@pytest.fixture
def root():
    return trust.generate_root()


@pytest.fixture
def setup(root):
    registry = trust.Registry(root.public_key())
    se = make_station(registry, root)
    verifier = trust.Verifier(registry)
    return registry, se, verifier


# --- record format ---------------------------------------------------------

def test_overhead_is_118_bytes():
    assert trust.OVERHEAD == 118

def test_record_round_trips():
    r = rec.Record(sensor_id=7, key_id=2, seq=5, t_obs=T0, prev_hash=rec.ZERO_HASH,
                   payload=rec.encode_payload([20.0, 50.0]), signature=b"\x00" * 64)
    back = rec.decode(r.encode())
    assert (back.sensor_id, back.key_id, back.seq, back.t_obs) == (7, 2, 5, T0)
    assert back.payload == r.payload and back.signature == r.signature

def test_encoded_length_is_overhead_plus_payload():
    payload = rec.encode_payload([1.0, 2.0, 3.0])        # 1 + 3*4 = 13 bytes
    r = rec.Record(sensor_id=1, key_id=0, seq=0, t_obs=T0, prev_hash=rec.ZERO_HASH,
                   payload=payload, signature=b"\x00" * 64)
    assert len(r.encode()) == trust.OVERHEAD + len(payload)

def test_payload_codec_round_trips():
    values = [19.5, -3.25, 100.0, 0.0]
    back, status = rec.decode_payload(rec.encode_payload(values, status=3))
    assert status == 3
    assert back == pytest.approx(values)

def test_decode_rejects_short_and_mismatched():
    with pytest.raises(rec.MalformedRecord):
        rec.decode(b"\x00" * 10)                          # below the 118-byte floor
    r = rec.Record(sensor_id=1, key_id=0, seq=0, t_obs=T0, prev_hash=rec.ZERO_HASH,
                   payload=b"\x01\x02\x03", signature=b"\x00" * 64)
    raw = bytearray(r.encode())
    with pytest.raises(rec.MalformedRecord):
        rec.decode(bytes(raw[:-1]))                       # one byte short of payload_len


# --- keys and the secure-element boundary ----------------------------------

def test_sign_and_verify():
    se = trust.FileSecureElement.generate()
    sig = se.sign(b"hello")
    assert trust.verify_signature(se.public_key(), sig, b"hello")
    assert not trust.verify_signature(se.public_key(), sig, b"hellp")  # tampered data

def test_public_key_is_32_bytes_and_private_is_not_exposed():
    se = trust.FileSecureElement.generate()
    assert len(se.public_key()) == 32
    assert not hasattr(se, "private_bytes")
    assert not any("private" in name for name in vars(se))

def test_keystore_survives_reload(tmp_path):
    path = tmp_path / "station.key"
    se = trust.FileSecureElement.generate(path)
    reloaded = trust.FileSecureElement.load(path)
    assert reloaded.public_key() == se.public_key()
    assert trust.verify_signature(se.public_key(), reloaded.sign(b"x"), b"x")


# --- enrolment, revocation, validity ---------------------------------------

def test_certificate_verifies_against_its_root(root):
    se = trust.FileSecureElement.generate()
    cert = trust.issue_certificate(root, sensor_id=1, public_key=se.public_key(),
                                   position=POS, valid_from=0, valid_to=T0 + DAY)
    assert trust.verify_certificate(cert, root.public_key())

def test_certificate_rejected_under_a_different_root(root):
    other = trust.generate_root()
    se = trust.FileSecureElement.generate()
    cert = trust.issue_certificate(root, sensor_id=1, public_key=se.public_key(),
                                   position=POS, valid_from=0, valid_to=T0 + DAY)
    assert not trust.verify_certificate(cert, other.public_key())

def test_registry_refuses_unsigned_certificate(root):
    registry = trust.Registry(root.public_key())
    forged = trust.Certificate(sensor_id=9, key_id=0, public_key=b"\x01" * 32,
                               latitude=0.0, longitude=0.0, valid_from=0, valid_to=T0,
                               signature=b"\x00" * 64)
    with pytest.raises(ValueError):
        registry.enrol(forged)

def test_active_certificate_honours_window_and_revocation(root):
    registry = trust.Registry(root.public_key())
    make_station(registry, root, sensor_id=1, valid_from=T0, valid_to=T0 + 2 * DAY)
    assert registry.active_certificate(1, T0 + DAY) is not None
    assert registry.active_certificate(1, T0 - DAY) is None        # before window
    assert registry.active_certificate(1, T0 + 5 * DAY) is None    # after window
    assert registry.active_certificate(2, T0) is None              # unknown
    registry.revoke(1)
    assert registry.active_certificate(1, T0 + DAY) is None        # revoked


# --- the verifier: the honest path -----------------------------------------

def test_accepts_a_correct_chain(setup):
    _, se, verifier = setup
    chain = Chain(se)
    for i in range(3):
        v = verifier.verify(chain.next().encode(), arrival_time=T0 + i * DAY)
        assert v.decision == trust.ACCEPT and v.reason == vfy.OK

def test_state_is_two_values_per_station(setup):
    _, se, verifier = setup
    chain = Chain(se)
    verifier.verify(chain.next().encode(), arrival_time=T0)
    st = verifier.state[1]
    assert st.last_seq == 0 and st.last_hash == chain.last.digest()


# --- the four attacks the layer must stop ----------------------------------

def test_rejects_a_modified_record(setup):
    """Flip a payload byte after signing: the signature no longer matches."""
    _, se, verifier = setup
    r = Chain(se).next()
    raw = bytearray(r.encode())
    raw[rec.HEADER_SIZE] ^= 0xFF                       # first payload byte
    v = verifier.verify(bytes(raw), arrival_time=T0)
    assert v.decision == trust.REJECT and v.reason == vfy.FORGED

def test_rejects_a_record_signed_by_the_wrong_key(setup):
    """An impostor with its own key, reusing an enrolled station's id."""
    _, _se, verifier = setup
    impostor = trust.FileSecureElement.generate()
    r = Chain(impostor, sensor_id=1).next()
    v = verifier.verify(r.encode(), arrival_time=T0)
    assert v.decision == trust.REJECT and v.reason == vfy.FORGED

def test_rejects_a_replayed_record(setup):
    _, se, verifier = setup
    chain = Chain(se)
    first = chain.next()
    verifier.verify(first.encode(), arrival_time=T0)
    verifier.verify(chain.next().encode(), arrival_time=T0 + DAY)
    replayed = verifier.verify(first.encode(), arrival_time=T0 + 2 * DAY)  # old seq again
    assert replayed.decision == trust.REJECT and replayed.reason == vfy.REPLAY

def test_rejects_reordering(setup):
    _, se, verifier = setup
    chain = Chain(se)
    r0, r1 = chain.next(), chain.next()
    verifier.verify(r1.encode(), arrival_time=T0 + DAY)      # accept the later one first
    out = verifier.verify(r0.encode(), arrival_time=T0 + 2 * DAY)
    assert out.decision == trust.REJECT and out.reason == vfy.REPLAY

def test_missing_record_is_accepted_but_flags_a_gap(setup):
    """Suppress record #1: #2 still verifies but its prev_hash reveals the hole."""
    _, se, verifier = setup
    chain = Chain(se)
    verifier.verify(chain.next().encode(), arrival_time=T0)   # #0 accepted
    chain.next()                                              # #1 built but dropped
    v = verifier.verify(chain.next().encode(), arrival_time=T0 + 2 * DAY)  # #2
    assert v.decision == trust.ACCEPT and v.reason == vfy.GAP and v.gap


# --- unknown, revoked, expired, wrong key_id -------------------------------

def test_rejects_unknown_station(setup):
    _, se, verifier = setup
    r = Chain(se, sensor_id=42).next()                        # id not enrolled
    v = verifier.verify(r.encode(), arrival_time=T0)
    assert v.decision == trust.REJECT and v.reason == vfy.UNKNOWN_STATION

def test_rejects_revoked_station(setup):
    registry, se, verifier = setup
    registry.revoke(1)
    v = verifier.verify(Chain(se).next().encode(), arrival_time=T0)
    assert v.decision == trust.REJECT and v.reason == vfy.UNKNOWN_STATION

def test_rejects_record_outside_certificate_validity(root):
    registry = trust.Registry(root.public_key())
    se = make_station(registry, root, sensor_id=1, valid_from=T0, valid_to=T0 + DAY)
    verifier = trust.Verifier(registry)
    r = Chain(se, t_start=T0 + 5 * DAY).next()                # observed after expiry
    v = verifier.verify(r.encode(), arrival_time=T0 + 5 * DAY)
    assert v.decision == trust.REJECT and v.reason == vfy.UNKNOWN_STATION

def test_rejects_wrong_key_id(root):
    registry = trust.Registry(root.public_key())
    se = make_station(registry, root, sensor_id=1, key_id=0)
    verifier = trust.Verifier(registry)
    r = Chain(se, key_id=7).next()                            # cert says key_id 0
    v = verifier.verify(r.encode(), arrival_time=T0)
    assert v.decision == trust.REJECT and v.reason == vfy.UNKNOWN_STATION


# --- timing: stale and delayed ---------------------------------------------

def test_rejects_future_dated_record(setup):
    _, se, verifier = setup
    r = Chain(se, t_start=T0 + 5 * DAY).next()
    v = verifier.verify(r.encode(), arrival_time=T0)          # arrives before it was "observed"
    assert v.decision == trust.REJECT and v.reason == vfy.STALE

def test_flags_a_delayed_record(setup):
    _, se, verifier = setup
    r = Chain(se).next()
    v = verifier.verify(r.encode(), arrival_time=T0 + 3 * DAY)  # well past cadence + margin
    assert v.decision == trust.FLAG and v.reason == vfy.DELAYED


# --- cadence watchdog ------------------------------------------------------

def test_watchdog_reports_a_silent_station(setup):
    _, se, verifier = setup
    verifier.verify(Chain(se).next().encode(), arrival_time=T0)
    assert verifier.silent_stations(now=T0 + DAY) == []            # within interval
    assert verifier.silent_stations(now=T0 + 5 * DAY) == [1]       # overdue

def test_watchdog_ignores_revoked_station(setup):
    registry, se, verifier = setup
    verifier.verify(Chain(se).next().encode(), arrival_time=T0)
    registry.revoke(1)
    assert verifier.silent_stations(now=T0 + 5 * DAY) == []


# --- tamper-evident ledger -------------------------------------------------

def test_ledger_chains_and_verifies():
    led = trust.Ledger()
    assert led.head == ledger_mod.GENESIS and len(led) == 0      # empty chain
    h0 = led.append(b"record-0")
    h1 = led.append(b"record-1")
    assert led.head == h1 and h0 != h1
    assert len(led) == 2
    assert led.verify()

def test_ledger_detects_altered_entry():
    led = trust.Ledger()
    led.append(b"a"); led.append(b"b"); led.append(b"c")
    led._entries[1] = replace(led._entries[1], payload=b"B")   # rewrite stored data
    assert not led.verify()
    assert led.first_broken() == 1                               # points at the rewrite

def test_ledger_detects_removed_entry():
    led = trust.Ledger()
    led.append(b"a"); led.append(b"b"); led.append(b"c")
    del led._entries[1]
    assert not led.verify()
