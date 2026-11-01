"""Local cache with checksums (spec F1, Q4).

Idea: every downloaded file is saved once, and its SHA-256 fingerprint is
written in a small manifest file. Next time we only use the local copy if
the fingerprint still matches. This gives:
  - no second download (the tool works offline, Q4)
  - detection of a file changed by mistake (reproducibility, Q2)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

MANIFEST_NAME = "manifest.json"


def sha256_of_bytes(content: bytes) -> str:
    """Fingerprint of some bytes."""
    return hashlib.sha256(content).hexdigest()


def sha256_of_file(path: Path) -> str:
    """Fingerprint of a file (read by blocks, fine for big files)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _read_manifest(cache_dir: Path) -> dict:
    path = cache_dir / MANIFEST_NAME
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(cache_dir: Path, manifest: dict) -> None:
    path = cache_dir / MANIFEST_NAME
    # sort_keys + indent: same content gives the same file (clean git diffs)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def save_with_checksum(
    cache_dir: str | Path, name: str, content: bytes, source: str = ""
) -> Path:
    """Save `content` as cache_dir/name and record its checksum."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / name
    path.write_bytes(content)

    manifest = _read_manifest(cache_dir)
    manifest[name] = {
        "sha256": sha256_of_bytes(content),
        "bytes": len(content),
        "source": source,
    }
    _write_manifest(cache_dir, manifest)
    return path


def load_if_valid(cache_dir: str | Path, name: str) -> Path | None:
    """Return the path of the cached file if it exists AND its checksum
    matches the manifest. Otherwise return None."""
    cache_dir = Path(cache_dir)
    path = cache_dir / name
    entry = _read_manifest(cache_dir).get(name)
    if entry is None or not path.exists():
        return None
    if sha256_of_file(path) != entry["sha256"]:
        return None
    return path