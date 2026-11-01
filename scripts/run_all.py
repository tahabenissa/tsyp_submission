"""Reproduce the standard-scenario results: every official attack at every site.

    python scripts/run_all.py            full grid (about 15 minutes on a laptop)
    python scripts/run_all.py --quick    first 10 scenarios per site, to check the setup

Results go to results/eval/standard/ (summary.md holds the tables for the report).
"""

from __future__ import annotations

import argparse
import warnings

from sensorguard.eval.runner import run_standard


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="10 scenarios per site, written to results/eval/quick")
    parser.add_argument("--sites", nargs="*", help="only these sites")
    args = parser.parse_args(argv)
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    if args.quick:
        from sensorguard import pipeline as pl
        run_standard(pl.REPO_ROOT / "results" / "eval" / "quick", sites=args.sites, limit=10)
    else:
        run_standard(sites=args.sites)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
