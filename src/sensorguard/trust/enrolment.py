"""Enrolment certificates, the station registry and revocation.

The root key signs a **certificate** that binds a station's public key to its
identifier, **its position** and a validity window. Position is part of the
signed identity on purpose: the reference and the satellite context are looked
up by position, so a record that could claim a different place would be checked
against the wrong witnesses.

The **registry** is the operator's list of enrolled stations. A station judged
compromised is **revoked**: it stays in the registry (so its past is still
explained) but its certificate no longer validates, and the verifier rejects
its later records at L1.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .keys import SecureElement, verify_signature

# Certificate body, big-endian:
#   I sensor_id   H key_id   q valid_from   q valid_to
#   d latitude    d longitude   32s public_key
_CERT_BODY = struct.Struct(">IHqqdd32s")
CERT_SIGNATURE_SIZE = 64


@dataclass(frozen=True)
class Certificate:
    """A root-signed binding of a station key to an identity, place and lifetime."""

    sensor_id: int
    key_id: int
    public_key: bytes               # 32 raw Ed25519 bytes
    latitude: float
    longitude: float
    valid_from: int                 # unix seconds UTC, inclusive
    valid_to: int                   # unix seconds UTC, inclusive
    signature: bytes = b""          # root signature over the body

    def body(self) -> bytes:
        """The canonical bytes the root signs (everything but the signature)."""
        return _CERT_BODY.pack(
            self.sensor_id,
            self.key_id,
            self.valid_from,
            self.valid_to,
            self.latitude,
            self.longitude,
            self.public_key,
        )

    @property
    def position(self) -> tuple[float, float]:
        return (self.latitude, self.longitude)

    def covers(self, when: int) -> bool:
        """True if ``when`` (unix seconds) is inside the validity window."""
        return self.valid_from <= when <= self.valid_to


def issue_certificate(
    root: SecureElement,
    *,
    sensor_id: int,
    public_key: bytes,
    position: tuple[float, float],
    valid_from: int,
    valid_to: int,
    key_id: int = 0,
) -> Certificate:
    """Root signs a certificate for a station. The private key never appears here;
    the station hands over only its public key."""
    if len(public_key) != 32:
        raise ValueError("public_key must be 32 raw bytes")
    if valid_to < valid_from:
        raise ValueError("valid_to is before valid_from")
    lat, lon = position
    unsigned = Certificate(
        sensor_id=sensor_id,
        key_id=key_id,
        public_key=public_key,
        latitude=lat,
        longitude=lon,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    signature = root.sign(unsigned.body())
    return Certificate(**{**unsigned.__dict__, "signature": signature})


def verify_certificate(cert: Certificate, root_public_key: bytes) -> bool:
    """True if the certificate carries a valid root signature over its body."""
    return verify_signature(root_public_key, cert.signature, cert.body())


class Registry:
    """The enrolled stations, keyed by ``sensor_id``, with revocation."""

    def __init__(self, root_public_key: bytes):
        self.root_public_key = root_public_key
        self._certs: dict[int, Certificate] = {}
        self._revoked: set[int] = set()

    def enrol(self, cert: Certificate) -> None:
        """Add a station. Refuses a certificate the root did not sign."""
        if not verify_certificate(cert, self.root_public_key):
            raise ValueError("certificate is not signed by this root")
        self._certs[cert.sensor_id] = cert

    def revoke(self, sensor_id: int) -> None:
        self._revoked.add(sensor_id)

    def is_revoked(self, sensor_id: int) -> bool:
        return sensor_id in self._revoked

    def lookup(self, sensor_id: int) -> Certificate | None:
        """The certificate for a station, or ``None`` if it is unknown or revoked."""
        if sensor_id in self._revoked:
            return None
        return self._certs.get(sensor_id)

    def active_certificate(self, sensor_id: int, when: int) -> Certificate | None:
        """The station's certificate if it is known, not revoked and valid at ``when``."""
        cert = self.lookup(sensor_id)
        if cert is None or not cert.covers(when):
            return None
        return cert
