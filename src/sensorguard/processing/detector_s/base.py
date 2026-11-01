"""Statistical detector S for sensor-guard residual streams.

Pure numpy/scipy implementation.  No machine learning, no fusion, no confidence
score, no attack generator.  Output always uses the shared date/score/flag
format and is written only to results/detector_s.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg", force=True)

__all__ = ["Detector", "load_detector_config"]

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


def repo_root() -> Path:
    """Best-effort path to the repository root (risky import-free)."""
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "config" / "preparation.yaml").exists():
        return candidate
    return Path.cwd()


REPO_ROOT = repo_root()
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "detector_s.yaml"


def load_detector_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load detector S settings.  File-system writes remain prohibited here."""
    path = Path(path)
    with path.open(encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    cfg.setdefault("output_directory", "results/detector_s")
    cfg.setdefault("figures_directory", "results/detector_s/figures")
    cfg.setdefault("standardized_residual_directory", "results/models_2021_2024")
    cfg.setdefault("config_path", str(path))
    cfg.setdefault(
        "false_alarm_target",
        0.01,
    )
    cfg.setdefault("alarm_warn_rate_multiple", 2.0)
    cfg.setdefault("alarm_fail_rate_multiple", 3.0)
    cfg.setdefault("alarm_max_distinct_episodes", 3)
    cfg.setdefault(
        "variables",
        ["temp_c", "rh_pct", "wind_ms", "precip_mm", "solar_mj_m2"],
    )
    cfg.setdefault("residual_variables", {})
    cfg["output_directory"] = Path(cfg["output_directory"]).resolve()
    cfg["figures_directory"] = Path(cfg["figures_directory"]).resolve()
    return cfg


def get(cfg: dict[str, Any], key: str, default: Any = None) -> Any:
    """Read a config value; a dotted key such as ``"mahalanobis.quantile"`` walks nested sections."""
    node: Any = cfg
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def variables(cfg: dict[str, Any]) -> list[str]:
    return list(cfg.get("variables", []))


def monitored_variables(cfg: dict[str, Any]) -> list[str]:
    """Variables the detectors actually score for a run.

    Defaults to the full ``variables`` list.  ``precip_mm`` is excluded: it is
    NaN on dry-dry days and would otherwise blind every detector on those days.
    Use this everywhere (not ``variables``) when choosing which columns to
    score and which degrees of freedom a chi-square threshold should carry.
    """
    return list(cfg.get("monitored_variables", variables(cfg)))


def residual_columns(cfg: dict[str, Any]) -> dict[str, str]:
    """Explicit mapping from logical variable to the written standardized residual column."""
    explicit = cfg.get("residual_variables")
    if explicit:
        return {str(k): str(v) for k, v in explicit.items()}
    return {var: f"reference_{var}" for var in monitored_variables(cfg)}



def resolve_site_residuals(site: str, cfg: dict[str, Any]) -> Path:
    return Path(cfg["standardized_residual_directory"]) / f"{site}_standardized_residuals.csv"


def read_residuals(site: str, cfg: dict[str, Any]) -> pd.DataFrame:
    path = resolve_site_residuals(site, cfg)
    if not path.exists():
        raise FileNotFoundError(f"Missing standardized residual file: {path}")
    df = pd.read_csv(path, index_col="date", parse_dates=True)
    missing = [v for v in residual_columns(cfg).values() if v not in df.columns]
    if missing:
        raise ValueError(f"Residual file {path} is missing columns: {missing}")
    df = df.sort_index()
    if df.index.has_duplicates:
        raise ValueError(f"Residual file {path} has duplicate dates")
    df.index.name = "date"
    return df


def _require_new_output(path: Path) -> None:
    """Refuse to overwrite an existing non-empty generated artifact."""
    if path.exists() and path.is_file() and path.stat().st_size > 0:
        raise FileExistsError(f"Refusing to overwrite non-empty output: {path}")


def ensure_output_directory(cfg: dict[str, Any]) -> None:
    cfg["output_directory"].mkdir(parents=True, exist_ok=True)
    cfg["figures_directory"].mkdir(parents=True, exist_ok=True)


def write_daily_csv(df: pd.DataFrame, path: Path) -> None:
    _require_new_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=True)


def _status_from_rate(rate: float, episodes: int, cfg: dict[str, Any]) -> str:
    target = float(cfg.get("false_alarm_target", 0.01))
    if not np.isfinite(rate) or rate < 0:
        return "NA"
    if rate <= target:
        return "PASS"
    if rate <= target * float(cfg.get("alarm_warn_rate_multiple", 2.0)):
        return "WARN"
    if episodes <= int(cfg.get("alarm_max_distinct_episodes", 3)):
        return "WARN"
    return "FAIL"


def _finite_or_nan(value: float) -> float:
    value = float(value)
    return value if np.isfinite(value) else np.nan


class Detector:
    """Base contract for every Statistical detector S test.

    ``name`` is a class attribute: each subclass sets its own.
    """

    name = "detector"

    def fit(self, train: pd.DataFrame, cfg: dict[str, Any]) -> Any:
        raise NotImplementedError(f"{self.name}.fit is not implemented")

    def score(self, test: pd.DataFrame, params: Any, cfg: dict[str, Any]) -> pd.DataFrame:
        """Return one row per day: date, score, flag."""
        raise NotImplementedError(f"{self.name}.score is not implemented")

    def per_variable(self, test: pd.DataFrame, params: Any, cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
        """Optional per-variable detail (CUSUM, trend, change point, replay...)."""
        return {}
