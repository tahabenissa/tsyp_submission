"""Smoke tests for the analysis task runner."""
from pathlib import Path

from sensorguard.processing.calibrate import load_preparation_config


def test_analysis_outputs_exist() -> None:
    config = load_preparation_config("config/preparation.yaml", "config/split.yaml")
    out_dir = Path(config["analysis_directory"])
    assert (out_dir / "task1_full_train_reference_FAILs.csv").is_file()
    assert (out_dir / "task2_yearly_offsets.csv").is_file()
    assert (out_dir / "task3_loo_status_counts.csv").is_file()
    assert (out_dir / "task4_effect_sizes.csv").is_file()
    assert (out_dir / "task4_formula.txt").is_file()
    assert (out_dir / "preparation_rapport_final_fr.txt").is_file()
