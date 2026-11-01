"""Trust score, responses and the with/without decision comparison (leave one site out).

    python scripts/run_trust.py            full grid (about 15 minutes)
    python scripts/run_trust.py --quick    20 scenarios per site, to check the setup

Results go to results/eval/trust/ (summary.md holds the tables for the report).
"""

from __future__ import annotations

import argparse
import warnings

from sensorguard import pipeline as pl
from sensorguard.eval import trust_eval


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="20 scenarios per site, written to results/eval/trust_quick")
    args = parser.parse_args(argv)
    warnings.filterwarnings("ignore")
    if args.quick:
        trust_eval.run(pl.REPO_ROOT / "results" / "eval" / "trust_quick", limit=20)
    else:
        trust_eval.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
