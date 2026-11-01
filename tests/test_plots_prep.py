"""Tests for deterministic explanatory preparation figures."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sensorguard.processing.plots_prep import generate_explanatory_figures


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_explanatory_figures_are_created_and_deterministic(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = generate_explanatory_figures(
        artifact_directory="results/models",
        output_directory=first_root,
        site_ids=["fawn"],
    )
    second = generate_explanatory_figures(
        artifact_directory="results/models",
        output_directory=second_root,
        site_ids=["fawn"],
    )
    assert len(first) == 12
    assert len(second) == 12
    assert all(path.exists() for path in first + second)
    assert [_digest(path) for path in first] == [_digest(path) for path in second]
