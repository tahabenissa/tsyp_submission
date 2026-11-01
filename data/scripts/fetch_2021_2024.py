"""Download the raw data of the three development sites, 2021-2024, into data/raw_2021_2024/.

    python data/scripts/fetch_2021_2024.py          (from the repository root)

Then clean it into the folder the pipeline reads:

    python data/scripts/clean.py data/raw_2021_2024 data/clean_2021_2024

Sources: Kansas Mesonet (Manhattan), AZMET (station az09), FAWN (Okahumpka,
15-minute observations), and NASA POWER daily at each site's coordinates.
"""
from pathlib import Path

import pandas as pd
import requests

from sensorguard.data.power import fetch_power_daily
from sensorguard.data.stations import fetch_azmet_daily, fetch_kansas_daily

START, END = "2021-01-01", "2024-12-31"
YEARS = ["2021", "2022", "2023", "2024"]
FAWN_URL = "https://fawn.ifas.ufl.edu/data/fawnpub/15_minute_obs/BY_STATION/Okahumpka_303/"

base = Path("data/raw_2021_2024")
stations_dir = base / "stations"
power_dir = base / "power"
fawn_dir = base / "fawn"

print("Kansas...")
k = fetch_kansas_daily("Manhattan", START, END, cache_dir=stations_dir)
print("Kansas rows", len(k))

print("AZMET...")
a = fetch_azmet_daily("az09", START, END, cache_dir=stations_dir)
print("AZMET rows", len(a))

print("FAWN...")
fawn_dir.mkdir(parents=True, exist_ok=True)
for year in YEARS:
    path = fawn_dir / f"{year}.csv"
    with requests.get(FAWN_URL + year + ".csv", stream=True, timeout=120) as r:
        r.raise_for_status()
        with path.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    # The yearly files can carry summary rows without a time of day: keep observations only.
    df = pd.read_csv(path, dtype=str)
    df = df[df["Date Time"].astype(str).str.contains(" ", na=False)]
    df.to_csv(path, index=False)
    print("FAWN", year, "rows", len(df))

sites = {"fawn": (28.682, -81.886), "azmet": (32.480, -109.930), "kansas": (39.209, -96.592)}
for name, (lat, lon) in sites.items():
    print("POWER", name)
    p = fetch_power_daily(lat, lon, START, END, cache_dir=power_dir)
    print("POWER rows", len(p))
print("DONE")
