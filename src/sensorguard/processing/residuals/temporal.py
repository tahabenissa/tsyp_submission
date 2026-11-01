"""R1: harmonic seasonal baseline plus causal autoregression."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _harmonic_design(index: pd.DatetimeIndex, order: int, period_days: float) -> np.ndarray:
    day = index.dayofyear.to_numpy(dtype=float)
    columns = [np.ones(len(index))]
    for harmonic in range(1, order + 1):
        phase = 2 * np.pi * harmonic * day / period_days
        columns.extend((np.sin(phase), np.cos(phase)))
    return np.column_stack(columns)


def _mad_spread(values: pd.Series, floor: float, mad_scale: float) -> float:
    median = values.median()
    value = (values - median).abs().median() * mad_scale
    return float(max(float(value) if pd.notna(value) else floor, floor))


def _baseline(
    index: pd.DatetimeIndex, coefficients: list[float], order: int, period_days: float
) -> pd.Series:
    return pd.Series(
        _harmonic_design(index, order, period_days) @ np.asarray(coefficients), index=index
    )


def _one_step_departures(
    values: pd.Series,
    baseline: pd.Series,
    ar_intercept: float,
    ar_coefficients: list[float],
) -> pd.Series:
    """Make causal AR predictions from observed previous-day departures only."""
    order = len(ar_coefficients)
    residual = pd.Series(np.nan, index=values.index, dtype=float)
    departure = values - baseline
    for position, date in enumerate(values.index):
        if pd.isna(values.loc[date]) or position < order:
            continue
        previous = departure.iloc[position - order : position]
        if previous.isna().any():
            continue
        prediction = baseline.loc[date] + ar_intercept + float(
            np.dot(np.asarray(ar_coefficients), previous.iloc[::-1].to_numpy())
        )
        residual.loc[date] = values.loc[date] - prediction
    return residual


def _model_values(
    values: pd.Series, settings: dict[str, Any], config: dict[str, Any]
) -> pd.Series:
    """Return the station values on the scale used by the harmonic and AR fits.

    Positive-ratio variables are log-transformed with the configured
    pseudocount before any seasonal or autoregressive term is fitted.
    """
    values = values.astype(float)
    if settings.get("transform") == "log_ratio":
        return pd.Series(
            np.log(values + config["log_ratio_pseudocount"]), index=values.index
        )
    return values


def fit_temporal_model(
    station: pd.DataFrame,
    config: dict[str, Any],
    fit_start: str | pd.Timestamp,
    fit_end: str | pd.Timestamp,
    fit_days: int | None = None,
) -> dict[str, Any]:
    """Fit seasonal and AR terms strictly on a bounded training window."""
    train = station.loc[pd.Timestamp(fit_start) : pd.Timestamp(fit_end)]
    if fit_days is not None:
        train = train.iloc[:fit_days]
    order = config["ar_order"]
    is_cold_start = fit_days is not None
    harmonic_order = int(
        config.get("cold_start_harmonic_order", 0) if is_cold_start else config["harmonic_order"]
    )
    model: dict[str, Any] = {
        "fit_start": str(train.index.min().date()) if not train.empty else None,
        "fit_end": str(train.index.max().date()) if not train.empty else None,
        "fit_calendar_days": int(len(train)),
        "mode": "cold_start" if fit_days is not None else "full_train",
        "harmonic_order": harmonic_order,
        "variables": {},
    }
    for variable, settings in config["variables"].items():
        if not settings.get("temporal_enabled", True):
            model["variables"][variable] = {
                "baseline_coefficients": None,
                "ar_intercept": 0.0,
                "ar_coefficients": [0.0] * order,
                "spread": settings["spread_floor"],
            }
            continue
        values = _model_values(train[variable], settings, config)
        design = _harmonic_design(train.index, harmonic_order, config["harmonic_period_days"])
        valid = values.notna().to_numpy()
        minimum = max(config["minimum_fit_days"], design.shape[1])
        if valid.sum() < minimum:
            model["variables"][variable] = {
                "baseline_coefficients": None,
                "ar_intercept": 0.0,
                "ar_coefficients": [0.0] * order,
                "spread": settings["spread_floor"],
            }
            continue
        coefficients = np.linalg.lstsq(design[valid], values.to_numpy()[valid], rcond=None)[0]
        baseline = _baseline(
            train.index, coefficients.tolist(), harmonic_order, config["harmonic_period_days"]
        )
        departures = values - baseline
        rows: list[list[float]] = []
        targets: list[float] = []
        for position in range(order, len(train)):
            history = departures.iloc[position - order : position]
            target = departures.iloc[position]
            if history.notna().all() and pd.notna(target):
                rows.append([1.0, *history.iloc[::-1].to_list()])
                targets.append(float(target))
        if len(rows) >= max(config["minimum_fit_days"], order + 1):
            ar_fit = np.linalg.lstsq(np.asarray(rows), np.asarray(targets), rcond=None)[0]
            ar_intercept = float(ar_fit[0])
            ar_coefficients = [float(value) for value in ar_fit[1:]]
        else:
            ar_intercept = 0.0
            ar_coefficients = [0.0] * order
        raw_residual = _one_step_departures(values, baseline, ar_intercept, ar_coefficients)
        model["variables"][variable] = {
            "baseline_coefficients": [float(value) for value in coefficients],
            "ar_intercept": ar_intercept,
            "ar_coefficients": ar_coefficients,
            "spread": _mad_spread(
                raw_residual.dropna(), settings["spread_floor"], config["mad_scale"]
            ),
        }
    return model


def apply_temporal_residuals(
    station: pd.DataFrame,
    model: dict[str, Any],
    config: dict[str, Any],
) -> pd.DataFrame:
    """Apply a train-frozen causal temporal model to all available dates."""
    result = pd.DataFrame(index=station.index)
    fit_order = model.get("harmonic_order", config["harmonic_order"])
    for variable in config["variables"]:
        settings = config["variables"][variable]
        if not settings.get("temporal_enabled", True):
            result[variable] = np.nan
            continue
        parameters = model["variables"][variable]
        coefficients = parameters["baseline_coefficients"]
        if coefficients is None:
            result[variable] = np.nan
            continue
        baseline = _baseline(
            station.index,
            coefficients,
            fit_order,
            config["harmonic_period_days"],
        )
        values = _model_values(station[variable], settings, config)
        raw_residual = _one_step_departures(
            values,
            baseline,
            parameters["ar_intercept"],
            parameters["ar_coefficients"],
        )
        result[variable] = raw_residual / parameters["spread"]
    result.index.name = "date"
    return result
