"""Throwaway: download NASA POWER daily data for 3 sites into data/raw (Member 1 will replace this)."""
import sys
from pathlib import Path

import pandas as pd
import requests

OUT = Path(sys.argv[1])
PARAMS = "T2M,T2M_MAX,T2M_MIN,RH2M,WS2M,PRECTOTCORR,ALLSKY_SFC_SW_DWN"
SITES = {  # three farming climates: semi-arid, Mediterranean, irrigated valley
    "semiarid": (35.68, 10.10),
    "mediterranean": (36.73, 9.18),
    "valley": (36.60, -120.00),
}
for name, (lat, lon) in SITES.items():
    r = requests.get(
        "https://power.larc.nasa.gov/api/temporal/daily/point",
        params={"parameters": PARAMS, "community": "AG", "latitude": lat, "longitude": lon,
                "start": "20190101", "end": "20231231", "format": "JSON"},
        timeout=120,
    )
    r.raise_for_status()
    p = r.json()["properties"]["parameter"]
    df = pd.DataFrame(p)
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df.index.name = "date"
    df = df.where(df > -998)  # -999 is the fill value
    df.to_csv(OUT / f"{name}.csv")
    print(name, df.shape, int(df.isna().sum().sum()), "missing")
