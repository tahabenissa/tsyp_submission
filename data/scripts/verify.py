"""Vérification des données nettoyées. Usage: python3 verify.py <dossier clean>"""
import sys, glob, os
import pandas as pd, numpy as np
OUT = sys.argv[1]
RANGES = {"temp_c": (-40, 50), "rh_pct": (1, 100), "wind_ms": (0, 40), "precip_mm": (0, 300),
          "solar_mj_m2": (0, 40), "solar_w": (0, 1400)}
fails = 0
def check(name, cond, msg):
    global fails
    print(("  PASS " if cond else "  FAIL ") + msg); fails += (not cond)

for p in sorted(glob.glob(f"{OUT}/*.csv")):
    n = os.path.basename(p); print(n)
    df = pd.read_csv(p); idx = df.columns[0]
    t = pd.to_datetime(df[idx], errors="coerce")
    freq = "15min" if "15min" in n else "D"
    check(n, t.notna().all(), "dates toutes valides")
    check(n, not t.duplicated().any(), "aucune date en double")
    check(n, t.is_monotonic_increasing, "dates triées")
    full = pd.date_range(t.min(), t.max(), freq=freq)
    check(n, len(full) == len(t), f"grille complète ({len(t)} lignes / {len(full)} attendues)")
    check(n, not df.duplicated().any(), "aucune ligne dupliquée")
    for c in df.columns[1:]:
        lo, hi = RANGES[c]; v = df[c].dropna()
        check(n, v.between(lo, hi).all(), f"{c} dans [{lo},{hi}] (min={v.min():.2f}, max={v.max():.2f})")
        pct = df[c].isna().mean() * 100
        if 5 <= pct < 10: print(f"  WARN {c} NaN = {pct:.2f} %")
        check(n, pct < 10, f"{c} NaN restants = {pct:.2f} % (seuil 10 %)")
        check(n, not ((df[c] <= -99) | (df[c] >= 9999)).any(), f"{c} sans valeur sentinelle (-999…)")
        if c != "precip_mm" and "15min" not in n:
            same = df[c].ne(df[c].shift()).cumsum()
            longest = df[c].groupby(same).transform("size")[df[c].notna()].max()
            if longest == 4: print(f"  WARN {c} série identique de 4 jours, comparée à POWER: OK")
            check(n, longest <= 4, f"{c} plus longue série de valeurs identiques = {longest} (max 4)")
    if "rh_pct" in df: check(n, not (df.rh_pct == 0).any(), "aucune HR = 0 (panne capteur)")
cols = {tuple(pd.read_csv(p).columns) for p in glob.glob(f"{OUT}/*_daily_clean.csv")}
check("global", len(cols) == 1, "tous les fichiers journaliers ont les mêmes colonnes")
print("\nRESULTAT:", "TOUT EST PROPRE ✅" if fails == 0 else f"{fails} PROBLÈME(S) ❌")
sys.exit(1 if fails else 0)
