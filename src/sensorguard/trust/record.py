"""Signed reading record: the wire format, encode and decode.

One record carries one station reading. Its layout is fixed so the overhead can
be measured exactly and so any party can parse it without a schema negotiation:

    | field       | size | purpose                                            |
    |-------------|------|----------------------------------------------------|
    | version     | 1 B  | format evolution                                   |
    | type        | 1 B  | reading / status / heartbeat                       |
    | sensor_id   | 4 B  | which station                                      |
    | key_id      | 2 B  | which station key (rotation)                       |
    | seq         | 4 B  | strictly increasing counter (ordering, replay)     |
    | t_obs       | 8 B  | observation time at the station (unix seconds UTC) |
    | prev_hash   | 32 B | SHA-256 of the previous record (the hash chain)    |
    | payload_len | 2 B  | length of the payload                              |
    | payload     | var  | the day's values, fixed-point, plus a status byte  |
    | signature   | 64 B | Ed25519 over every field above                     |

Fixed overhead is **118 bytes** (everything but the payload). The signature
covers the header and the payload, i.e. all the bytes before the signature, so
changing any field invalidates it.

The record layer treats the payload as opaque bytes. ``encode_payload`` /
``decode_payload`` are a small fixed-point codec for the common case (a handful
of named float variables plus a status byte); a station is free to use another.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

# Header up to (not including) the payload, big-endian, standard sizes.
#   B  version      B  type       I  sensor_id   H  key_id
#   I  seq          q  t_obs      32s prev_hash   H  payload_len
_HEADER = struct.Struct(">BBIHIq32sH")
HEADER_SIZE = _HEADER.size          # 54
HASH_SIZE = 32
SIGNATURE_SIZE = 64
OVERHEAD = HEADER_SIZE + SIGNATURE_SIZE   # 118 bytes, the fixed per-record cost

# Record types.
READING = 1
STATUS = 2
HEARTBEAT = 3

VERSION = 1
ZERO_HASH = b"\x00" * HASH_SIZE     # prev_hash of the first record in a chain


class MalformedRecord(ValueError):
    """Raised when bytes cannot be parsed as a well-formed record."""


@dataclass
class Record:
    """A reading record. ``signature`` is empty until the record is signed."""

    sensor_id: int
    key_id: int
    seq: int
    t_obs: int                      # unix seconds UTC
    prev_hash: bytes
    payload: bytes
    type: int = READING
    version: int = VERSION
    signature: bytes = b""

    def signed_region(self) -> bytes:
        """The bytes the signature covers: the header followed by the payload."""
        if len(self.prev_hash) != HASH_SIZE:
            raise MalformedRecord(f"prev_hash must be {HASH_SIZE} bytes")
        if not 0 <= self.payload_len <= 0xFFFF:
            raise MalformedRecord("payload too long for a 2-byte length")
        header = _HEADER.pack(
            self.version,
            self.type,
            self.sensor_id,
            self.key_id,
            self.seq,
            self.t_obs,
            self.prev_hash,
            self.payload_len,
        )
        return header + self.payload

    @property
    def payload_len(self) -> int:
        return len(self.payload)

    def encode(self) -> bytes:
        """The full record on the wire: signed region followed by the signature."""
        if len(self.signature) != SIGNATURE_SIZE:
            raise MalformedRecord("record is not signed")
        return self.signed_region() + self.signature

    def digest(self) -> bytes:
        """SHA-256 of the full encoded record: the value a successor puts in ``prev_hash``."""
        return hashlib.sha256(self.encode()).digest()


def decode(raw: bytes) -> Record:
    """Parse bytes into a :class:`Record`, or raise :class:`MalformedRecord`."""
    if len(raw) < OVERHEAD:
        raise MalformedRecord(f"record is {len(raw)} bytes, below the {OVERHEAD}-byte minimum")
    try:
        (version, rtype, sensor_id, key_id, seq, t_obs, prev_hash, payload_len) = _HEADER.unpack(
            raw[:HEADER_SIZE]
        )
    except struct.error as exc:          # pragma: no cover - guarded by the length check
        raise MalformedRecord(str(exc)) from exc
    expected = HEADER_SIZE + payload_len + SIGNATURE_SIZE
    if len(raw) != expected:
        raise MalformedRecord(
            f"length {len(raw)} does not match payload_len {payload_len} (expected {expected})"
        )
    payload = raw[HEADER_SIZE : HEADER_SIZE + payload_len]
    signature = raw[HEADER_SIZE + payload_len :]
    return Record(
        sensor_id=sensor_id,
        key_id=key_id,
        seq=seq,
        t_obs=t_obs,
        prev_hash=prev_hash,
        payload=payload,
        type=rtype,
        version=version,
        signature=signature,
    )


# --- a small fixed-point payload codec for named float variables ------------
#
# payload = status byte (1 B) + one signed int32 per variable, big-endian,
# each value stored as round(value * SCALE). The variable order is agreed out
# of band (the enrolment certificate or the schema), not carried per record.

SCALE = 1000                        # three decimal places, plenty for weather


def encode_payload(values: list[float], status: int = 0) -> bytes:
    """Encode a list of floats (in a fixed, agreed order) plus a status byte."""
    if not 0 <= status <= 0xFF:
        raise ValueError("status must fit in one byte")
    out = bytearray([status])
    for v in values:
        out += struct.pack(">i", round(v * SCALE))
    return bytes(out)


def decode_payload(payload: bytes) -> tuple[list[float], int]:
    """Inverse of :func:`encode_payload`: returns ``(values, status)``."""
    if not payload or (len(payload) - 1) % 4 != 0:
        raise MalformedRecord("payload is not a status byte plus whole int32 values")
    status = payload[0]
    ints = struct.unpack(f">{(len(payload) - 1) // 4}i", payload[1:])
    return [i / SCALE for i in ints], status
