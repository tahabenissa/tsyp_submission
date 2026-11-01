"""Import-only checks for the Preparation view: no window may open at import."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
import yaml

_TOOLS = Path(__file__).resolve().parent.parent / "tools"


def _import_prep_view():
    if str(_TOOLS) not in sys.path:
        sys.path.insert(0, str(_TOOLS))
    import prep_view

    return prep_view


def test_prep_view_imports_without_opening_a_window():
    import tkinter as tk

    before = tk._default_root
    prep_view = _import_prep_view()
    after = tk._default_root
    assert before is None and after is None, "a window was opened at import time"
    assert hasattr(prep_view, "PreparationView")
    assert hasattr(prep_view, "load_config")
    assert hasattr(prep_view, "explain_dir")
    assert hasattr(prep_view, "checks_path")
    assert hasattr(prep_view, "discover_sites")
    assert hasattr(prep_view, "discover_figure_types")
    assert hasattr(prep_view, "_site_counts")


def test_prep_view_loads_real_config():
    prep_view = _import_prep_view()
    config = prep_view.load_config()
    assert isinstance(config, dict)
    expected = yaml.safe_load(
        (Path(__file__).resolve().parent.parent / "config" / "preparation.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert config == expected


def test_prep_view_discovered_figure_types_match_the_six_explain_types():
    prep_view = _import_prep_view()
    expected = {
        "autocorrelation",
        "calibration_offsets",
        "check_heatmap",
        "full_vs_cold_start",
        "raw_station_power_calibrated",
        "residual_before_after",
    }
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for ftype in expected:
            (folder / f"fawn_{ftype}.png").write_bytes(b"")
        types = prep_view.discover_figure_types(folder)
        assert set(types) == expected


def test_prep_view_site_counts_are_read_only():
    prep_view = _import_prep_view()
    config = prep_view.load_config()
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "validation_checks.csv"
        csv_path.write_text(
            "site,status\nfawn,PASS\nfawn,FAIL\nfawn,WARN\nfawn,NA\n",
            encoding="utf-8",
        )

        def _checks_path(_config):
            return csv_path

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(prep_view, "checks_path", _checks_path)
        counts = prep_view._site_counts(config, "fawn")
        monkeypatch.undo()
    assert set(counts) == {"PASS", "WARN", "FAIL", "NA"}
    assert all(isinstance(v, int) for v in counts.values())
    assert counts == {"PASS": 1, "WARN": 1, "FAIL": 1, "NA": 1}
