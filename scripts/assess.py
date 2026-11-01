"""File mode from the command line: a station series + coordinates in, the defence's conclusions out.

    python scripts/assess.py station.csv --lat 32.48 --lon -109.93
    python scripts/assess.py station.csv --lat 32.48 --lon -109.93 --fit-end 2023-12-31 --out results/assess/mine
    python scripts/assess.py station.csv --lat 32.48 --lon -109.93 --power power.csv     (no internet)

The CSV needs a date column and any of: temperature, humidity, wind, rain,
solar radiation (column names are recognised automatically, NASA POWER names
included; use --map temp_c=TMP to name one explicitly).  NASA POWER for the
same place and days is downloaded once and cached.

Writes daily.csv (scores, probability, trust, band, decisions), actions.csv,
episodes.csv, residuals.csv, series_used.csv and summary.csv.
"""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path

from sensorguard import assess as A


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--power", help="NASA POWER file instead of downloading")
    ap.add_argument("--fit-start"); ap.add_argument("--fit-end")
    ap.add_argument("--score-start"); ap.add_argument("--score-end")
    ap.add_argument("--map", nargs="*", default=[], help="variable=column, e.g. temp_c=TMP")
    ap.add_argument("--out", default="results/assess/latest")
    args = ap.parse_args(argv)
    warnings.filterwarnings("ignore")

    raw = A.read_table(args.csv)
    mapping = A.guess_columns(raw.columns)
    mapping.update(dict(m.split("=", 1) for m in args.map))
    date_col = A.guess_date_column(raw.columns) or raw.columns[0]
    station = A.to_daily(raw, mapping, date_col)
    print("columns:", {k: v for k, v in mapping.items() if v})
    reference = A.reference_for(args.lat, args.lon, station.index.min(), station.index.max(), args.power)
    periods = A.default_periods(station.dropna(how="all").index)
    for key, val in (("train_start", args.fit_start), ("train_end", args.fit_end),
                     ("validation_start", args.score_start), ("validation_end", args.score_end)):
        if val:
            periods[key] = val
    if args.fit_end and not args.score_start:
        import pandas as pd
        periods["validation_start"] = str((pd.Timestamp(args.fit_end) + pd.Timedelta(days=1)).date())
    result = A.assess(station, reference, args.lat, args.lon, periods, progress=lambda m: print("...", m))
    for w in result.warnings:
        print("warning:", w)
    for k, v in result.summary().items():
        print(f"{k:>42}: {v}")
    if len(result.actions):
        print(result.actions.to_string(index=False))
    print("written to", result.save(Path(args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
