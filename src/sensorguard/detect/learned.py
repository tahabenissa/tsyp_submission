"""Detector M: one-class PyOD trained on clean residual windows.

The model follows the SensorGuard architecture:
- fit calibration and temporal baselines on clean training years only;
- build features from station-vs-POWER and temporal residuals;
- fit candidate PyOD models on clean windows only;
- choose the model type on labelled Step/Drift/Replay attacks injected in a
  TUNING year (2023), with the candidates fitted on 2021-2022;
- set the operating thresholds (target 1% FPR) from leave-one-year-out scores:
  the chosen model is fitted on two training years and scores the third, three
  times, so every clean training day gets an out-of-sample score;
- choose the threshold granularity (global, per site or per site and season)
  by which one keeps the false-alarm rate nearest 1% on a held-out training
  year;
- fit the final model on all clean training windows (2021-2023).

2024 is never touched here: it is scored once, by the evaluation.

Why leave one year out: a threshold set from a single year does not transfer
to another year.  Fitted on 2021-2022 with thresholds from 2023, LOF flagged 6%
of FAWN's 2021 days (target 1%): the residuals wander from year to year, and a
99th percentile per site and season rests on about 90 days, so on one or two
extreme values.  Pooling three out-of-sample years covers that wandering.

Attack samples are NEVER used to fit the one-class model. The supervised
Random Forest remains a separate upper-bound experiment.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import RobustScaler

from pyod.models.iforest import IForest
from pyod.models.ecod import ECOD
from pyod.models.copod import COPOD
from pyod.models.hbos import HBOS
from pyod.models.knn import KNN
from pyod.models.lof import LOF

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config" / "config_m.yaml"
VARIABLES = ["temp_c", "rh_pct", "wind_ms", "precip_mm", "solar_mj_m2"]


def _load_config(config_path=None):
    path = Path(config_path) if config_path else DEFAULT_CONFIG
    if not path.is_absolute():
        path = ROOT / path
    with path.open(encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle)
    if not isinstance(cfg, dict):
        raise ValueError(f"Configuration invalide : {path}")
    return cfg


def _project_context():
    # Import lazily to avoid loading the complete pipeline during module import.
    from sensorguard import pipeline
    from sensorguard.processing.calibrate import fit_reference_calibration
    from sensorguard.processing.residuals.reference import apply_reference_residuals
    from sensorguard.processing.residuals.temporal import (
        apply_temporal_residuals,
        fit_temporal_model,
    )
    return (
        pipeline,
        fit_reference_calibration,
        apply_reference_residuals,
        fit_temporal_model,
        apply_temporal_residuals,
    )


def _fit_preparation(station, power, prep_cfg, fit_start, fit_end):
    _, fit_reference, _, fit_temporal, _ = _project_context()
    calibration = fit_reference(station, power, prep_cfg, fit_start, fit_end)
    temporal_model = fit_temporal(station, prep_cfg, fit_start, fit_end)
    return {"calibration": calibration, "temporal_model": temporal_model}


def _fast_temporal_residuals(station, temporal_model, prep_cfg):
    """Vectorized equivalent of apply_temporal_residuals for faster attack sweeps."""
    index = station.index
    order = int(prep_cfg["ar_order"])
    harmonic_order = int(temporal_model.get("harmonic_order", prep_cfg["harmonic_order"]))
    day = index.dayofyear.to_numpy(dtype=float)
    design_columns = [np.ones(len(index))]
    for harmonic in range(1, harmonic_order + 1):
        phase = 2 * np.pi * harmonic * day / prep_cfg["harmonic_period_days"]
        design_columns.extend((np.sin(phase), np.cos(phase)))
    design = np.column_stack(design_columns)

    result = pd.DataFrame(index=index)
    for variable, settings in prep_cfg["variables"].items():
        parameters = temporal_model["variables"][variable]
        coefficients = parameters["baseline_coefficients"]
        if not settings.get("temporal_enabled", True) or coefficients is None:
            result[variable] = np.nan
            continue

        raw_values = pd.to_numeric(station[variable], errors="coerce").to_numpy(dtype=float)
        if settings.get("transform") == "log_ratio":
            values = np.log(raw_values + prep_cfg["log_ratio_pseudocount"])
        else:
            values = raw_values
        baseline = design @ np.asarray(coefficients, dtype=float)
        departure = values - baseline
        raw_residual = np.full(len(index), np.nan, dtype=float)

        if len(index) > order:
            history = np.column_stack([
                departure[order - lag : len(index) - lag]
                for lag in range(1, order + 1)
            ])
            valid = (
                np.isfinite(history).all(axis=1)
                & np.isfinite(values[order:])
                & np.isfinite(baseline[order:])
            )
            positions = np.flatnonzero(valid) + order
            if len(positions):
                prediction = (
                    baseline[positions]
                    + float(parameters["ar_intercept"])
                    + history[valid] @ np.asarray(parameters["ar_coefficients"], dtype=float)
                )
                raw_residual[positions] = values[positions] - prediction

        result[variable] = raw_residual / float(parameters["spread"])
    result.index.name = "date"
    return result


def _make_residuals(station, power, preparation, prep_cfg):
    _, _, apply_reference, _, _ = _project_context()
    reference = apply_reference(station, power, preparation["calibration"], prep_cfg)
    temporal = _fast_temporal_residuals(
        station, preparation["temporal_model"], prep_cfg
    )
    reference = reference.rename(columns={c: f"reference__{c}" for c in reference.columns})
    temporal = temporal.rename(columns={c: f"temporal__{c}" for c in temporal.columns})
    residuals = pd.concat([reference, temporal], axis=1)
    residuals.index.name = "date"
    return residuals


def _slope(values):
    values = np.asarray(values, dtype=float)
    if len(values) < 5 or not np.isfinite(values).all():
        return np.nan
    x = np.arange(len(values), dtype=float)
    return float(np.polyfit(x, values, 1)[0])


def build_window_features(
    residuals: pd.DataFrame,
    station: pd.DataFrame | None = None,
    power: pd.DataFrame | None = None,
    context_scales: pd.Series | dict | None = None,
) -> pd.DataFrame:
    """Causal residual-window features plus replay/reference context features."""
    output = {}
    for column in residuals.columns:
        series = pd.to_numeric(residuals[column], errors="coerce")
        output[f"{column}__level"] = series
        output[f"{column}__delta1"] = series.diff()
        output[f"{column}__mean7"] = series.rolling(7, min_periods=5).mean()
        output[f"{column}__mean30"] = series.rolling(30, min_periods=20).mean()
        output[f"{column}__std7"] = series.rolling(7, min_periods=5).std()
        output[f"{column}__slope7"] = series.rolling(7, min_periods=5).apply(_slope, raw=True)
        output[f"{column}__sum30"] = series.rolling(30, min_periods=20).sum()

    if station is not None and power is not None:
        station = station.reindex(residuals.index)[VARIABLES]
        power = power.reindex(residuals.index)[VARIABLES]
        if context_scales is None:
            context_scales = station.std().replace(0, 1.0)
        context_scales = pd.Series(context_scales).reindex(VARIABLES).replace(0, 1.0)

        # Independent witness agreement: a replayed station week stops following
        # the current NASA POWER week even when its values remain physically plausible.
        for variable in VARIABLES:
            station_delta = station[variable].diff()
            power_delta = power[variable].diff()
            output[f"context__delta_correlation7__{variable}"] = (
                station_delta.rolling(7, min_periods=5).corr(power_delta)
            )

        # Exact/near replay distance against earlier windows. The scale is fitted
        # on clean training years and then frozen for validation and prediction.
        for offset in (7, 28, 364):
            normalized_gap = (
                station - station.shift(offset)
            ).abs().div(context_scales, axis=1)
            daily_distance = normalized_gap.mean(axis=1)
            output[f"context__replay_distance7_back{offset}"] = (
                daily_distance.rolling(7, min_periods=5).mean()
            )

        # Simple physical QC flags are inputs, not the main detector.
        output["qc__rh_out_of_range"] = (
            (station["rh_pct"] < 0) | (station["rh_pct"] > 100)
        ).astype(float)
        for variable in ("wind_ms", "precip_mm", "solar_mj_m2"):
            output[f"qc__{variable}_negative"] = (station[variable] < 0).astype(float)

    features = pd.DataFrame(output, index=residuals.index)
    # Missing residuals are not silently treated as ordinary values:
    # retain an explicit missingness indicator alongside neutral-filled values.
    missing = features.isna().astype(float)
    missing.columns = [f"{name}__missing" for name in missing.columns]
    features = pd.concat([features.fillna(0.0), missing], axis=1)
    features = features.replace([np.inf, -np.inf], 0.0)
    features.index.name = "date"
    return features


def _models(contamination=0.01, random_state=42):
    return {
        "Isolation Forest": IForest(contamination=contamination, random_state=random_state),
        "ECOD": ECOD(contamination=contamination),
        "COPOD": COPOD(contamination=contamination),
        "HBOS": HBOS(contamination=contamination),
        "KNN": KNN(contamination=contamination, n_neighbors=10, method="largest"),
        "LOF": LOF(contamination=contamination, n_neighbors=20),
    }


def _attack_cases(station, site, attack_cfg):
    """Generate labelled official attack cases on the tuning year."""
    from sensorguard.pipeline import AttackSpec, inject

    onset = str(attack_cfg["onset"])
    cases = []
    for variable in VARIABLES:
        for relative_to in attack_cfg["relative_to"]:
            for sign in (-1, 1):
                spec = AttackSpec(
                    attack="step",
                    variables=(variable,),
                    onset=onset,
                    magnitude=float(attack_cfg["step_magnitude"]),
                    sign=sign,
                    relative_to=relative_to,
                    length_days=int(attack_cfg["step_length_days"]),
                )
                cases.append((f"{site}_step_{variable}_{relative_to}_{sign}", inject(station, spec)))

                drift_spec = AttackSpec(
                    attack="drift",
                    variables=(variable,),
                    onset=onset,
                    magnitude=float(attack_cfg["drift_magnitude"]),
                    sign=sign,
                    relative_to=relative_to,
                    ramp_days=int(attack_cfg["drift_ramp_days"]),
                    hold_days=int(attack_cfg.get("drift_hold_days", 0)),
                )
                cases.append((f"{site}_drift_{variable}_{relative_to}_{sign}", inject(station, drift_spec)))

    replay_onset = str(attack_cfg.get("replay_onset", "2023-04-01"))
    for offset in attack_cfg["replay_offsets_days"]:
        spec = AttackSpec(
            attack="replay",
            onset=replay_onset,
            length_days=int(attack_cfg["replay_length_days"]),
            source_offset_days=int(offset),
        )
        cases.append((f"{site}_replay_back{offset}", inject(station, spec)))
    return cases


def _metric_row(y_true, scores, threshold):
    y_true = np.asarray(y_true, dtype=int)
    scores = np.asarray(scores, dtype=float)
    predicted = scores > threshold
    return {
        "roc_auc": float(roc_auc_score(y_true, scores)),
        "average_precision": float(average_precision_score(y_true, scores)),
        "recall_at_clean_threshold": float(recall_score(y_true, predicted, zero_division=0)),
        "precision_at_clean_threshold": float(precision_score(y_true, predicted, zero_division=0)),
        "f1_at_clean_threshold": float(f1_score(y_true, predicted, zero_division=0)),
        "false_positive_rate": float(predicted[y_true == 0].mean()) if np.any(y_true == 0) else np.nan,
    }


def train_detector_m(config_path=None):
    """Train on clean residual windows and rank candidates on held-out attacks."""
    cfg = _load_config(config_path)
    pipeline, *_ = _project_context()
    prep_cfg = pipeline.load_config()
    from sensorguard.processing.calibrate import season_labels
    split = prep_cfg["split"]
    detector_cfg = cfg["detector"]
    seed = int(cfg.get("random_state", 42))
    contamination = float(detector_cfg.get("contamination", 0.01))
    threshold_quantile = float(detector_cfg.get("clean_threshold_quantile", 0.99))
    threshold_mode = str(detector_cfg.get("threshold_mode", "season"))
    min_season_samples = int(detector_cfg.get("min_season_samples", 20))
    if threshold_mode not in {"global", "site", "season", "auto"}:
        raise ValueError("threshold_mode must be global, site, season or auto.")
    if not 0.5 < threshold_quantile < 1.0:
        raise ValueError("clean_threshold_quantile doit être entre 0.5 et 1.0.")

    # The calibration (preparation) uses every training year, like detector S.
    # The models are fitted on the first years only, and the last training year
    # is kept aside to choose the model and its thresholds, so the test year
    # (split["validation_*"], 2024) is never seen before the evaluation.
    train_start = pd.Timestamp(split["train_start"])
    train_end = pd.Timestamp(split["train_end"])
    tuning = cfg.get("tuning", {})
    fit_end = pd.Timestamp(tuning.get("fit_end", "2022-12-31"))
    validation_start = pd.Timestamp(tuning.get("start", "2023-01-01"))
    validation_end = pd.Timestamp(tuning.get("end", "2023-12-31"))
    if not (train_start < fit_end < validation_start <= validation_end <= train_end):
        raise ValueError("tuning must lie inside the training years: fit_end < start <= end <= train_end")
    if pd.Timestamp(cfg["attack_validation"]["onset"]) < validation_start:
        raise ValueError("attack_validation.onset must be inside the tuning year")

    training_frames = []
    validation_frames = []
    validation_frames_by_site = {}
    all_clean_by_site = {}
    clean_preparations = {}
    validation_sites = {}

    for site in pipeline.sites(prep_cfg):
        station, power, _ = pipeline.load_site(site, prep_cfg)
        preparation = _fit_preparation(station, power, prep_cfg, train_start, train_end)
        context_scales = station.loc[train_start:train_end, VARIABLES].std().replace(0, 1.0)
        preparation["context_scales"] = context_scales
        clean_preparations[site] = preparation
        residuals = _make_residuals(station, power, preparation, prep_cfg)
        features = build_window_features(residuals, station, power, context_scales)

        train_mask = (features.index >= train_start) & (features.index <= fit_end)
        validation_mask = (features.index >= validation_start) & (features.index <= validation_end)
        training_frames.append(features.loc[train_mask])
        validation_frames.append(features.loc[validation_mask])
        validation_frames_by_site[site] = features.loc[validation_mask]
        all_clean_by_site[site] = features.loc[(features.index >= train_start) & (features.index <= train_end)]
        validation_sites[site] = {
            "station": station,
            "power": power,
            "validation_mask": validation_mask,
        }
        print(
            f"[DATA] {site}: {int(train_mask.sum())} clean fit windows, "
            f"{int(validation_mask.sum())} clean tuning windows"
        )

    X_train_df = pd.concat(training_frames, axis=0).sort_index()
    X_clean_val_df = pd.concat(validation_frames, axis=0).sort_index()
    # Constant signals (for example an always-zero QC flag) add distance noise
    # without information, especially for KNN. Keep only train-varying columns.
    feature_names = X_train_df.columns[X_train_df.nunique(dropna=False) > 1].tolist()
    if not feature_names:
        raise ValueError("Aucune caractéristique variable dans les fenêtres propres.")
    X_train_df = X_train_df[feature_names]
    X_clean_val_df = X_clean_val_df[feature_names]
    validation_frames_by_site = {
        site: frame[feature_names] for site, frame in validation_frames_by_site.items()
    }

    scaler = RobustScaler()
    X_train = scaler.fit_transform(X_train_df.to_numpy(dtype=float))
    X_clean_val = scaler.transform(X_clean_val_df[feature_names].to_numpy(dtype=float))

    attack_features = []
    attack_labels = []
    attack_names = []
    attack_sites = []
    attack_seasons = []
    for site, values in validation_sites.items():
        cases = _attack_cases(values["station"], site, cfg["attack_validation"])
        for case_name, attack_result in cases:
            residuals = _make_residuals(
                attack_result.series, values["power"], clean_preparations[site], prep_cfg
            )
            features = build_window_features(
                residuals, attack_result.series, values["power"],
                clean_preparations[site]["context_scales"],
            ).reindex(columns=feature_names)
            mask = (
                (features.index >= validation_start)
                & (features.index <= validation_end)
                & values["validation_mask"]
            )
            y = attack_result.labels["attacked"].reindex(features.index).fillna(False).astype(int)
            X_case = scaler.transform(features.loc[mask, feature_names].to_numpy(dtype=float))
            y_case = y.loc[mask].to_numpy(dtype=int)
            if y_case.sum() == 0:
                raise ValueError(f"Aucune journée attaquée dans le scénario {case_name}")
            attack_features.append(X_case)
            attack_labels.append(y_case)
            attack_names.append(case_name)
            attack_sites.append(site)
            attack_seasons.append(
                season_labels(features.index[mask], prep_cfg["season_definition"]).to_numpy()
            )
        print(f"[ATTACKS] {site}: {len(cases)} scénarios Step/Drift/Replay générés")

    model_dir = ROOT / detector_cfg.get("model_directory", "results/models_detector_m")
    model_dir.mkdir(parents=True, exist_ok=True)
    comparison_rows = []
    detailed_rows = []
    fitted_models = {}
    model_thresholds = {}
    candidate_models = _models(contamination, seed)

    clean_meta = pd.concat([
        pd.DataFrame({
            "site": site,
            "date": frame.index,
            "season": season_labels(frame.index, prep_cfg["season_definition"]),
        })
        for site, frame in validation_frames_by_site.items()
    ], ignore_index=True)

    def clean_scores_for_model(model):
        parts = []
        for site, frame in validation_frames_by_site.items():
            X = scaler.transform(frame.to_numpy(dtype=float))
            parts.append(np.asarray(model.decision_function(X)).reshape(-1))
        return np.concatenate(parts)

    def thresholds_for_model(clean_scores):
        frame = clean_meta.copy()
        frame["score"] = clean_scores
        global_thr = float(np.quantile(frame["score"], threshold_quantile))
        site_thr = frame.groupby("site")["score"].quantile(threshold_quantile).to_dict()
        season_thr = frame.groupby(["site", "season"])["score"].quantile(threshold_quantile).to_dict()
        season_counts = frame.groupby(["site", "season"])["score"].size().to_dict()

        def get(site, season):
            if threshold_mode == "global":
                return global_thr
            if threshold_mode == "site":
                return site_thr.get(site, global_thr)
            if season_counts.get((site, season), 0) >= min_season_samples:
                return season_thr.get((site, season), site_thr.get(site, global_thr))
            return site_thr.get(site, global_thr)

        return {
            "global": global_thr,
            "site": site_thr,
            "season": season_thr,
            "mode": threshold_mode,
            "quantile": threshold_quantile,
        }, get

    for name, model in candidate_models.items():
        model.fit(X_train)  # clean fit windows only (2021-2022)
        clean_scores = clean_scores_for_model(model)
        thresholds, get_threshold = thresholds_for_model(clean_scores)
        clean_thresholds = np.array([
            get_threshold(site, season)
            for site, season in zip(clean_meta["site"], clean_meta["season"])
        ])
        scenario_metrics = []
        global_metrics = []
        for case_name, X_case, y_case, case_site, case_seasons in zip(
            attack_names, attack_features, attack_labels, attack_sites, attack_seasons
        ):
            scores = np.asarray(model.decision_function(X_case)).reshape(-1)
            case_thresholds = np.array([
                get_threshold(case_site, season) for season in case_seasons
            ])
            case_metrics = _metric_row(y_case, scores, case_thresholds)
            scenario_metrics.append(case_metrics)
            detailed_rows.append({
                "model": name,
                "scenario": case_name,
                "threshold_mode": threshold_mode,
                **case_metrics,
            })
            global_metrics.append(_metric_row(y_case, scores, thresholds["global"]))
            if threshold_mode != "global":
                detailed_rows.append({
                    "model": name,
                    "scenario": case_name,
                    "threshold_mode": "global",
                    **_metric_row(y_case, scores, thresholds["global"]),
                })

        metrics = pd.DataFrame(scenario_metrics)
        global_frame = pd.DataFrame(global_metrics)
        row = {
            "model": name,
            "mean_roc_auc_attacks": float(metrics["roc_auc"].mean()),
            "mean_average_precision_attacks": float(metrics["average_precision"].mean()),
            "mean_recall_at_1pct_fpr": float(metrics["recall_at_clean_threshold"].mean()),
            "mean_precision": float(metrics["precision_at_clean_threshold"].mean()),
            "mean_f1": float(metrics["f1_at_clean_threshold"].mean()),
            "clean_validation_fpr": float((clean_scores > clean_thresholds).mean()),
            "clean_validation_fpr_global": float((clean_scores > thresholds["global"]).mean()),
            "clean_threshold": thresholds["global"],
            "threshold_mode": threshold_mode,
            "threshold_quantile": threshold_quantile,
            "mean_recall_at_1pct_fpr_global": float(global_frame["recall_at_clean_threshold"].mean()),
            "mean_precision_global": float(global_frame["precision_at_clean_threshold"].mean()),
            "mean_f1_global": float(global_frame["f1_at_clean_threshold"].mean()),
            "training_clean_windows": int(len(X_train)),
            "validation_clean_windows": int(len(X_clean_val)),
            "attack_scenarios": int(len(scenario_metrics)),
        }
        comparison_rows.append(row)
        fitted_models[name] = model
        model_thresholds[name] = thresholds
        print(
            f"[COMPARE] {name}: AP={row['mean_average_precision_attacks']:.4f}, "
            f"AUC={row['mean_roc_auc_attacks']:.4f}, "
            f"precision={row['mean_precision']:.4f}, "
            f"recall={row['mean_recall_at_1pct_fpr']:.4f}, "
            f"F1={row['mean_f1']:.4f}, "
            f"FPR={row['clean_validation_fpr']:.2%}"
        )

    comparison = pd.DataFrame(comparison_rows).sort_values(
        ["mean_average_precision_attacks", "mean_roc_auc_attacks", "mean_recall_at_1pct_fpr"],
        ascending=False,
    ).reset_index(drop=True)
    comparison.insert(0, "rank", np.arange(1, len(comparison) + 1))
    comparison.to_csv(model_dir / "model_comparison.csv", index=False)
    pd.DataFrame(detailed_rows).to_csv(
        model_dir / "attack_scenario_metrics.csv", index=False
    )

    chosen_name = str(comparison.iloc[0]["model"])

    # Thresholds from leave-one-year-out scores, final model on every training year.
    years = sorted({d.year for frame in all_clean_by_site.values() for d in frame.index})
    oos = []
    for held in years:
        fit_parts = [f.loc[f.index.year != held, feature_names] for f in all_clean_by_site.values()]
        fold_scaler = RobustScaler().fit(pd.concat(fit_parts).to_numpy(dtype=float))
        fold_model = _models(contamination, seed)[chosen_name]
        fold_model.fit(fold_scaler.transform(pd.concat(fit_parts).to_numpy(dtype=float)))
        for site, frame in all_clean_by_site.items():
            part = frame.loc[frame.index.year == held, feature_names]
            oos.append(pd.DataFrame({
                "site": site, "year": held,
                "season": season_labels(part.index, prep_cfg["season_definition"]).to_numpy(),
                "score": np.asarray(fold_model.decision_function(
                    fold_scaler.transform(part.to_numpy(dtype=float)))).reshape(-1),
            }))
    oos = pd.concat(oos, ignore_index=True)

    def thresholds_from(frame, mode):
        g = float(np.quantile(frame["score"], threshold_quantile))
        site_t = frame.groupby("site")["score"].quantile(threshold_quantile).to_dict()
        counts = frame.groupby(["site", "season"])["score"].size()
        season_t = {k: v for k, v in frame.groupby(["site", "season"])["score"].quantile(threshold_quantile).items()
                    if counts[k] >= min_season_samples}
        return {"global": g, "site": site_t, "season": season_t, "mode": mode, "quantile": threshold_quantile}

    def day_thresholds(t, frame):
        if t["mode"] == "global":
            return np.full(len(frame), t["global"])
        site_level = frame["site"].map(t["site"]).fillna(t["global"])
        if t["mode"] == "site":
            return site_level.to_numpy()
        keys = list(zip(frame["site"], frame["season"]))
        return np.array([t["season"].get(k, s_) for k, s_ in zip(keys, site_level)])

    # Granularity: thresholds from two years, false-alarm rate on the third.
    granularity = []
    for mode in ("global", "site", "season"):
        rates = []
        for held in years:
            t = thresholds_from(oos[oos.year != held], mode)
            test = oos[oos.year == held]
            for site in test["site"].unique():
                g = test[test["site"] == site]
                rates.append(float((g["score"].to_numpy() > day_thresholds(t, g)).mean()))
        granularity.append({"mode": mode, "mean_fpr": float(np.mean(rates)), "max_fpr": float(np.max(rates)),
                            "error": float(np.mean(np.abs(np.asarray(rates) - (1 - threshold_quantile))))})
    granularity = pd.DataFrame(granularity).sort_values("error").reset_index(drop=True)
    granularity.to_csv(model_dir / "threshold_granularity.csv", index=False)
    chosen_mode = threshold_mode if threshold_mode != "auto" else str(granularity.iloc[0]["mode"])
    chosen_thresholds = thresholds_from(oos, chosen_mode)
    print("[THRESHOLDS] leave-one-year-out false-alarm rate per site and held-out year:")
    print(granularity.to_string(index=False))
    print(f"[THRESHOLDS] granularity used: {chosen_mode}")

    all_clean = pd.concat([f[feature_names] for f in all_clean_by_site.values()]).to_numpy(dtype=float)
    scaler = RobustScaler().fit(all_clean)
    best_model = _models(contamination, seed)[chosen_name]
    best_model.fit(scaler.transform(all_clean))
    X_train = all_clean

    joblib.dump(best_model, model_dir / "best_model_m.pkl")
    joblib.dump(scaler, model_dir / "scaler_m.pkl")
    joblib.dump(feature_names, model_dir / "features_m.pkl")
    joblib.dump(clean_preparations, model_dir / "preparation_m.pkl")
    joblib.dump(chosen_thresholds["global"], model_dir / "threshold_m.pkl")
    joblib.dump(chosen_thresholds, model_dir / "thresholds_m.pkl")

    print(f"[OK] Modèle sélectionné sur les attaques officielles : {chosen_name}")
    print(f"[OK] Modèle entraîné sur {len(X_train)} fenêtres propres uniquement.")
    print(f"[OK] Comparaison : {model_dir / 'model_comparison.csv'}")
    print("[INFO] Les attaques ont servi à l'évaluation, jamais à l'entraînement.")
    return {
        "model_name": chosen_name,
        "training_clean_windows": int(len(X_train)),
        "validation_clean_windows": int(len(X_clean_val)),
        "attack_scenarios": int(len(attack_names)),
        "model_dir": str(model_dir),
        "comparison": comparison.to_dict(orient="records"),
    }


def _read_daily_frame(data):
    if isinstance(data, (str, Path)):
        from sensorguard.processing.calibrate import read_cleaned_daily_table
        frame = read_cleaned_daily_table(data)
    else:
        frame = data.copy()
        if "date" in frame.columns:
            frame["date"] = pd.to_datetime(frame["date"], errors="raise")
            frame = frame.set_index("date")
        frame.index = pd.to_datetime(frame.index, errors="raise")
        frame = frame.sort_index()
    missing = [column for column in VARIABLES if column not in frame.columns]
    if missing:
        raise ValueError(f"Colonnes météo manquantes : {missing}")
    return frame[VARIABLES].copy()


def predict_detector_m(station_data, power_data, site, config_path=None):
    """Score a station using its paired POWER reference and saved clean calibration."""
    cfg = _load_config(config_path)
    model_dir = ROOT / cfg["detector"].get("model_directory", "results/models_detector_m")
    required = [
        "best_model_m.pkl", "scaler_m.pkl", "features_m.pkl",
        "preparation_m.pkl", "threshold_m.pkl",
    ]
    missing_files = [name for name in required if not (model_dir / name).is_file()]
    if missing_files:
        raise FileNotFoundError(
            f"Artefacts manquants : {missing_files}. Lancez d'abord train_detector_m.py."
        )

    pipeline, *_ = _project_context()
    prep_cfg = pipeline.load_config()
    from sensorguard.processing.calibrate import season_labels
    station = _read_daily_frame(station_data)
    power = _read_daily_frame(power_data)
    preparation_by_site = joblib.load(model_dir / "preparation_m.pkl")
    if site not in preparation_by_site:
        raise ValueError(
            f"Site {site!r} inconnu. Sites calibrés : {sorted(preparation_by_site)}"
        )

    preparation = preparation_by_site[site]
    residuals = _make_residuals(station, power, preparation, prep_cfg)
    features = build_window_features(
        residuals, station, power, preparation.get("context_scales")
    )
    feature_names = joblib.load(model_dir / "features_m.pkl")
    features = features.reindex(columns=feature_names, fill_value=0.0)

    scaler = joblib.load(model_dir / "scaler_m.pkl")
    model = joblib.load(model_dir / "best_model_m.pkl")
    thresholds_path = model_dir / "thresholds_m.pkl"
    if thresholds_path.is_file():
        thresholds = joblib.load(thresholds_path)
    else:
        thresholds = {
            "global": float(joblib.load(model_dir / "threshold_m.pkl")),
            "site": {},
            "season": {},
            "mode": "global",
        }
    X = scaler.transform(features.to_numpy(dtype=float))
    scores = np.asarray(model.decision_function(X)).reshape(-1)

    mode = str(thresholds.get("mode", "global"))
    seasons = season_labels(features.index, prep_cfg["season_definition"])

    def threshold_for(season):
        if mode == "global":
            return thresholds["global"]
        if mode == "site":
            return thresholds.get("site", {}).get(site, thresholds["global"])
        return thresholds.get("season", {}).get(
            (site, season), thresholds.get("site", {}).get(site, thresholds["global"])
        )

    day_thresholds = np.array([threshold_for(season) for season in seasons])
    result = pd.DataFrame(index=features.index)
    result["anomaly_score"] = scores
    result["is_anomaly"] = (scores > day_thresholds).astype(int)
    result.index.name = "date"
    return result


def detect_anomalies(station_data, power_data, site, config_path=None):
    result = predict_detector_m(station_data, power_data, site, config_path)
    print(
        f"Détection terminée : {int(result['is_anomaly'].sum())} anomalie(s) "
        f"/ {len(result)} jours."
    )
    return result
