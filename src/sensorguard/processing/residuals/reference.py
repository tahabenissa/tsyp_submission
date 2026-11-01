"""R3: standardized station-versus-witness residuals."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from sensorguard.processing.calibrate import season_labels, transformed_gap, witness


def apply_reference_residuals(
    station: pd.DataFrame,
    power: pd.DataFrame,
    calibration: dict[str, Any],
    config: dict[str, Any],
) -> pd.DataFrame:
    """Apply frozen per-season calibration without filling any missing values.

    A missing station or witness input yields a missing residual.  For rain,
    days where both station and POWER are at or below the rainy-day threshold
    are near dry for both sources: their residual is set to NaN because a
    dry-versus-dry gap carries no information.  The fit already excludes those
    days so that they cannot dominate the fitted offset.
    """
    power = witness(power, calibration)   # regression-modelled variables, e.g. humidity
    index = station.index.union(power.index).sort_values()
    result = pd.DataFrame(index=index)
    labels = season_labels(index, config["season_definition"])
    dry_dry_flags: dict[str, pd.Series] = {}
    for variable, settings in config["variables"].items():
        station_values = station[variable].reindex(index)
        power_values = power[variable].reindex(index)
        gap = transformed_gap(
            station_values, power_values, settings["transform"], config["log_ratio_pseudocount"]
        )
        residual = pd.Series(np.nan, index=index, dtype=float)
        for season in config["season_definition"]:
            parameters = calibration["variables"][variable]["seasons"][season]
            offset = parameters["offset"]
            spread = parameters["spread"]
            if offset is not None and spread > 0:
                mask = labels.eq(season) & gap.notna()
                residual.loc[mask] = (gap.loc[mask] - offset) / spread
        if variable == "precip_mm":
            threshold = config["rainy_day_threshold_mm"]
            dry_dry = (station_values <= threshold) & (power_values <= threshold)
            # Plain dict (no Series) so DataFrame.attrs stays comparable.
            dry_dry_flags[variable] = {date: bool(flag) for date, flag in dry_dry.items()}
            residual = residual.where(~dry_dry)
        else:
            dry_dry_flags[variable] = {}
        result[variable] = residual
    result.index.name = "date"
    result.attrs["dry_dry_flags"] = dry_dry_flags
    return result
