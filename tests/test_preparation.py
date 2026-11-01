"""Focused tests for calibration and residual preparation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from sensorguard.processing.calibrate import (
    fit_reference_calibration,
    make_check_table,
    season_labels,
    transformed_gap,
    validation_diagnostics,
)
from sensorguard.processing.residuals.reference import apply_reference_residuals
from sensorguard.processing.residuals.temporal import apply_temporal_residuals, fit_temporal_model


def _config() -> dict:
    return {
        "random_seed": 42,
        "season_definition": {"DJF": [12, 1, 2], "MAM": [3, 4, 5], "JJA": [6, 7, 8], "SON": [9, 10, 11]},
        "variables": {
            "temp_c": {"transform": "difference", "spread_floor": 0.01},
            "rh_pct": {"transform": "difference", "spread_floor": 0.01},
            "wind_ms": {"transform": "log_ratio", "spread_floor": 0.001},
            "precip_mm": {"transform": "log_ratio", "spread_floor": 0.001},
            "solar_mj_m2": {"transform": "difference", "spread_floor": 0.01},
        },
        "log_ratio_pseudocount": 0.1,
        "rainy_day_threshold_mm": 0.1,
        "mad_scale": 1.4826,
        "minimum_fit_days": 3,
        "missing_season_fallback": "global",
    }


def _full_config() -> dict:
    return {
        **_config(),
        "check_limits": {
            "residual_center_pass": 0.25,
            "residual_center_warn": 0.50,
            "extreme_ratio_pass": 1.50,
            "extreme_ratio_warn": 2.00,
            "seasonal_sd_ratio_pass": 1.50,
            "seasonal_sd_ratio_warn": 2.00,
            "reference_autocorrelation_pass": 0.30,
            "reference_autocorrelation_warn": 0.50,
        },
        "harmonic_order": 2,
        "harmonic_period_days": 365.25,
        "ar_order": 1,
        "cold_start_harmonic_order": 0,
        "extreme_tail_fraction": 0.05,
        "split": {
            "validation_start": "2024-01-01",
            "validation_end": "2024-03-30",
        },
    }


def _daily_table(index: pd.DatetimeIndex, start: float = 1.0) -> pd.DataFrame:
    values = np.arange(len(index), dtype=float) + start
    return pd.DataFrame(
        {
            "temp_c": values,
            "rh_pct": values + 10,
            "wind_ms": values + 1,
            "precip_mm": values / 10,
            "solar_mj_m2": values + 5,
        },
        index=index,
    )


def _power_table(station: pd.DataFrame) -> pd.DataFrame:
    power = station - 0.5
    power["precip_mm"] = station["precip_mm"] * 0.8
    return power


def test_calibration_is_deterministic_with_fixed_seed() -> None:
    index = pd.date_range("2023-01-01", periods=20, freq="D")
    station = _daily_table(index)
    power = _power_table(station)
    config = _config()
    first = fit_reference_calibration(station, power, config, "2023-01-01", "2023-01-20")
    np.random.seed(config["random_seed"])
    second = fit_reference_calibration(station, power, config, "2023-01-01", "2023-01-20")
    assert first == second


def test_reference_residual_keeps_missing_input_missing() -> None:
    index = pd.date_range("2023-01-01", periods=20, freq="D")
    station = _daily_table(index)
    power = _power_table(station)
    station.loc[index[7], "temp_c"] = np.nan
    config = _config()
    fitted = fit_reference_calibration(station, power, config, "2023-01-01", "2023-01-20")
    residual = apply_reference_residuals(station, power, fitted, config)
    assert pd.isna(residual.loc[index[7], "temp_c"])


def test_temporal_residual_keeps_missing_input_missing() -> None:
    index = pd.date_range("2023-01-01", periods=20, freq="D")
    station = _daily_table(index)
    station.loc[index[7], "temp_c"] = np.nan
    config = _config() | {"harmonic_order": 1, "harmonic_period_days": 365.25, "ar_order": 1}
    fitted = fit_temporal_model(station, config, "2023-01-01", "2023-01-20")
    residual = apply_temporal_residuals(station, fitted, config)
    assert pd.isna(residual.loc[index[7], "temp_c"])


def test_fitting_does_not_use_validation_dates() -> None:
    index = pd.date_range("2023-12-20", periods=30, freq="D")
    station = _daily_table(index)
    power = _power_table(station)
    config = _config()
    baseline = fit_reference_calibration(station, power, config, "2023-12-20", "2023-12-31")
    altered_station = station.copy()
    altered_station.loc["2024-01-01":, :] = 999.0
    changed = fit_reference_calibration(altered_station, power, config, "2023-12-20", "2023-12-31")
    assert baseline == changed


def test_seasons_follow_configured_months() -> None:
    index = pd.to_datetime(["2023-01-15", "2023-04-15", "2023-07-15", "2023-10-15"])
    assert season_labels(index, _config()["season_definition"]).tolist() == ["DJF", "MAM", "JJA", "SON"]


def test_wind_and_rain_use_the_log_ratio_transform() -> None:
    index = pd.date_range("2023-01-01", periods=1, freq="D")
    station = pd.Series([3.0], index=index)
    power = pd.Series([1.0], index=index)
    expected = np.log((3.0 + 0.1) / (1.0 + 0.1))
    assert transformed_gap(station, power, "log_ratio", 0.1).iloc[0] == expected


def test_precip_mm_dry_dry_residual_is_nan_with_per_day_flag() -> None:
    index = pd.date_range("2023-01-01", periods=10, freq="D")
    station = _daily_table(index)
    station["precip_mm"] = [0.0, 0.0, 0.05, 0.2, 0.0, 0.3, 0.0, 0.4, 0.0, 0.5]
    power = _power_table(station)
    config = _full_config()
    fitted = fit_reference_calibration(station, power, config, "2023-01-01", "2023-01-10")
    residual = apply_reference_residuals(station, power, fitted, config)
    dry_dates = [index[0], index[1], index[2], index[4], index[6], index[8]]
    for date in dry_dates:
        assert pd.isna(residual.loc[date, "precip_mm"])
    for date in [index[3], index[5], index[7], index[9]]:
        assert pd.notna(residual.loc[date, "precip_mm"])
    flags = residual.attrs["dry_dry_flags"]["precip_mm"]
    assert isinstance(flags, dict)
    assert all(flags[date] for date in dry_dates)
    assert not flags[index[3]]
    series = pd.Series(flags)
    counts = series.groupby(season_labels(series.index, config["season_definition"])).sum()
    assert int(counts["DJF"]) == 6


def test_temporal_fit_uses_log_transform_before_harmonic_and_ar() -> None:
    index = pd.date_range("2023-01-01", periods=40, freq="D")
    station = _daily_table(index)
    station["wind_ms"] = 2.0
    config = _full_config()
    model = fit_temporal_model(station, config, "2023-01-01", "2023-02-09")
    coefficients = model["variables"]["wind_ms"]["baseline_coefficients"]
    expected = np.log(2.0 + config["log_ratio_pseudocount"])
    assert np.isclose(coefficients[0], expected)
    assert not np.isclose(coefficients[0], 2.0)


def test_temporal_disabled_variable_outputs_nan() -> None:
    index = pd.date_range("2023-01-01", periods=40, freq="D")
    station = _daily_table(index)
    config = _full_config()
    config["variables"] = {
        name: ({**settings, "temporal_enabled": False} if name == "precip_mm" else dict(settings))
        for name, settings in config["variables"].items()
    }
    model = fit_temporal_model(station, config, "2023-01-01", "2023-02-09")
    residual = apply_temporal_residuals(station, model, config)
    assert residual["precip_mm"].isna().all()
    assert residual["wind_ms"].notna().any()


def test_non_finite_metrics_get_na_status() -> None:
    config = _full_config()
    seasons = list(config["season_definition"])
    record = {
        "site": "s",
        "mode": "full_train",
        "residual_family": "reference",
        "variable": "temp_c",
        "n": 5,
        "mean": np.nan,
        "median": np.nan,
        "sd": np.nan,
        "ordinary_sd": np.nan,
        "extreme_sd": np.nan,
        "extreme_ratio": np.nan,
        "previous_day_autocorrelation": np.nan,
    }
    for season in seasons:
        record[f"{season}_mean"] = np.nan
        record[f"{season}_median"] = np.nan
        record[f"{season}_sd"] = np.nan
    checks = make_check_table(pd.DataFrame([record]), config)
    assert (checks["status"] == "NA").all()


def test_extreme_days_are_defined_on_nonzero_values_only() -> None:
    config = _full_config()
    index = pd.date_range("2024-01-01", periods=30, freq="D")
    station = _daily_table(index)
    station["wind_ms"] = 0.0
    residuals = pd.DataFrame(
        {variable: 0.0 for variable in config["variables"]}, index=index
    )
    diagnostics = validation_diagnostics(residuals, station, config, "full_train", "reference")
    for row in diagnostics:
        row["site"] = "s"
        row["mode"] = "full_train"
        row["residual_family"] = "reference"
    checks = make_check_table(pd.DataFrame(diagnostics), config)
    wind_ratio = checks[
        (checks["variable"] == "wind_ms") & (checks["metric"] == "ordinary_extreme_sd_ratio")
    ]
    assert wind_ratio.iloc[0]["status"] == "NA"


def test_cold_start_harmonic_order_applies_only_to_cold_start() -> None:
    index = pd.date_range("2023-01-01", periods=40, freq="D")
    station = _daily_table(index)
    config = _full_config()
    full = fit_temporal_model(station, config, "2023-01-01", "2023-02-09")
    cold = fit_temporal_model(station, config, "2023-01-01", "2023-02-09", fit_days=10)
    assert full["mode"] == "full_train"
    assert cold["mode"] == "cold_start"
    assert len(full["variables"]["temp_c"]["baseline_coefficients"]) == 1 + 2 * config["harmonic_order"]
    assert len(cold["variables"]["temp_c"]["baseline_coefficients"]) == 1 + 2 * config["cold_start_harmonic_order"]


def test_cold_start_checks_only_cover_seasons_in_training_window() -> None:
    config = _full_config()
    index = pd.date_range("2024-01-01", periods=90, freq="D")
    station = _daily_table(index)
    residuals = pd.DataFrame(0.0, index=index, columns=list(config["variables"]))
    diagnostics = validation_diagnostics(
        residuals, station, config, "cold_start", "reference", covered_seasons=["DJF", "MAM"]
    )
    for row in diagnostics:
        row["site"] = "s"
        row["mode"] = "cold_start"
        row["residual_family"] = "reference"
    checks = make_check_table(pd.DataFrame(diagnostics), config)
    subset = checks[checks["variable"] == "temp_c"]
    assert subset[subset["metric"] == "JJA_mean"].iloc[0]["status"] == "NA"
    assert subset[subset["metric"] == "SON_median"].iloc[0]["status"] == "NA"
    assert subset[subset["metric"] == "DJF_mean"].iloc[0]["status"] == "PASS"
