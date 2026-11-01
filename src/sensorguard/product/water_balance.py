"""Decision product: FAO-56 reference evapotranspiration, 30-day water balance, decision levels.

Why this product.  Irrigation advice, drought classes and index-insurance
triggers are all thresholds on a water balance: how much rain fell against how
much water the crop could have lost.  An attacker who raises the station's
temperature or solar radiation raises the computed evapotranspiration, makes
the balance look drier, and can trigger an insurance payout or an irrigation
order.  This module turns a station series into that decision, so the effect
of an attack and of the defence can be measured where it matters.

ET0 (FAO-56 Penman-Monteith, daily, Allen et al. 1998, equations 6-39):

    ET0 = [0.408 D Rn + g 900/(T+273) u2 (es - ea)] / [D + g (1 + 0.34 u2)]

with T the daily mean temperature, es the saturation vapour pressure at T,
ea = RH/100 x es, u2 the wind speed, Rn the net radiation from the measured
solar radiation, the clear-sky radiation for the latitude and day of year, and
the net long-wave balance.  Simplifications, stated for the report: only the
daily mean temperature is available (FAO-56 prefers Tmax and Tmin), wind is
used as measured (no height correction), soil heat flux is 0 for daily steps,
and the elevation is 0 m unless given.

Decision level per day, from the 30-day balance B = sum(rain - ET0):

    0 normal          B at or above the dry quantile
    1 dry             B below the dry quantile           (irrigation advised)
    2 severe drought  B below the severe quantile        (insurance trigger)

The quantiles are computed per site and calendar month on the clean train
years, so "dry" means dry for that place and time of year.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SIGMA = 4.903e-9  # Stefan-Boltzmann, MJ K-4 m-2 day-1


def et0_fao56(df: pd.DataFrame, latitude: float, elevation_m: float = 0.0) -> pd.Series:
    """Daily reference evapotranspiration (mm/day) from temp_c, rh_pct, wind_ms, solar_mj_m2."""
    t = df["temp_c"].astype(float)
    rh = df["rh_pct"].astype(float).clip(0, 100)
    u2 = df["wind_ms"].astype(float).clip(lower=0)
    rs = df["solar_mj_m2"].astype(float).clip(lower=0)
    es = 0.6108 * np.exp(17.27 * t / (t + 237.3))
    ea = rh / 100.0 * es
    delta = 4098 * es / (t + 237.3) ** 2
    pressure = 101.3 * ((293 - 0.0065 * elevation_m) / 293) ** 5.26
    gamma = 0.000665 * pressure
    doy = df.index.dayofyear.to_numpy()
    phi = np.deg2rad(latitude)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    decl = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(decl), -1, 1))
    ra = 24 * 60 / np.pi * 0.0820 * dr * (ws * np.sin(phi) * np.sin(decl) + np.cos(phi) * np.cos(decl) * np.sin(ws))
    rso = (0.75 + 2e-5 * elevation_m) * ra
    rns = 0.77 * rs
    ratio = np.clip(rs / np.where(rso > 0, rso, np.nan), 0.3, 1.0)
    rnl = SIGMA * (t + 273.16) ** 4 * (0.34 - 0.14 * np.sqrt(ea.clip(lower=0))) * (1.35 * ratio - 0.35)
    rn = rns - rnl
    et0 = (0.408 * delta * rn + gamma * 900 / (t + 273) * u2 * (es - ea)) / (delta + gamma * (1 + 0.34 * u2))
    return et0.clip(lower=0).rename("et0_mm")


def water_balance(df: pd.DataFrame, latitude: float, window_days: int = 30, elevation_m: float = 0.0) -> pd.Series:
    """30-day sum of rain minus ET0 (mm); NaN until a full window of days is available."""
    daily = df["precip_mm"].astype(float) - et0_fao56(df, latitude, elevation_m)
    return daily.rolling(window_days, min_periods=window_days).sum().rename("water_balance_mm")


def fit_levels(balance: pd.Series, dry_q: float = 0.30, severe_q: float = 0.10) -> pd.DataFrame:
    """Dry and severe thresholds per calendar month, from a (clean, train-years) balance series."""
    b = balance.dropna()
    g = b.groupby(b.index.month)
    return pd.DataFrame({"dry": g.quantile(dry_q), "severe": g.quantile(severe_q)})


def decision_levels(balance: pd.Series, levels: pd.DataFrame) -> pd.Series:
    months = balance.index.month
    dry = levels["dry"].reindex(months).to_numpy()
    severe = levels["severe"].reindex(months).to_numpy()
    b = balance.to_numpy()
    out = np.where(b < severe, 2, np.where(b < dry, 1, 0)).astype(float)
    out[np.isnan(b)] = np.nan
    return pd.Series(out, index=balance.index, name="decision_level")
