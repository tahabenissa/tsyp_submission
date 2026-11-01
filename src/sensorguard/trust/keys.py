"""Keys and the secure-element interface.

The key hierarchy has three levels:

* a **root key**, held offline by the network operator, which signs nothing but
  certificates (station enrolment, service);
* one **station key** per device, generated on the device and never leaving it;
* a **trust-service key**, which signs products.

A real station would keep its private key in a hardware secure element that
only ever exposes two operations: *sign this* and *here is my public key*. We
model that boundary with :class:`SecureElement`, so the rest of the code can
only sign and read the public key -- never read the private key. The prototype
backs it with a key file (:class:`FileSecureElement`); swapping in real
hardware means implementing the same two methods.

Public keys are passed around as the 32 raw Ed25519 bytes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

PUBLIC_KEY_SIZE = 32
PRIVATE_KEY_SIZE = 32


@runtime_checkable
class SecureElement(Protocol):
    """What a hardware secure element exposes: sign, and the public key. No more."""

    def sign(self, data: bytes) -> bytes: ...

    def public_key(self) -> bytes: ...


class FileSecureElement:
    """A file-backed secure element. The private key stays in the file and in
    this object; only :meth:`sign` and :meth:`public_key` leave it."""

    def __init__(self, private_key: ed25519.Ed25519PrivateKey):
        self._key = private_key

    @classmethod
    def generate(cls, path: str | Path | None = None) -> "FileSecureElement":
        """Create a fresh key. If ``path`` is given, write the private seed to it
        (0600 where the OS allows) so the same identity survives a restart."""
        se = cls(ed25519.Ed25519PrivateKey.generate())
        if path is not None:
            se.save(path)
        return se

    @classmethod
    def load(cls, path: str | Path) -> "FileSecureElement":
        """Load a key previously written by :meth:`save`."""
        raw = Path(path).read_bytes()
        if len(raw) != PRIVATE_KEY_SIZE:
            raise ValueError(f"key file must be {PRIVATE_KEY_SIZE} raw bytes, got {len(raw)}")
        return cls(ed25519.Ed25519PrivateKey.from_private_bytes(raw))

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.write_bytes(self._key.private_bytes_raw())
        try:
            p.chmod(0o600)              # best effort; no-op on platforms without it
        except (OSError, NotImplementedError):  # pragma: no cover - platform dependent
            pass

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data)

    def public_key(self) -> bytes:
        return self._key.public_key().public_bytes_raw()


def verify_signature(public_key: bytes, signature: bytes, data: bytes) -> bool:
    """True if ``signature`` is a valid Ed25519 signature of ``data`` by ``public_key``."""
    if len(public_key) != PUBLIC_KEY_SIZE:
        return False
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(public_key).verify(signature, data)
        return True
    except (InvalidSignature, ValueError):
        return False


# Convenient aliases: a root or service key is just a secure element whose job
# is signing certificates or products rather than readings.
def generate_root(path: str | Path | None = None) -> FileSecureElement:
    """Create the offline root key."""
    return FileSecureElement.generate(path)


def sign_record(se: SecureElement, record):
    """The sensor side: sign a record's signed region with the station key and
    return a copy carrying the 64-byte signature. ``record`` is a
    :class:`~sensorguard.trust.record.Record`; typed loosely to avoid an import
    cycle."""
    from dataclasses import replace

    return replace(record, signature=se.sign(record.signed_region()))
