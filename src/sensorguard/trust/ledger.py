"""A hash-chained, tamper-evident log.

Accepted records, trust scores, actions and issued products are appended here.
Each entry stores the hash of the one before it, so anyone holding a later
chain head can prove that no earlier entry was altered or removed. This is the
defence against an attacker inside the pipeline (position P3) who rewrites
stored data *after* it was verified: the rewrite breaks the chain.

The ledger stores opaque ``bytes`` entries; callers serialise their own records
(a signed reading, a trust decision, a product) however they like.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

GENESIS = b"\x00" * 32              # prev_hash of the first entry


def _link(prev_hash: bytes, index: int, payload: bytes) -> bytes:
    """The hash binding one entry to its predecessor and its position."""
    h = hashlib.sha256()
    h.update(prev_hash)
    h.update(index.to_bytes(8, "big"))
    h.update(payload)
    return h.digest()


@dataclass(frozen=True)
class Entry:
    index: int
    payload: bytes
    prev_hash: bytes
    entry_hash: bytes


class Ledger:
    """Append-only log with a verifiable hash chain."""

    def __init__(self):
        self._entries: list[Entry] = []

    @property
    def head(self) -> bytes:
        """The hash of the last entry (``GENESIS`` when empty)."""
        return self._entries[-1].entry_hash if self._entries else GENESIS

    def __len__(self) -> int:
        return len(self._entries)

    def __getitem__(self, index: int) -> Entry:
        return self._entries[index]

    def append(self, payload: bytes) -> bytes:
        """Append an entry and return the new head hash."""
        index = len(self._entries)
        entry_hash = _link(self.head, index, payload)
        self._entries.append(Entry(index, payload, self.head, entry_hash))
        return entry_hash

    def verify(self) -> bool:
        """Recompute the whole chain; True only if nothing was altered or removed."""
        return self.first_broken() is None

    def first_broken(self) -> int | None:
        """Position of the first entry that no longer fits the chain, or None if intact."""
        prev = GENESIS
        for i, entry in enumerate(self._entries):
            if entry.index != i or entry.prev_hash != prev:
                return i
            if _link(prev, i, entry.payload) != entry.entry_hash:
                return i
            prev = entry.entry_hash
        return None
