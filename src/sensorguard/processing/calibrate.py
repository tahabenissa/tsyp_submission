"""Train-only calibration and preparation-model reporting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from sensorguard import schema


# The current external clean-file contract differs from the proposal in schema.py.
# This explicit mapping is applied only at the input boundary.
SCHEMA_TO_CLEAN_COLUMN = {
    schema.TEMP: "temp_c",
    schema.HUMIDITY: "rh_pct",
    schema.WIND: "wind_ms",
    schema.RAIN: "precip_mm",
    schema.SOLAR: "solar_mj_m2",
}


def load_preparation_config(
    preparation_path: str | Path = "config/preparation.yaml",
    split_path: str | Path = "config/split.yaml",
) -> dict[str, Any]:
    """Load all preparation settings, including the time-only split."""
    with Path(preparation_path).open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    with Path(split_path).open(encoding="utf-8") as handle:
        config["split"] = yaml.safe_load(handle)
    return config


def adapt_cleaned_daily_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate the clean CSV contract and attach its explicit schema mapping.

    The public clean files deliberately retain their source-oriented labels.  The
    returned frame therefore keeps those labels; callers use this adapter rather
    than silently pretending the proposal schema has the same column names.
    """
    required = ["date", *SCHEMA_TO_CLEAN_COLUMN.values()]
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        raise ValueError(f"Clean daily table is missing columns: {missing}")
    adapted = frame.loc[:, required].copy()
    adapted["date"] = pd.to_datetime(adapted["date"], errors="raise")
    adapted = adapted.set_index("date").sort_index()
    if adapted.index.has_duplicates:
        raise ValueError("Clean daily table has duplicate dates")
    adapted.index.name = "date"
    adapted.attrs["schema_to_clean_column"] = SCHEMA_TO_CLEAN_COLUMN.copy()
    return adapted


def read_cleaned_daily_table(path: str | Path) -> pd.DataFrame:
    """Read one external clean CSV through the explicit schema adapter."""
    return adapt_cleaned_daily_table(pd.read_csv(path))


def season_labels(index: pd.DatetimeIndex, season_definition: dict[str, list[int]]) -> pd.Series:
    """Return configured season labels, preserving the supplied date index."""
    month_to_season = {
        month: season for season, months in season_definition.items() for month in months
    }
    labels = pd.Series(index.month.map(month_to_season), index=index, dtype="object")
    if labels.isna().any():
        raise ValueError("Season definition does not cover every month")
    return labels


def transformed_gap(
    station: pd.Series,
    power: pd.Series,
    transform: str,
    pseudocount: float,
) -> pd.Series:
    """Return station-minus-witness or the configured positive-value log ratio."""
    if transform == "difference":
        return station - power
    if transform == "log_ratio":
        return np.log((station + pseudocount) / (power + pseudocount))
    raise ValueError(f"Unknown residual transform: {transform}")


# --- Sharper witness: predict a station variable from several POWER variables ---
#
# NASA POWER is a ~50 km grid cell.  Its humidity follows the station much less
# closely (correlation 0.76-0.90) than its temperature (0.99), so a humidity
# attack is small compared with the normal station/POWER disagreement.  For a
# variable configured with ``reference_model: regression`` the witness is not
# POWER's own value but a ridge regression of the station value on POWER's
# humidity, temperature, dew point, rain, wind, solar and the season, fitted on
# the clean training dates only.  The per-season offset and spread are then
# fitted on top of it, exactly as for the other variables.

def _dew_point(temp_c: pd.Series, rh_pct: pd.Series) -> pd.Series:
    """Magnus formula, deg C."""
    a, b = 17.62, 243.12
    g = np.log(rh_pct.clip(1, 100) / 100.0) + a * temp_c / (b + temp_c)
    return b * g / (a - g)


def witness_features(power: pd.DataFrame) -> pd.DataFrame:
    """Same-day POWER inputs of the witness regression (no station value is used)."""
    doy = 2 * np.pi * power.index.dayofyear / 365.25
    f = pd.DataFrame(index=power.index)
    f["rh"] = power["rh_pct"]
    f["t"] = power["temp_c"]
    f["td"] = _dew_point(power["temp_c"], power["rh_pct"])
    f["rain"] = np.log1p(power["precip_mm"].clip(lower=0))
    f["wind"] = power["wind_ms"]
    f["solar"] = power["solar_mj_m2"]
    for k in (1, 2):
        f[f"cos{k}"] = np.cos(k * doy)
        f[f"sin{k}"] = np.sin(k * doy)
    for col in ("rh", "t"):
        f[f"{col}_cos1"] = f[col] * f["cos1"]
        f[f"{col}_sin1"] = f[col] * f["sin1"]
    return f


def fit_witness_model(station: pd.Series, power: pd.DataFrame, alpha: float,
                      minimum_days: int = 180) -> dict[str, Any] | None:
    """Ridge regression on standardised features, kept as plain lists so it saves to JSON."""
    x = witness_features(power)
    ok = x.notna().all(axis=1) & station.notna()
    if int(ok.sum()) < minimum_days:
        return None
    xv, yv = x[ok].to_numpy(float), station[ok].to_numpy(float)
    mean, scale = xv.mean(axis=0), xv.std(axis=0)
    scale[scale == 0] = 1.0
    z = (xv - mean) / scale
    coef = np.linalg.solve(z.T @ z + alpha * np.eye(z.shape[1]), z.T @ (yv - yv.mean()))
    return {"features": list(x.columns), "mean": mean.tolist(), "scale": scale.tolist(),
            "coef": coef.tolist(), "intercept": float(yv.mean()), "alpha": float(alpha),
            "fit_days": int(ok.sum())}


def predict_witness(model: dict[str, Any], power: pd.DataFrame) -> pd.Series:
    x = witness_features(power)[model["features"]].to_numpy(float)
    z = (x - np.asarray(model["mean"])) / np.asarray(model["scale"])
    return pd.Series(z @ np.asarray(model["coef"]) + model["intercept"], index=power.index)


def witness(power: pd.DataFrame, calibration: dict[str, Any]) -> pd.DataFrame:
    """POWER with every regression-modelled variable replaced by its prediction.

    A day where an input is missing keeps POWER's own value, so a gap in a minor
    input never removes a residual.  Humidity is kept inside 0-100 %.
    """
    models = calibration.get("witness_models") or {}
    if not any(models.values()):
        return power
    out = power.copy()
    for variable, model in models.items():
        if model is None or variable not in out:
            continue
        pred = predict_witness(model, power)
        if variable == "rh_pct":
            pred = pred.clip(0, 100)
        out[variable] = pred.where(pred.notna(), power[variable])
    return out


def _mad_spread(values: pd.Series, floor: float, mad_scale: float) -> float:
    median = values.median()
    spread = (values - median).abs().median() * mad_scale
    return float(max(float(spread) if pd.notna(spread) else floor, floor))


def _fit_one_group(
    gap: pd.Series,
    station: pd.Series,
    power: pd.Series,
    variable: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    valid = gap.notna()
    rainy_days = None
    if variable == "precip_mm":
        threshold = config["rainy_day_threshold_mm"]
        rainy_days = valid & ((station > threshold) | (power > threshold))
        valid &= rainy_days
    selected = gap.loc[valid]
    minimum = config["minimum_fit_days"]
    if len(selected) < minimum:
        return {
            "offset": None,
            "spread": config["variables"][variable]["spread_floor"],
            "fit_days": int(len(selected)),
            "rainy_days": int(rainy_days.sum()) if rainy_days is not None else None,
            "available": False,
        }
    return {
        "offset": float(selected.median()),
        "spread": _mad_spread(
            selected, config["variables"][variable]["spread_floor"], config["mad_scale"]
        ),
        "fit_days": int(len(selected)),
        "rainy_days": int(rainy_days.sum()) if rainy_days is not None else None,
        "available": True,
    }


def fit_reference_calibration(
    station: pd.DataFrame,
    power: pd.DataFrame,
    config: dict[str, Any],
    fit_start: str | pd.Timestamp,
    fit_end: str | pd.Timestamp,
    fit_days: int | None = None,
) -> dict[str, Any]:
    """Fit robust per-season station/witness gaps using only the requested dates."""
    window = power.loc[pd.Timestamp(fit_start) : pd.Timestamp(fit_end)]
    if fit_days is not None:
        window = window.iloc[:fit_days]
    witness_models: dict[str, Any] = {}
    for variable, settings in config["variables"].items():
        if settings.get("reference_model") == "regression":
            witness_models[variable] = fit_witness_model(
                station[variable].reindex(window.index), window,
                float(config.get("witness_ridge_alpha", 10.0)),
            )
    power = witness(power, {"witness_models": witness_models})
    pair = station.join(power, how="outer", lsuffix="_station", rsuffix="_power")
    train = pair.loc[pd.Timestamp(fit_start) : pd.Timestamp(fit_end)]
    if fit_days is not None:
        train = train.iloc[:fit_days]
    labels = season_labels(train.index, config["season_definition"])
    model: dict[str, Any] = {
        "fit_start": str(train.index.min().date()) if not train.empty else None,
        "fit_end": str(train.index.max().date()) if not train.empty else None,
        "fit_calendar_days": int(len(train)),
        "mode": "cold_start" if fit_days is not None else "full_train",
        "variables": {},
        "witness_models": witness_models,
    }
    for variable, settings in config["variables"].items():
        station_values = train[f"{variable}_station"]
        power_values = train[f"{variable}_power"]
        gap = transformed_gap(
            station_values, power_values, settings["transform"], config["log_ratio_pseudocount"]
        )
        global_fit = _fit_one_group(gap, station_values, power_values, variable, config)
        seasons: dict[str, Any] = {}
        for season in config["season_definition"]:
            mask = labels.eq(season)
            fitted = _fit_one_group(
                gap.loc[mask], station_values.loc[mask], power_values.loc[mask], variable, config
            )
            if not fitted["available"] and config["missing_season_fallback"] == "global":
                fitted = {**global_fit, "fallback": "global"}
            else:
                fitted["fallback"] = None
            seasons[season] = fitted
        model["variables"][variable] = {
            "transform": settings["transform"],
            "global": global_fit,
            "seasons": seasons,
        }
    return model


def _json_safe(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def save_calibration(model: dict[str, Any], path: str | Path) -> None:
    """Save a compact, reproducible calibration record."""
    target = Path(path)
    _require_new_output(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(_json_safe(model), handle, indent=2, sort_keys=True)
        handle.write("\n")


def _require_new_output(path: Path) -> None:
    """Protect an existing generated artifact from an accidental overwrite."""
    if path.exists() and path.is_file() and path.stat().st_size > 0:
        raise FileExistsError(f"Refusing to overwrite non-empty output: {path}")


def validation_diagnostics(
    residuals: pd.DataFrame,
    station: pd.DataFrame,
    config: dict[str, Any],
    mode: str,
    residual_family: str,
    covered_seasons: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Calculate the specified validation gate without altering missing values.

    When covered_seasons is given (cold-start mode), only the seasons covered by
    the cold-start training window are evaluated; the other seasons stay missing.
    """
    split = config["split"]
    validation = residuals.loc[split["validation_start"] : split["validation_end"]]
    station_validation = station.loc[validation.index]
    labels = season_labels(validation.index, config["season_definition"])
    rows: list[dict[str, Any]] = []
    for variable in config["variables"]:
        values = validation[variable]
        source = station_validation[variable]
        valid_source = source.dropna()
        if variable in ("precip_mm", "wind_ms"):
            nonzero = valid_source[valid_source != 0]
            if nonzero.empty:
                extreme = pd.Series(False, index=source.index, dtype=bool)
            else:
                lower = float(nonzero.quantile(config["extreme_tail_fraction"]))
                upper = float(nonzero.quantile(1 - config["extreme_tail_fraction"]))
                extreme = (source != 0) & ((source <= lower) | (source >= upper))
        else:
            lower = float(valid_source.quantile(config["extreme_tail_fraction"]))
            upper = float(valid_source.quantile(1 - config["extreme_tail_fraction"]))
            extreme = (source <= lower) | (source >= upper)
        valid = values.dropna()
        ordinary_sd = float(values.loc[~extreme].std(ddof=1))
        extreme_sd = float(values.loc[extreme].std(ddof=1))
        row: dict[str, Any] = {
            "mode": mode,
            "residual_family": residual_family,
            "variable": variable,
            "n": int(valid.size),
            "mean": float(valid.mean()) if not valid.empty else np.nan,
            "median": float(valid.median()) if not valid.empty else np.nan,
            "sd": float(valid.std(ddof=1)) if valid.size > 1 else np.nan,
            "ordinary_sd": ordinary_sd,
            "extreme_sd": extreme_sd,
            "extreme_ratio": (
                extreme_sd / ordinary_sd if np.isfinite(ordinary_sd) and ordinary_sd > 0 else np.nan
            ),
            "previous_day_autocorrelation": (
                float(values.corr(values.shift(1))) if residual_family == "reference" else np.nan
            ),
        }
        for season in config["season_definition"]:
            if covered_seasons is not None and season not in covered_seasons:
                row[f"{season}_mean"] = np.nan
                row[f"{season}_median"] = np.nan
                row[f"{season}_sd"] = np.nan
                continue
            seasonal = values.loc[labels.eq(season)].dropna()
            row[f"{season}_mean"] = float(seasonal.mean()) if not seasonal.empty else np.nan
            row[f"{season}_median"] = float(seasonal.median()) if not seasonal.empty else np.nan
            row[f"{season}_sd"] = float(seasonal.std(ddof=1)) if seasonal.size > 1 else np.nan
        rows.append(row)
    return rows


def _status(value: float, pass_limit: float, warn_limit: float, absolute: bool = True) -> str:
    if not np.isfinite(value):
        return "NA"
    measure = abs(value) if absolute else value
    if measure <= pass_limit:
        return "PASS"
    if measure <= warn_limit:
        return "WARN"
    return "FAIL"


def make_check_table(diagnostics: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    """Attach transparent PASS/WARN/FAIL labels to every requested metric."""
    rows: list[dict[str, Any]] = []
    for _, record in diagnostics.iterrows():
        identity = {
            key: record[key]
            for key in ("site", "mode", "residual_family", "variable")
        }
        metrics = {
            "overall_mean": record["mean"],
            "overall_median": record["median"],
            "ordinary_extreme_sd_ratio": record["extreme_ratio"],
        }
        seasonal_sds = [record[f"{season}_sd"] for season in config["season_definition"]]
        finite_sds = [value for value in seasonal_sds if np.isfinite(value) and value > 0]
        metrics["seasonal_sd_ratio"] = (
            max(finite_sds) / min(finite_sds) if len(finite_sds) == len(seasonal_sds) else np.nan
        )
        for season in config["season_definition"]:
            metrics[f"{season}_mean"] = record[f"{season}_mean"]
            metrics[f"{season}_median"] = record[f"{season}_median"]
        if record["residual_family"] == "reference":
            metrics["previous_day_autocorrelation"] = record["previous_day_autocorrelation"]
        for metric, value in metrics.items():
            limits = config["check_limits"]
            if metric == "ordinary_extreme_sd_ratio":
                verdict = _status(
                    float(value), limits["extreme_ratio_pass"], limits["extreme_ratio_warn"], absolute=False
                )
            elif metric == "seasonal_sd_ratio":
                verdict = _status(
                    float(value),
                    limits["seasonal_sd_ratio_pass"],
                    limits["seasonal_sd_ratio_warn"],
                    absolute=False,
                )
            elif metric == "previous_day_autocorrelation":
                verdict = _status(
                    float(value),
                    limits["reference_autocorrelation_pass"],
                    limits["reference_autocorrelation_warn"],
                )
            else:
                verdict = _status(
                    float(value), limits["residual_center_pass"], limits["residual_center_warn"]
                )
            rows.append({**identity, "metric": metric, "value": value, "status": verdict})
    return pd.DataFrame(rows)


def _mark_out_of_range(axis, series, ymin, ymax, color) -> None:
    """Mark points beyond the clipped range with a small triangle at the border."""
    below = series[series < ymin]
    above = series[series > ymax]
    if not below.empty:
        axis.plot(
            below.index,
            [ymin] * len(below),
            marker="v",
            linestyle="none",
            color=color,
            markersize=4,
        )
    if not above.empty:
        axis.plot(
            above.index,
            [ymax] * len(above),
            marker="^",
            linestyle="none",
            color=color,
            markersize=4,
        )


def _plot_site(
    site: str,
    residuals: pd.DataFrame,
    config: dict[str, Any],
    output_directory: Path,
    residual_family: str,
) -> None:
    """Write the requested time-series and season-histogram figures."""
    import matplotlib.pyplot as plt

    figures = output_directory / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    split = config["split"]
    labels = season_labels(residuals.index, config["season_definition"])
    variables = list(config["variables"])
    plot = config["plot"]
    low_pct, high_pct = plot["histogram_percentiles"]
    low_q = low_pct / 100.0
    high_q = high_pct / 100.0
    ymin, ymax = [float(v) for v in plot["timeseries_y_limit"]]

    # --- time series of residuals: clipped y-axis, triangles at border ---
    fig, axes = plt.subplots(len(variables), 1, figsize=(12, 2.1 * len(variables)), sharex=True)
    for axis, variable in zip(axes, variables):
        train = residuals.loc[: split["train_end"], variable].dropna()
        valid = residuals.loc[split["validation_start"] :, variable].dropna()
        axis.plot(train.index, train.clip(ymin, ymax), color="tab:blue", label="train", linewidth=0.8)
        axis.plot(valid.index, valid.clip(ymin, ymax), color="tab:orange", label="validation", linewidth=0.8)
        axis.axhline(0, color="black", linewidth=0.6)
        _mark_out_of_range(axis, train, ymin, ymax, "tab:blue")
        _mark_out_of_range(axis, valid, ymin, ymax, "tab:orange")
        axis.set_ylim(ymin, ymax)
        axis.set_ylabel(variable)
    axes[0].legend(loc="upper right")
    fig.suptitle(f"{site}: {residual_family} residuals")
    fig.tight_layout()
    time_plot = figures / f"{site}_{residual_family}_residuals.png"
    _require_new_output(time_plot)
    fig.savefig(time_plot, dpi=config["plot"]["dpi"])
    plt.close(fig)

    # --- per-season histograms: pooled percentile x-range ---
    fig, axes = plt.subplots(len(variables), 1, figsize=(12, 2.1 * len(variables)), sharex=False)
    for axis, variable in zip(axes, variables):
        pooled = residuals[variable].dropna()
        if not pooled.empty:
            lo = float(pooled.quantile(low_q))
            hi = float(pooled.quantile(high_q))
            axis.set_xlim(lo, hi)
        for season in config["season_definition"]:
            values = residuals.loc[labels.eq(season), variable].dropna()
            if not values.empty:
                outside = 0
                if not pooled.empty:
                    outside = int(((values < lo) | (values > hi)).sum())
                label = f"{season} ({outside} hors echelle)" if outside > 0 else season
                axis.hist(
                    values,
                    bins=config["plot"]["histogram_bins"],
                    alpha=0.45,
                    label=label,
                )
        axis.set_ylabel(variable)
    axes[0].legend(loc="upper right")
    fig.suptitle(f"{site}: {residual_family} residuals by season")
    fig.tight_layout()
    histogram_plot = figures / f"{site}_{residual_family}_histograms.png"
    _require_new_output(histogram_plot)
    fig.savefig(histogram_plot, dpi=config["plot"]["dpi"])
    plt.close(fig)


def run_preparation(
    preparation_path: str | Path = "config/preparation.yaml",
    split_path: str | Path = "config/split.yaml",
    site_ids: list[str] | None = None,
    write_summary: bool = True,
) -> pd.DataFrame:
    """Run calibration plus reference/temporal residual preparation only."""
    from sensorguard.processing.residuals.reference import apply_reference_residuals
    from sensorguard.processing.residuals.temporal import (
        apply_temporal_residuals,
        fit_temporal_model,
    )

    config = load_preparation_config(preparation_path, split_path)
    np.random.seed(config["random_seed"])
    input_directory = Path(config["input_directory"])
    output_directory = Path(config["output_directory"])
    output_directory.mkdir(parents=True, exist_ok=True)
    diagnostic_rows: list[dict[str, Any]] = []
    dry_dry_rows: list[dict[str, Any]] = []

    selected_sites = config["sites"]
    if site_ids is not None:
        selected_sites = {site: config["sites"][site] for site in site_ids}
    for site, files in selected_sites.items():
        station = read_cleaned_daily_table(input_directory / files["station_file"])
        power = read_cleaned_daily_table(input_directory / files["power_file"])
        split = config["split"]
        full_calibration = fit_reference_calibration(
            station, power, config, split["train_start"], split["train_end"]
        )
        cold_calibration = fit_reference_calibration(
            station,
            power,
            config,
            split["train_start"],
            split["train_end"],
            fit_days=config["cold_start_days"],
        )
        save_calibration(full_calibration, output_directory / f"{site}_calibration.json")
        save_calibration(cold_calibration, output_directory / f"{site}_calibration_cold_start.json")

        full_reference = apply_reference_residuals(station, power, full_calibration, config)
        cold_reference = apply_reference_residuals(station, power, cold_calibration, config)
        full_temporal_model = fit_temporal_model(
            station, config, split["train_start"], split["train_end"]
        )
        cold_temporal_model = fit_temporal_model(
            station,
            config,
            split["train_start"],
            split["train_end"],
            fit_days=config["cold_start_days"],
        )
        full_temporal = apply_temporal_residuals(station, full_temporal_model, config)
        cold_temporal = apply_temporal_residuals(station, cold_temporal_model, config)
        combined = pd.DataFrame(index=station.index)
        for variable in config["variables"]:
            combined[f"reference_{variable}"] = full_reference[variable]
            combined[f"temporal_{variable}"] = full_temporal[variable]
            combined[f"reference_cold_start_{variable}"] = cold_reference[variable]
            combined[f"temporal_cold_start_{variable}"] = cold_temporal[variable]
        combined.index.name = "date"
        residual_output = output_directory / f"{site}_standardized_residuals.csv"
        _require_new_output(residual_output)
        combined.to_csv(residual_output)

        dry_dry_flags = full_reference.attrs.get("dry_dry_flags", {})
        dry_labels = season_labels(full_reference.index, config["season_definition"])
        for variable, flags in dry_dry_flags.items():
            series = pd.Series(flags)
            for season in config["season_definition"]:
                dry_dry_rows.append(
                    {
                        "site": site,
                        "variable": variable,
                        "season": season,
                        "dry_dry_days": int(series.loc[dry_labels.eq(season)].sum()),
                    }
                )

        cold_fit_start = cold_calibration.get("fit_start")
        cold_fit_end = cold_calibration.get("fit_end")
        if cold_fit_start and cold_fit_end:
            cold_span = pd.date_range(cold_fit_start, cold_fit_end, freq="D")
            cold_labels = season_labels(cold_span, config["season_definition"])
            covered_seasons = [
                season for season in config["season_definition"] if season in set(cold_labels)
            ]
        else:
            covered_seasons = None
        for mode, reference, temporal, seasons in (
            ("full_train", full_reference, full_temporal, None),
            ("cold_start", cold_reference, cold_temporal, covered_seasons),
        ):
            for family, residual in (("reference", reference), ("temporal", temporal)):
                for row in validation_diagnostics(
                    residual, station, config, mode, family, seasons
                ):
                    row["site"] = site
                    diagnostic_rows.append(row)
        _plot_site(site, full_reference, config, output_directory, "reference")
        _plot_site(site, full_temporal, config, output_directory, "temporal")

    diagnostics = pd.DataFrame(diagnostic_rows)
    checks = make_check_table(diagnostics, config)
    if write_summary:
        diagnostics_output = output_directory / "validation_diagnostics.csv"
        checks_output = output_directory / "validation_checks.csv"
        _require_new_output(diagnostics_output)
        _require_new_output(checks_output)
        diagnostics.to_csv(diagnostics_output, index=False)
        checks.to_csv(checks_output, index=False)
        if dry_dry_rows:
            dry_dry_output = output_directory / "dry_dry_days.csv"
            _require_new_output(dry_dry_output)
            pd.DataFrame(dry_dry_rows).to_csv(dry_dry_output, index=False)
        summary = (
            checks.groupby(["site", "mode", "residual_family", "status"])
            .size()
            .unstack(fill_value=0)
        )
        for column in ("PASS", "WARN", "FAIL", "NA"):
            if column not in summary.columns:
                summary[column] = 0
        summary = summary.reset_index()[
            ["site", "mode", "residual_family", "FAIL", "PASS", "WARN", "NA"]
        ]
        summary_output = output_directory / "validation_check_summary.csv"
        _require_new_output(summary_output)
        summary.to_csv(summary_output, index=False)
    return checks
