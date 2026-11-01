"""Plot one example of each official attack: clean vs attacked, with the labelled days shaded.

Usage: python tools/plot_attacks.py <data name> <output png>
Needs the three attacks already run on that data (mingw32-make attack-data DATA=<name>).
"""
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

data, out = sys.argv[1], sys.argv[2]
clean = pd.read_csv(f"data/raw/{data}.csv", index_col=0, parse_dates=True)
cases = [
    ("step", "T2M-up-value-seed0", "T2M", "12 % step on T2M"),
    ("drift", "T2M-up-value-ramp90-seed0", "T2M", "Drift to 15 % over 90 days on T2M"),
    ("replay", "back364-seed0", "ALLSKY_SFC_SW_DWN", "7-day replay (same week last year), solar radiation"),
]
fig, axes = plt.subplots(3, 1, figsize=(11, 9))
for ax, (attack, run, var, title) in zip(axes, cases):
    d = f"results/attacks/{data}/{attack}/{run}"
    att = pd.read_csv(f"{d}/attacked.csv", index_col=0, parse_dates=True)
    lab = pd.read_csv(f"{d}/labels.csv", index_col=0, parse_dates=True)
    on = lab.index[lab.attacked]
    w = slice(on[0] - pd.Timedelta(days=40), on[-1] + pd.Timedelta(days=40))
    ax.plot(clean.loc[w, var], label="clean", lw=1.2)
    ax.plot(att.loc[w, var], label="attacked", lw=1.2, ls="--")
    ax.axvspan(on[0], on[-1], color="red", alpha=0.12, label="labelled as attacked")
    ax.set_title(f"{data}: {title}")
    ax.legend(loc="upper left", fontsize=8)
fig.tight_layout()
fig.savefig(out, dpi=90)
print(f"plot saved to {out}")
