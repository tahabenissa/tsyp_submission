"""Explanatory figures for calibration and residual preparation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
import numpy as np
import pandas as pd

from sensorguard.processing.calibrate import (
    _require_new_output,
    load_preparation_config,
    read_cleaned_daily_table,
    season_labels,
    transformed_gap,
)
from sensorguard.processing.residuals.reference import apply_reference_residuals


def _caption(path: Path, text: str) -> None:
    """Write the required single-line French caption without replacing a file."""
    _require_new_output(path)
    path.write_text(text + "\n", encoding="utf-8")


def _save_figure(figure: plt.Figure, path: Path, config: dict[str, Any]) -> None:
    _require_new_output(path)
    figure.tight_layout()
    figure.savefig(path, dpi=config["plot"]["dpi"])
    _save_gui_copy(figure, path, config)
    plt.close(figure)


def _save_gui_copy(figure: plt.Figure, path: Path, config: dict[str, Any]) -> None:
    """Save a smaller copy of the figure for the GUI in the gui/ subfolder."""
    plot = config["plot"]
    gui_dir = path.parent.parent / plot.get("gui_subfolder", "gui")
    gui_dir.mkdir(parents=True, exist_ok=True)
    gui_path = gui_dir / path.name
    _require_new_output(gui_path)
    width_in, height_in = figure.get_size_inches()
    gui_width = float(plot.get("gui_figure_width", width_in))
    gui_height = height_in * (gui_width / width_in)
    figure.set_size_inches(gui_width, gui_height)
    figure.tight_layout()
    figure.savefig(gui_path, dpi=float(plot.get("gui_dpi", config["plot"]["dpi"])))


def _explain_directory(output_directory: Path, config: dict[str, Any]) -> Path:
    directory = output_directory / config["plot"]["explain_directory"]
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _calibrated_station(
    station: pd.Series,
    calibration: dict[str, Any],
    variable: str,
    config: dict[str, Any],
) -> pd.Series:
    """Map station values onto the POWER scale using frozen seasonal offsets."""
    labels = season_labels(station.index, config["season_definition"])
    corrected = pd.Series(np.nan, index=station.index, dtype=float)
    transform = config["variables"][variable]["transform"]
    pseudocount = config["log_ratio_pseudocount"]
    for season in config["season_definition"]:
        offset = calibration["variables"][variable]["seasons"][season]["offset"]
        mask = labels.eq(season) & station.notna()
        if offset is None:
            continue
        if transform == "difference":
            corrected.loc[mask] = station.loc[mask] - offset
        else:
            corrected.loc[mask] = (station.loc[mask] + pseudocount) / np.exp(offset) - pseudocount
    return corrected


def _validation_before_after(
    station: pd.DataFrame,
    power: pd.DataFrame,
    calibration: dict[str, Any],
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pre-offset and post-offset standardized reference residuals.

    Both residuals come from apply_reference_residuals: the pre-offset residual
    is obtained by applying the frozen calibrator with every seasonal offset
    zeroed, so no residual is recomputed by hand here.
    """
    split = config["split"]
    window = (
        station.index >= pd.Timestamp(split["validation_start"])
    ) & (station.index <= pd.Timestamp(split["validation_end"]))
    station_validation = station.loc[window]
    power_validation = power.loc[window]
    frozen = deepcopy(calibration)
    for variable in config["variables"]:
        for season in config["season_definition"]:
            frozen["variables"][variable]["seasons"][season]["offset"] = 0.0
    before = apply_reference_residuals(station_validation, power_validation, frozen, config)
    after = apply_reference_residuals(station_validation, power_validation, calibration, config)
    return before, after


def _diagnostic_row(
    diagnostics: pd.DataFrame,
    site: str,
    mode: str,
    family: str,
    variable: str,
) -> pd.Series:
    selected = diagnostics.loc[
        (diagnostics["site"] == site)
        & (diagnostics["mode"] == mode)
        & (diagnostics["residual_family"] == family)
        & (diagnostics["variable"] == variable)
    ]
    if len(selected) != 1:
        raise ValueError(f"Expected one diagnostics row for {site}, {mode}, {family}, {variable}")
    return selected.iloc[0]


def _raw_station_power_figure(
    site: str,
    station: pd.DataFrame,
    power: pd.DataFrame,
    calibration: dict[str, Any],
    config: dict[str, Any],
    directory: Path,
) -> None:
    variables = list(config["variables"])
    plot = config["plot"]
    figure, axes = plt.subplots(
        len(variables),
        1,
        figsize=(plot["figure_width"], plot["row_height"] * len(variables)),
        sharex=True,
    )
    for axis, variable in zip(axes, variables):
        axis.plot(
            station.index,
            station[variable],
            color=plot["raw_station_color"],
            linewidth=plot["line_width"],
            label="Station",
        )
        axis.plot(
            power.index,
            power[variable],
            color=plot["raw_power_color"],
            linewidth=plot["line_width"],
            label="NASA POWER",
        )
        axis.plot(
            station.index,
            _calibrated_station(station[variable], calibration, variable, config),
            color=plot["calibrated_station_color"],
            linewidth=plot["line_width"],
            label="Station calibree",
        )
        axis.set_ylabel(config["variable_labels"][variable])
        axis.grid(alpha=plot["grid_alpha"])
    axes[0].legend()
    axes[-1].set_xlabel("Date")
    figure.suptitle(f"{site}: station, NASA POWER et station calibree")
    output = directory / f"{site}_raw_station_power_calibrated.png"
    _save_figure(figure, output, config)
    _caption(
        output.with_suffix(".txt"),
        f"{site} : la courbe verte montre la station ramenee vers le niveau habituel de NASA POWER.",
    )


def _offset_figure(
    site: str,
    calibration: dict[str, Any],
    config: dict[str, Any],
    directory: Path,
) -> None:
    variables = list(config["variables"])
    seasons = list(config["season_definition"])
    plot = config["plot"]
    positions = np.arange(len(seasons))
    figure, axes = plt.subplots(
        len(variables),
        1,
        figsize=(plot["figure_width"], plot["row_height"] * len(variables)),
        sharex=True,
    )
    for axis, variable in zip(axes, variables):
        parameters = calibration["variables"][variable]["seasons"]
        offsets = [parameters[season]["offset"] for season in seasons]
        spreads = [parameters[season]["spread"] for season in seasons]
        axis.bar(
            positions,
            offsets,
            yerr=spreads,
            width=plot["bar_width"],
            color=plot["calibrated_station_color"],
            capsize=plot["bar_width"] * plot["figure_width"],
        )
        axis.axhline(0, color=plot["zero_line_color"], linewidth=plot["line_width"])
        axis.set_ylabel(config["variable_offset_labels"][variable])
        axis.grid(axis="y", alpha=plot["grid_alpha"])
    axes[-1].set_xticks(positions, seasons)
    axes[-1].set_xlabel("Saison")
    figure.suptitle(f"{site}: ecart normal calibre par saison")
    output = directory / f"{site}_calibration_offsets.png"
    _save_figure(figure, output, config)
    _caption(
        output.with_suffix(".txt"),
        f"{site} : chaque barre est l'ecart median appris et chaque barre d'erreur est sa dispersion robuste.",
    )


def _before_after_figure(
    site: str,
    station: pd.DataFrame,
    power: pd.DataFrame,
    calibration: dict[str, Any],
    config: dict[str, Any],
    directory: Path,
) -> None:
    before, after = _validation_before_after(station, power, calibration, config)
    variables = list(config["variables"])
    plot = config["plot"]
    low_pct, high_pct = plot["histogram_percentiles"]
    low_q = low_pct / 100.0
    high_q = high_pct / 100.0
    figure, axes = plt.subplots(
        len(variables),
        2,
        figsize=(plot["figure_width"], plot["row_height"] * len(variables)),
    )
    for row, variable in enumerate(variables):
        pooled = pd.concat((before[variable], after[variable])).dropna()
        if not pooled.empty:
            lo = float(pooled.quantile(low_q))
            hi = float(pooled.quantile(high_q))
        else:
            lo = hi = 0.0
        histogram_range = (lo, hi)
        for column, (title, series, color) in enumerate(
            (
                ("Avant calibration", before[variable], plot["before_color"]),
                ("Apres calibration", after[variable], plot["after_color"]),
            )
        ):
            axis = axes[row, column]
            series_values = series.dropna()
            outside = int(((series_values < lo) | (series_values > hi)).sum())
            suffix = "jour" if outside == 1 else "jours"
            axis.hist(
                series_values,
                bins=plot["histogram_bins"],
                range=histogram_range,
                color=color,
                alpha=plot["histogram_alpha"],
            )
            axis.axvline(0, color=plot["zero_line_color"], linewidth=plot["line_width"])
            axis.set_title(f"{title} ({outside} {suffix} hors echelle)")
            axis.set_xlabel("Residu standardise (sans unite)")
            axis.set_ylabel(f"Nombre de jours — {config['variable_labels'][variable]}")
            axis.grid(axis="y", alpha=plot["grid_alpha"])
    figure.suptitle(f"{site}: residus de validation avant et apres calibration")
    output = directory / f"{site}_residual_before_after.png"
    _save_figure(figure, output, config)
    _caption(
        output.with_suffix(".txt"),
        f"{site} : les deux histogrammes utilisent la meme echelle pour montrer le recentrage apporte par la calibration.",
    )


def _full_cold_figure(
    site: str,
    diagnostics: pd.DataFrame,
    config: dict[str, Any],
    directory: Path,
) -> None:
    variables = list(config["variables"])
    seasons = list(config["season_definition"])
    plot = config["plot"]
    family = plot["explanatory_residual_family"]
    sd_ymax = float(plot["sd_ymax"])
    positions = np.arange(len(seasons))
    figure, axes = plt.subplots(
        len(variables),
        2,
        figsize=(plot["figure_width"], plot["row_height"] * len(variables)),
    )
    for row, variable in enumerate(variables):
        full = _diagnostic_row(diagnostics, site, "full_train", family, variable)
        cold = _diagnostic_row(diagnostics, site, "cold_start", family, variable)
        for column, (metric, label) in enumerate(
            (("mean", "Moyenne du residu standardise"), ("sd", "Ecart-type du residu standardise"))
        ):
            axis = axes[row, column]
            full_values = [full[f"{season}_{metric}"] for season in seasons]
            cold_values = [cold[f"{season}_{metric}"] for season in seasons]
            axis.bar(
                positions - plot["bar_width"] / 2,
                full_values,
                width=plot["bar_width"],
                color=plot["full_train_color"],
                label="Train complet",
            )
            axis.bar(
                positions + plot["bar_width"] / 2,
                cold_values,
                width=plot["bar_width"],
                color=plot["cold_start_color"],
                label="Demarrage rapide",
            )
            ideal = 0.0 if metric == "mean" else 1.0
            axis.axhline(ideal, color=plot["zero_line_color"], linewidth=plot["line_width"])
            if metric == "sd":
                axis.set_ylim(0.0, sd_ymax)
            ymin_axis, ymax_axis = axis.get_ylim()
            for x, value in zip(positions - plot["bar_width"] / 2, full_values):
                if value > ymax_axis:
                    axis.text(
                        x,
                        ymax_axis,
                        f"{value:.2f}",
                        ha="center",
                        va="bottom",
                        fontsize=7,
                        color=plot["full_train_color"],
                    )
            for x, value in zip(positions + plot["bar_width"] / 2, cold_values):
                if value > ymax_axis:
                    axis.text(
                        x,
                        ymax_axis,
                        f"{value:.2f}",
                        ha="center",
                        va="bottom",
                        fontsize=7,
                        color=plot["cold_start_color"],
                    )
            axis.set_ylabel(f"{label} — {config['variable_labels'][variable]}")
            axis.set_xticks(positions, seasons)
            axis.grid(axis="y", alpha=plot["grid_alpha"])
            if row == 0:
                axis.legend()
    axes[-1, 0].set_xlabel("Saison")
    axes[-1, 1].set_xlabel("Saison")
    figure.suptitle(f"{site}: train complet face au demarrage rapide")
    output = directory / f"{site}_full_vs_cold_start.png"
    _save_figure(figure, output, config)
    _caption(
        output.with_suffix(".txt"),
        f"{site} : les barres comparent les residus de validation apres une annee complete et apres le demarrage rapide.",
    )


def _heatmap_figure(
    site: str,
    checks: pd.DataFrame,
    config: dict[str, Any],
    directory: Path,
) -> None:
    """Calibration check status per variable and season, written as words.

    One panel per mode (full train, cold start).  Rows list every variable
    plus its seasonal SD ratio and its lag-1 autocorrelation; each cell shows
    PASS, WARN, FAIL or NA.
    """
    variables = list(config["variables"])
    seasons = list(config["season_definition"])
    plot = config["plot"]
    family = plot["explanatory_residual_family"]
    status_score = plot["status_scores"]
    words = ["FAIL", "WARN", "PASS", "NA"]
    colors = [
        plot["heatmap_fail_color"],
        plot["heatmap_warn_color"],
        plot["heatmap_pass_color"],
        plot["heatmap_na_color"],
    ]
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5], len(colors))
    modes = (("full_train", "Train complet"), ("cold_start", "Demarrage rapide"))

    def status_for(mode: str, variable: str, metric: str) -> str:
        selected = checks.loc[
            (checks["site"] == site)
            & (checks["mode"] == mode)
            & (checks["residual_family"] == family)
            & (checks["variable"] == variable)
            & (checks["metric"] == metric)
        ]
        if len(selected) != 1:
            return "NA"
        status_value = selected.iloc[0]["status"]
        if pd.isna(status_value):
            return "NA"
        return str(status_value)

    def seasonal_status(mode: str, variable: str, season: str) -> str:
        scores = [
            status_score[status_for(mode, variable, f"{season}_{metric}")]
            for metric in plot["heatmap_metrics"]
        ]
        return words[min(scores)]

    row_labels: list[str] = []
    matrices: dict[str, list[list[float]]] = {}
    for variable in variables:
        label = config["variable_labels"][variable]
        row_labels.append(label)
        row_labels.append(f"{label} - ratio SD saisonniere")
        row_labels.append(f"{label} - autocorrelation avec la veille")
    for mode, _title in modes:
        matrix: list[list[float]] = []
        for variable in variables:
            label = config["variable_labels"][variable]
            matrix.append(
                [status_score[seasonal_status(mode, variable, season)] for season in seasons]
            )
            sd_status = status_for(mode, variable, "seasonal_sd_ratio")
            matrix.append([status_score[sd_status]] * len(seasons))
            ac_status = status_for(mode, variable, "previous_day_autocorrelation")
            matrix.append([status_score[ac_status]] * len(seasons))
        matrices[mode] = matrix

    figure, axes = plt.subplots(
        1,
        2,
        figsize=(plot["figure_width"] * 2, plot["row_height"] * len(row_labels)),
        sharey=True,
    )
    for axis, (mode, title) in zip(axes, modes):
        scores = np.asarray(matrices[mode], dtype=float)
        image = axis.imshow(scores, cmap=ListedColormap(colors), norm=norm, aspect="auto")
        axis.set_xticks(np.arange(len(seasons)), seasons)
        axis.set_yticks(np.arange(len(row_labels)), row_labels)
        axis.tick_params(axis="y", labelsize=7)
        axis.set_xlabel("Saison")
        axis.set_title(f"{site}: {title}")
        for row in range(len(row_labels)):
            for column in range(len(seasons)):
                axis.text(
                    column,
                    row,
                    words[int(scores[row, column])],
                    ha="center",
                    va="center",
                    color=plot["heatmap_text_color"],
                )
    axes[0].set_ylabel("Variable / indicateur (unite)")
    figure.colorbar(image, ax=axes, ticks=[0, 1, 2, 3]).ax.set_yticklabels(words)
    output = directory / f"{site}_check_heatmap.png"
    _save_figure(figure, output, config)
    _caption(
        output.with_suffix(".txt"),
        f"{site} : chaque cellule est le pire statut de la saison (PASS, WARN, FAIL ou NA) pour le residu de reference, en train complet et en demarrage rapide ; NA signifie un indicateur non defini ou une saison non couverte par l'entrainement du demarrage rapide.",
    )


def _autocorrelation_figure(
    site: str,
    diagnostics: pd.DataFrame,
    config: dict[str, Any],
    directory: Path,
) -> None:
    variables = list(config["variables"])
    plot = config["plot"]
    values = [
        _diagnostic_row(
            diagnostics, site, plot["heatmap_mode"], plot["heatmap_residual_family"], variable
        )["previous_day_autocorrelation"]
        for variable in variables
    ]
    positions = np.arange(len(variables))
    figure, axis = plt.subplots(figsize=(plot["figure_width"], plot["row_height"] * 2))
    axis.bar(positions, values, color=plot["raw_station_color"], width=plot["bar_width"])
    axis.axhline(0, color=plot["zero_line_color"], linewidth=plot["line_width"])
    axis.axhline(
        config["check_limits"]["reference_autocorrelation_pass"],
        color=plot["heatmap_pass_color"],
        linewidth=plot["line_width"],
        label="Limite PASS",
    )
    axis.axhline(
        config["check_limits"]["reference_autocorrelation_warn"],
        color=plot["heatmap_warn_color"],
        linewidth=plot["line_width"],
        label="Limite WARN",
    )
    axis.set_xticks(positions, [config["variable_labels"][variable] for variable in variables], rotation=20, ha="right")
    axis.set_xlabel("Variable (unite)")
    axis.set_ylabel("Autocorrelation avec la veille (sans unite)")
    axis.set_ylim(plot["autocorrelation_ymin"], plot["autocorrelation_ymax"])
    axis.set_title(f"{site}: memoire du residu de reference")
    axis.grid(axis="y", alpha=plot["grid_alpha"])
    axis.legend()
    output = directory / f"{site}_autocorrelation.png"
    _save_figure(figure, output, config)
    _caption(
        output.with_suffix(".txt"),
        f"{site} : une barre haute signifie que le residu ressemble encore beaucoup au residu de la veille.",
    )


def generate_explanatory_figures(
    preparation_path: str | Path = "config/preparation.yaml",
    split_path: str | Path = "config/split.yaml",
    artifact_directory: str | Path | None = None,
    output_directory: str | Path | None = None,
    site_ids: list[str] | None = None,
) -> list[Path]:
    """Generate six explanatory calibration figures and captions per configured site."""
    config = load_preparation_config(preparation_path, split_path)
    np.random.seed(config["random_seed"])
    artifact_root = Path(artifact_directory or config["output_directory"])
    output_root = Path(output_directory or artifact_root)
    explain = _explain_directory(output_root, config)
    diagnostics = pd.read_csv(artifact_root / "validation_diagnostics.csv")
    checks_path = artifact_root / "validation_checks_with_seasonal_spread.csv"
    if not checks_path.exists():
        checks_path = artifact_root / "validation_checks.csv"
    # keep_default_na=False so that the literal "NA" status stays a string.
    checks = pd.read_csv(checks_path, keep_default_na=False)
    created: list[Path] = []

    selected_sites = config["sites"]
    if site_ids is not None:
        selected_sites = {site: config["sites"][site] for site in site_ids}
    for site, files in selected_sites.items():
        station = read_cleaned_daily_table(Path(config["input_directory"]) / files["station_file"])
        power = read_cleaned_daily_table(Path(config["input_directory"]) / files["power_file"])
        with (artifact_root / f"{site}_calibration.json").open(encoding="utf-8") as handle:
            calibration = json.load(handle)
        _raw_station_power_figure(site, station, power, calibration, config, explain)
        _offset_figure(site, calibration, config, explain)
        _before_after_figure(site, station, power, calibration, config, explain)
        _full_cold_figure(site, diagnostics, config, explain)
        _heatmap_figure(site, checks, config, explain)
        _autocorrelation_figure(site, diagnostics, config, explain)
        for suffix in (
            "raw_station_power_calibrated",
            "calibration_offsets",
            "residual_before_after",
            "full_vs_cold_start",
            "check_heatmap",
            "autocorrelation",
        ):
            created.extend((explain / f"{site}_{suffix}.png", explain / f"{site}_{suffix}.txt"))
    return created


if __name__ == "__main__":
    generate_explanatory_figures()
