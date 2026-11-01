"""Tests that the preparation figure files (explain + GUI copies) are created."""

from __future__ import annotations

from pathlib import Path

from sensorguard.processing.plots_prep import generate_explanatory_figures

_FIGURE_TYPES = [
    "autocorrelation",
    "calibration_offsets",
    "check_heatmap",
    "full_vs_cold_start",
    "raw_station_power_calibrated",
    "residual_before_after",
]


def test_explanatory_figure_files_exist(tmp_path: Path) -> None:
    root = tmp_path / "out"
    created = generate_explanatory_figures(
        artifact_directory="results/models",
        output_directory=root,
        site_ids=["fawn"],
    )
    assert all(path.exists() for path in created)
    explain = root / "figures" / "explain"
    gui = root / "figures" / "gui"
    for ftype in _FIGURE_TYPES:
        assert (explain / f"fawn_{ftype}.png").is_file(), f"missing explain png: {ftype}"
        assert (explain / f"fawn_{ftype}.txt").is_file(), f"missing caption: {ftype}"
        assert (gui / f"fawn_{ftype}.png").is_file(), f"missing gui png: {ftype}"