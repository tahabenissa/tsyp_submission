"""Download and verify configured NASA POWER daily reference data.

Run after the team approves entries in ``scenarios/sites.yaml``:

    python scripts/fetch_data.py
    python scripts/fetch_data.py --offline

The existing POWER client owns HTTP requests, raw response caching, and
SHA-256 verification.  This script only loads site configuration and invokes
that client once per site.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from sensorguard.data.cache import load_if_valid
from sensorguard.data.power import (
    DEFAULT_CACHE_DIR,
    fetch_power_daily,
    power_cache_name,
)
from sensorguard.data.sites import Site, load_sites


@dataclass(frozen=True)
class FetchResult:
    """One completed site acquisition, suitable for deterministic reporting."""

    site_id: str
    role: str
    start: str
    end: str
    outcome: str


def fetch_configured_sites(
    sites_path: str | Path,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    offline: bool = False,
) -> list[FetchResult]:
    """Fetch every configured site once, reporting whether each was cached.

    An existing raw file with an invalid or absent checksum is deliberately
    not replaced.  This preserves downloaded source evidence for inspection.
    """
    cache_path = Path(cache_dir)
    results: list[FetchResult] = []
    for site in load_sites(sites_path):
        name = power_cache_name(site.latitude, site.longitude, site.start, site.end)
        raw_path = cache_path / name
        cached = load_if_valid(cache_path, name)
        if raw_path.exists() and cached is None:
            raise RuntimeError(
                f"Site '{site.site_id}': cached POWER response {raw_path} has "
                "no valid checksum; refusing to overwrite raw source data."
            )
        try:
            fetch_power_daily(
                site.latitude,
                site.longitude,
                site.start,
                site.end,
                cache_dir=cache_path,
                offline=offline,
            )
        except FileNotFoundError as exc:
            if offline:
                raise FileNotFoundError(
                    f"Site '{site.site_id}': no valid cached POWER response for "
                    f"{site.start} to {site.end} in {cache_path}."
                ) from exc
            raise
        results.append(
            FetchResult(
                site_id=site.site_id,
                role=site.role,
                start=site.start,
                end=site.end,
                outcome="cached" if cached is not None else "downloaded",
            )
        )
    return results


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch configured NASA POWER daily reference data."
    )
    parser.add_argument(
        "--sites",
        type=Path,
        default=Path("scenarios/sites.yaml"),
        help="YAML site configuration (default: scenarios/sites.yaml)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="POWER raw-response cache directory (default: data/raw/power)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Never make a network request; fail if a valid cache entry is absent.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run configured acquisition and return a process exit status."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        results = fetch_configured_sites(args.sites, args.cache_dir, args.offline)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"fetch_data: {exc}\n")

    if not results:
        print(f"No approved sites configured in {args.sites}; nothing to fetch.")
        return 0

    for result in results:
        print(
            f"site={result.site_id} role={result.role} "
            f"dates={result.start}..{result.end} status={result.outcome}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
