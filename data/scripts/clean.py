"""Cleaning of the weather data.  Usage: python clean.py <data/raw folder> <output folder>

Rules, identical for every source:
 1. One schema: date, temp_c, rh_pct, wind_ms, precip_mm, solar_mj_m2.
 2. Full daily calendar. A missing day stays NaN: nothing is interpolated or filled.
 3. Fill codes and impossible values become NaN. Every removal is counted and printed.
 4. A daily value built from 15-min data needs >= 80 % of its readings, variable by variable.
 5. Each NASA POWER file must sit at the coordinates of a known site.
"""
import sys, json, glob, os
import numpy as np
import pandas as pd

RAW, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)

VARS = ["temp_c", "rh_pct", "wind_ms", "precip_mm", "solar_mj_m2"]
LIMITS = {"temp_c": (-40, 50), "rh_pct": (1, 100), "wind_ms": (0, 40),
          "precip_mm": (0, 300), "solar_mj_m2": (0, 40)}
LIMITS_15MIN = {"temp_c": (-40, 50), "rh_pct": (1, 100), "wind_ms": (0, 40),
                "precip_mm": (0, 100), "solar_w": (0, 1400)}
FILL_CODES = [-999, -9999, -99, 9999]

# (lat, lon) of the POWER request of each site. Longitude: west is NEGATIVE.
SITES = {"fawn": (28.682, -81.886), "azmet": (32.480, -109.930),
         "kansas": (39.209, -96.592)}

LOG = []


def clean_values(df, limits, name):
    """Fill codes and out-of-range values -> NaN. Counts are kept in LOG."""
    df = df.copy()
    for c, (lo, hi) in limits.items():
        s = df[c]
        if c == "rh_pct":                                   # tiny overshoot 100.x -> 100
            s = s.mask((s > hi) & (s <= hi + 5), hi)
        bad = s.isin(FILL_CODES) | (s.notna() & ~s.between(lo, hi))
        if c == "rh_pct":
            bad |= (s <= lo)                                # RH <= 1 % = sensor fault
        s = s.mask(bad)
        df[c] = s
        LOG.append((name, c, int(bad.sum())))
    return df


def daily_final(df, name):
    """Same output for every source: schema, full calendar, limits, no filling."""
    df = df[VARS].astype(float)
    df.index = pd.to_datetime(df.index).normalize()
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df = df.reindex(pd.date_range(df.index.min(), df.index.max(), freq="D"))
    df = clean_values(df, LIMITS, name)
    df.index.name = "date"
    return df.round(3)


def save(df, fname):
    df.reset_index().to_csv(f"{OUT}/{fname}", index=False)
    pct = (df.isna().mean() * 100).round(1).to_dict()
    print(f"{fname}: {len(df)} days {df.index.min().date()} -> {df.index.max().date()}, NaN %: {pct}")


def one(pattern):
    found = sorted(glob.glob(f"{RAW}/{pattern}"))
    if len(found) != 1:
        raise SystemExit(f"expected exactly 1 file for {pattern}, found {len(found)}")
    return found[0]


# ---------- 1. FAWN (15 min) ----------
files = sorted(glob.glob(f"{RAW}/fawn/*.csv"))
if not files:
    raise SystemExit("no FAWN files found")
f = pd.concat([pd.read_csv(p) for p in files])
if "Station ID" in f and f["Station ID"].nunique() > 1:
    raise SystemExit("FAWN files contain several stations")
f["Date Time"] = pd.to_datetime(f["Date Time"])
f = f.drop_duplicates("Date Time").sort_values("Date Time").set_index("Date Time")
f = pd.DataFrame({
    "temp_c": f["Temp @ 2m (C)"],
    "rh_pct": f["Relative Humidity (%)"],
    "wind_ms": f["Wind Speed (mph)"] * 0.44704,        # mph -> m/s
    "precip_mm": f["Rainfall Amount (in)"] * 25.4,     # inch -> mm
    "solar_w": f["Solar Radiation (w/m2)"]})
full = pd.date_range(f.index.min().normalize(),
                     f.index.max().normalize() + pd.Timedelta(hours=23, minutes=45), freq="15min")
f = f.reindex(full)                                    # gaps become visible NaN, never filled
f.index.name = "datetime"
f = clean_values(f, LIMITS_15MIN, "fawn_15min")
f.round(3).to_csv(f"{OUT}/fawn_15min_clean.csv")

g = f.resample("D")
d = pd.DataFrame({
    "temp_c": g["temp_c"].mean(), "rh_pct": g["rh_pct"].mean(), "wind_ms": g["wind_ms"].mean(),
    "precip_mm": g["precip_mm"].sum(min_count=1),
    "solar_mj_m2": g["solar_w"].mean() * 0.0864})      # mean W/m2 -> MJ/m2/day
need = 0.8 * 96
for src, dst in [("temp_c", "temp_c"), ("rh_pct", "rh_pct"), ("wind_ms", "wind_ms"),
                 ("precip_mm", "precip_mm"), ("solar_w", "solar_mj_m2")]:
    d.loc[g[src].count() < need, dst] = np.nan         # each variable needs its own 80 %
save(daily_final(d, "fawn"), "fawn_daily_clean.csv")

# ---------- 2. Kansas Mesonet (daily) ----------
k = pd.read_csv(one("stations/kansas_*.csv"), parse_dates=["TIMESTAMP"]).set_index("TIMESTAMP")
kk = pd.DataFrame({"temp_c": k["TEMP2MAVG"], "rh_pct": k["RELHUM2MAVG"], "wind_ms": k["WSPD2MAVG"],
                   "precip_mm": k["PRECIP"], "solar_mj_m2": k["SRAVG"] * 0.0864})
save(daily_final(kk, "kansas"), "kansas_daily_clean.csv")

# ---------- 3. AZMET (daily) ----------
a = pd.read_csv(one("stations/azmet_*.csv"), parse_dates=["datetime"]).set_index("datetime")
aa = a.rename(columns={"temp_air_meanC": "temp_c", "relative_humidity_mean": "rh_pct",
                       "wind_spd_mean_mps": "wind_ms", "precip_total_mm": "precip_mm",
                       "sol_rad_total": "solar_mj_m2"})
save(daily_final(aa, "azmet"), "azmet_daily_clean.csv")

# ---------- 4. NASA POWER (JSON -> CSV) ----------
ren = {"T2M": "temp_c", "RH2M": "rh_pct", "WS2M": "wind_ms",
       "PRECTOTCORR": "precip_mm", "ALLSKY_SFC_SW_DWN": "solar_mj_m2"}


def site_of(lat, lon):
    for s, (la, lo) in SITES.items():
        if abs(lat - la) < 0.05 and abs(lon - lo) < 0.05:
            return s
    for s, (la, lo) in SITES.items():
        if abs(lat - la) < 0.05 and abs(lon + lo) < 0.05:
            raise SystemExit(f"POWER file at ({lat}, {lon}) is site '{s}' with the WRONG longitude sign")
    raise SystemExit(f"POWER file at ({lat}, {lon}) matches no known site")


best = {}
for p in sorted(glob.glob(f"{RAW}/power/power_*.json")):
    j = json.load(open(p))
    lon, lat, elev = (j["geometry"]["coordinates"] + [None])[:3]
    s = site_of(lat, lon)
    n = len(j["properties"]["parameter"]["T2M"])
    if s not in best or n > best[s][0]:                # several files for one site: keep the longest
        best[s] = (n, j, lat, lon, elev)

for s, (n, j, lat, lon, elev) in best.items():
    print(f"POWER {s}: lat={lat} lon={lon} elevation={elev} m")
    df = pd.DataFrame(j["properties"]["parameter"]).rename(columns=ren)
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    unit = j.get("parameters", {}).get("ALLSKY_SFC_SW_DWN", {}).get("units", "")
    if "kW" in unit:                                   # kWh/m2/day -> MJ/m2/day
        df["solar_mj_m2"] = df["solar_mj_m2"] * 3.6
    save(daily_final(df.replace(-999, np.nan), f"power_{s}"), f"power_{lat}_{lon}_daily_clean.csv")

print("\nValues removed (fill codes / impossible values):")
for name, c, n in LOG:
    if n:
        print(f"  {name:14s} {c:12s} {n}")
print("Done. Nothing was interpolated.")