# Detector S — statistical detection on standardized residuals

## Purpose

Detector S is the statistical detection stage of sensor-guard. It scores daily
standardized residuals (produced by the preparation run) for each weather
station and raises a per-day flag (0/1) for each detector. It is pure
numpy/scipy: **no machine learning, no fusion, no confidence score, no attack
generator.** Every detector returns the shared `date / score / flag` format.

## Where everything lives

| Concern | Location |
|---|---|
| Code | `src/sensorguard/processing/detector_s/` |
| Parameters | `config/detector_s.yaml` (nothing is hard-coded in detector code) |
| Outputs | `results/detector_s/` and `results/detector_s/figures/` (created by the run; must be empty before the first run) |
| Inputs (read only) | standardized residuals and received station values from a pipeline run, through `sensorguard.detect.statistical.run`; or the residual files `results/models_2021_2024/{site}_standardized_residuals.csv` if a preparation run wrote them |
| Train / evaluation split | fit on `2021-01-01 .. 2023-12-31`, score on `2024-01-01 .. 2024-12-31` |

## Modules

- `base.py` — `Detector` base contract (`fit`, `score`, `per_variable`), config loading (`load_detector_config`), variable lists (`variables`, `monitored_variables`, `residual_columns`), output helpers (`ensure_output_directory`, `write_daily_csv` with a never-overwrite-non-empty guard), and PASS/WARN/FAIL status from the alarm rate.
- `stats.py` — shared linear algebra: `fit_ar`, `whiten`, `cusum_up_down` (NaN-hold policy), `cusum_stat`, `mann_kendall`, `sen_slope`.
- `cusum.py` — `CusumDetector`: per-variable AR model fitted on train, residuals whitened, CUSUM accumulated, combined statistic = max across variables, threshold from config.
- `change_point.py` — `ChangePointDetector`: binary-segmentation-style scoring on whitened streams; null threshold derived from the train period only.
- `mahalanobis.py` — `MahalanobisDetector`: robust centre/scale (median/MAD), regularized covariance on train, chi-square quantile threshold; degrees of freedom = number of monitored variables.
- `replay.py` — `ReplayDetector`: compares every 7-day window of the **station values** (not the residuals) with every earlier window, lag 1 to 730 days; a day is flagged when its smallest distance is below `replay.tolerance` (in train standard deviations). See [detector_s-fixes.md](detector_s-fixes.md) section 3.
- `trend.py` — `TrendDetector`: rolling Mann-Kendall z and Sen slope; threshold = empirical train quantile of `|z|`.

## NaN and observability rules

- `precip_mm` is **not monitored**: its residual is NaN on dry-dry days (about 40–70% of days depending on the site), so monitoring it would blind every detector most of the time. `monitored_variables` = `temp_c, rh_pct, wind_ms, solar_mj_m2`.
- Any monitored variable NaN on a day => that day's score is NaN and its flag is 0 (observability gap, not an attack).
- CUSUM `nan_policy: hold`: on a NaN day the up/down accumulators keep their previous value; the NaN is never filled or interpolated, and the held state continues into the next day.

## Output format

Each detector writes one daily CSV (`date`, `score`, `flag`) into `results/detector_s/`. `write_daily_csv` refuses to overwrite an existing non-empty artifact, so a run never silently clobbers a previous output.

## PASS / WARN / FAIL

Per-detector status comes from the daily alarm rate versus `false_alarm_target` (0.01): at or below target => PASS; at or below target x `alarm_warn_rate_multiple` (2.0) => WARN; above that => WARN while there are at most `alarm_max_distinct_episodes` (3) distinct episodes, otherwise FAIL.

## Relationship to the preparation run

Detector S inherits per-site, per-variable, per-season standardized residuals with NaNs preserved (see `docs/preparation.md`). It only reads `results/models_2021_2024/`; it never writes there. Natural year-to-year level shifts mean thresholds must be wide enough, which is why every threshold is derived on the 2021–2023 train period, never on 2024.

The review of this detector, the bugs fixed and the first measurements on real data are in [detector_s-fixes.md](detector_s-fixes.md).
