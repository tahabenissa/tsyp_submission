"""Analysis tasks 1-4 for the preparation residuals."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from sensorguard.processing.calibrate import (
    fit_reference_calibration,
    load_preparation_config,
    read_cleaned_daily_table,
    season_labels,
)
from sensorguard.processing.residuals.reference import apply_reference_residuals


def _site_frames(config, site, files, input_dir):
    station = read_cleaned_daily_table(input_dir / files["station_file"])
    power = read_cleaned_daily_table(input_dir / files["power_file"])
    return station, power


def _residuals_for_fit(config, station, power, fit_start, fit_end, apply_dates):
    calib = fit_reference_calibration(station, power, config, fit_start, fit_end)
    resid = apply_reference_residuals(station, power, calib, config)
    mask = resid.index.isin(apply_dates)
    return resid.loc[mask]


def run(config_path="config/preparation.yaml", split_path="config/split.yaml"):
    config = load_preparation_config(config_path, split_path)
    input_dir = _REPO_ROOT / config["input_directory"]
    out_dir = _REPO_ROOT / config["analysis_directory"]
    if out_dir.exists():
        import shutil

        for child in out_dir.iterdir():
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
    out_dir.mkdir(parents=True, exist_ok=True)

    split = config["split"]
    train_start, train_end = split["train_start"], split["train_end"]
    val_start, val_end = split["validation_start"], split["validation_end"]
    variables = list(config["variables"])
    sites = config["sites"]
    seasons = list(config["season_definition"])
    percent = config["effect_size_percent"]

    train_dates = pd.date_range(train_start, train_end, freq="D")
    val_dates = pd.date_range(val_start, val_end, freq="D")

    task1_rows = []
    normal_resid_by_site = {}
    swapped_resid_by_site = {}
    for site, files in sites.items():
        station, power = _site_frames(config, site, files, input_dir)
        normal = _residuals_for_fit(config, station, power, train_start, train_end, val_dates)
        normal_resid_by_site[site] = normal
        swapped = _residuals_for_fit(config, station, power, val_start, val_end, train_dates)
        swapped_resid_by_site[site] = swapped
        labels_normal = season_labels(normal.index, config["season_definition"])
        labels_swapped = season_labels(swapped.index, config["season_definition"])
        for var in variables:
            for season in seasons:
                n_vals = normal.loc[labels_normal.eq(season), var].dropna()
                s_vals = swapped.loc[labels_swapped.eq(season), var].dropna()
                mn = float(n_vals.mean()) if len(n_vals) else float("nan")
                mdn = float(n_vals.median()) if len(n_vals) else float("nan")
                ms = float(s_vals.mean()) if len(s_vals) else float("nan")
                mds = float(s_vals.median()) if len(s_vals) else float("nan")

                def sgn(x):
                    if x > 0:
                        return 1
                    if x < 0:
                        return -1
                    return 0

                flips = sgn(mn) != 0 and sgn(ms) != 0 and sgn(mn) != sgn(ms)
                task1_rows.append(
                    {
                        "site": site,
                        "variable": var,
                        "season": season,
                        "mean_normal_fit2023_apply2024": mn,
                        "median_normal_fit2023_apply2024": mdn,
                        "n_normal": int(len(n_vals)),
                        "mean_swapped_fit2024_apply2023": ms,
                        "median_swapped_fit2024_apply2023": mds,
                        "n_swapped": int(len(s_vals)),
                        "sign_flips": bool(flips),
                    }
                )
    pd.DataFrame(task1_rows).to_csv(out_dir / "task1_swap_test.csv", index=False)
    # TASK 2 monthly medians of normal (fit 2023 apply 2024) residual
    task2_rows = []
    for site in sites:
        normal = normal_resid_by_site[site].copy()
        normal["month"] = normal.index.month
        for var in variables:
            g = normal.groupby("month")[var].median()
            for month, val in g.items():
                task2_rows.append(
                    {"site": site, "variable": var, "month": int(month), "median_residual": float(val)}
                )
    pd.DataFrame(task2_rows).to_csv(out_dir / "task2_monthly_medians.csv", index=False)

    for site in sites:
        normal = normal_resid_by_site[site].copy()
        normal["month"] = normal.index.month
        fig, ax = plt.subplots(figsize=(8, 4))
        for var in variables:
            g = normal.groupby("month")[var].median()
            ax.plot(g.index, g.values, marker="o", label=var)
        ax.set_xticks(range(1, 13))
        ax.set_xlabel("month")
        ax.set_ylabel("median reference residual")
        ax.set_title(f"{site}: monthly median reference residual (2024)")
        ax.legend()
        fig.tight_layout()
        fig.savefig(out_dir / f"task2_monthly_medians_{site}.png", dpi=config["plot"]["dpi"])
        plt.close(fig)

    # TASK 3 effect size
    task3_rows = []
    for site, files in sites.items():
        station, power = _site_frames(config, site, files, input_dir)
        calib_normal = fit_reference_calibration(station, power, config, train_start, train_end)
        val_station = station.loc[pd.Timestamp(val_start):pd.Timestamp(val_end)]
        for var in variables:
            mean_val_station = float(val_station[var].mean())
            spread = float(calib_normal["variables"][var]["global"]["spread"])
            effect = (percent / 100.0 * mean_val_station) / spread
            task3_rows.append(
                {
                    "site": site,
                    "variable": var,
                    "mean_validation_station_value": mean_val_station,
                    "fitted_spread": spread,
                    "percent": percent,
                    "effect_size": effect,
                }
            )
    pd.DataFrame(task3_rows).to_csv(out_dir / "task3_effect_size.csv", index=False)
    with (out_dir / "task3_formula.txt").open("w", encoding="utf-8") as f:
        f.write(
            "effect_size = (percent / 100 * mean_validation_station_value) / fitted_spread\n"
            "where percent is taken from config key 'effect_size_percent' (= %d),\n" % percent
            + "mean_validation_station_value is the mean of the station series over the validation year,\n"
            "and fitted_spread is the global fitted spread from the reference calibration fit on the training year.\n"
        )

    # TASK 4 autocorrelation lag-1 per site/variable/season (normal residual, validation year)
    task4_rows = []
    for site in sites:
        normal = normal_resid_by_site[site]
        labels = season_labels(normal.index, config["season_definition"])
        for var in variables:
            for season in seasons:
                vals = normal.loc[labels.eq(season), var].dropna()
                if len(vals) < 3:
                    ac = float("nan")
                else:
                    ac = float(vals.autocorr(lag=1))
                task4_rows.append(
                    {
                        "site": site,
                        "variable": var,
                        "season": season,
                        "lag1_autocorr": ac,
                        "n": int(len(vals)),
                    }
                )
    pd.DataFrame(task4_rows).to_csv(out_dir / "task4_autocorrelation.csv", index=False)

    print("DONE", out_dir)


if __name__ == "__main__":
    run()