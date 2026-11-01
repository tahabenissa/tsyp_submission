# Detector S: review, fixes and first measurements on real data

Branch `feat/detector-s`, started from `main` at `58ba65f` (after the detector S work was merged, PR #11). This file records exactly what was changed in detector S, why, and what the first run on the three development sites showed. The detector descriptions themselves are in [detector_s.md](detector_s.md).

**State in one line:** five bugs fixed, replay rewritten, detector S connected to the pipeline (sections 2 to 5). Then the false-alarm problem was diagnosed (section 6) and fixed (section 9): every threshold is now set from a false-alarm budget on the clean training years, and on real 2024 data the CUSUM gives 1 to 4 false alarms per station-year.

---

## 1. Starting point

What was on `main` when the work started:

| Check | Result |
|---|---|
| `tests/test_detector_ar.py` | could not even be imported: `scipy` was in `requirements.txt` but not installed in `.venv` |
| after installing `scipy` | 12 passed, **3 failed** |
| input folder `results/models_2021_2024/` | **empty**: the preparation run that should write the residual files was never run, so detector S had nothing to read |
| connection to the pipeline | none: `pipeline.py` still used its placeholder screen, and `src/sensorguard/detect/statistical.py` was an empty stub |

The three failing tests:

1. `test_clean_noise_gives_few_alarms`: one detector flagged **74.5 %** of clean days.
2. `test_mahalanobis_catches_single_day_spike`: a very large one-day spike was not flagged.
3. `test_cusum_catches_constant_shift_and_change_point_dates_it`: the change date was 28 days late.

A diagnostic run on the test's clean synthetic noise gave:

| Detector | Threshold | Alarm rate on clean noise | Max score |
|---|---|---|---|
| CUSUM | 4.0 | **0.94** | 53.2 |
| change point | 76.4 | 0.00 | 53.2 |
| trend | 2.54 | 0.005 | 2.55 |
| replay | 0.61 | 0.00 | 0.57 |
| Mahalanobis | 18.5 | 0.00 | 0.89 |

Every detector also reported its name as `"detector"`, which is why the test error message did not say which one failed.

---

## 2. Bugs found and fixed

### 2.1 CUSUM downward accumulator had the wrong sign (`stats.py`)

**Before**

```python
down[t] = min(0.0, down[t-1] - whitened[t] - slack)
```

The term `- slack` pulls `down` further below zero every day, whatever the data. After 200 days of pure noise, `down` was about −50. Since the score is `max(up, -down)`, the score grew without limit and almost every day was flagged.

**After**

```python
down[t] = min(0.0, down[t-1] + whitened[t] + slack)
```

This is the standard two-sided CUSUM. `up` collects positive deviations larger than the slack and `down` collects negative ones. Both forget at a rate of `slack` per day. The existing test `test_cusum_holds_state_across_nan_day` asserted the wrong formula, so it was corrected. A new test, `test_cusum_down_side_catches_negative_shift_only`, checks that:

- noise inside the slack never accumulates, and
- a −1.0 shift builds up on the down side only, at 0.75 per day.

This bug also explains the change-point threshold of 76: that threshold was a quantile of the same broken statistic.

### 2.2 Whitened residuals were not in standard-deviation units (`stats.whiten`)

`whiten` received the AR model's residual standard deviation `sigma` but never used it. The CUSUM slack (0.25) and threshold (4.0) are meant in standard deviations, so they only meant what the config says if the data happened to have σ = 1. The prediction error is now divided by `sigma`.

Two smaller changes in the same function:

- **Lag order.** The old code multiplied the lag window (oldest value first) by the coefficients (lag-1 first). That is wrong for any AR order above 1. Order 1, the configured one, was not affected. The new code pairs coefficient *i* with lag *i + 1* explicitly.
- **Speed.** The day-by-day Python loop is replaced by an array computation.

### 2.3 Mahalanobis compared the wrong quantities (`mahalanobis.py`)

There were two errors in `score`:

1. **Missing scaling.** The covariance was fitted on residuals scaled by the robust spread (MAD), but test days were not scaled before computing the distance. A spike of 25 robust standard deviations came out as a distance of about 5.
2. **Distance against a squared-distance threshold.** The score was `sqrt(d²)` but the threshold was `chi2.ppf(0.999, df=4) = 18.5`, which is a threshold for `d²`.

Now test days are scaled the same way as in `fit`, and the score is `d²`, compared directly with the chi-square quantile.

There was also a hidden config bug. `get(cfg, "mahalanobis.shrinkage", 0.10)` looked for a top-level key literally named `"mahalanobis.shrinkage"`, never found it, and always used the default. The same applied to `quantile`. `base.get` now follows dotted keys into nested sections, so the values in `config/detector_s.yaml` are actually used. They match the defaults, so no result changed.

### 2.4 Change-point detector: threshold from one variable, onset dated too late (`change_point.py`, rewritten)

- **Threshold.** In `fit`, the loop variable `st` was overwritten for each variable, so the threshold came from the last variable only (solar). The detector scores the maximum over all variables. The threshold is now a quantile of that same combined statistic on the train period.
- **Onset dating.** An episode's `start` was its first alarm day. A CUSUM alarm always comes some days after the change, because evidence has to accumulate first. The classic CUSUM estimate of when the change happened is the day after the alarming accumulator was last at zero. That is implemented as `stats.cusum_onset()`. Each episode now carries:
  - `start`: the estimated change date, used for the onset-error metric
  - `first_alarm`: the first flagged day, used for latency
  - `end`, `days`, `type` (step / drift), `max_score`, `variable`
- **Typing.** The Mann-Kendall trend test now runs from the estimated onset to the end of the episode, not only over the flagged days.

The file was rewritten as one shared helper (`_paths`), because the old file repeated the same whitening and CUSUM code four times.

### 2.5 Every detector called itself `"detector"` (`base.py`)

`Detector` was a `@dataclass` with a field `name = "detector"`. The subclasses set `name = "cusum"` and so on as plain class attributes, but the generated `__init__` overwrote them with `"detector"` on every instance. `Detector` is now a plain class and `name` a class attribute.

### 2.6 Trend detector ignored downward drifts and was slow (`trend.py`, `stats.py`)

- **Downward drifts.** The combined score was `max(z)` across variables, but the flag tested `|z|`. A downward drift on one variable (negative *z*) was hidden whenever another variable had a small positive *z*. The combined score is now `max(|z|)`.
- **Speed.** Each scored day recomputed the Sen slope with a pure-Python double loop (about 11,000 pairs for a 150-day window), even though `score` never uses the slope. The slope is now computed only in `per_variable`. Both Mann-Kendall and Sen's slope are vectorised, and the trend detector takes under 1 s per site-year.

---

## 3. Replay detector rewritten (`replay.py`)

**Problem.** The old detector looked for a 7-day block of **residuals** similar to an earlier block. A replay attack copies the station's **own values** from an earlier period. The residual is the station minus the NASA POWER reference for the same day, and the reference for the replayed days has moved on. So a replayed week does **not** repeat in residual space, and the old detector could not see the official attack. Its unit test passed only because it copied residuals directly, which no real attack does. Two smaller issues:

- blocks were cut on a fixed 7-day grid, so a replay that did not start on a multiple of 7 was split across two blocks;
- the "per variable" output compared each block with a block of zeros, which always gives similarity 0.

**New method.** It works on the station values that passed layer 1.

1. Scale each variable by its train-period standard deviation.
2. For every 7-day window ending on day *t*, and every lag from 1 to `max_lag_days` (730), compute the mean absolute difference between the window and the window *lag* days earlier, over all days and variables.
3. Keep the smallest of these distances and the lag that produced it.
4. A day's score is the smallest distance over all windows that contain it. The day is flagged when the score is below `tolerance` (0.05 standard deviations).

Other details:

- The last 730 train days are kept as history, so a replay early in the scored year still finds its source.
- A lag shorter than the block also catches a frozen sensor repeating one value.
- `fit` records `train_min_distance`, the closest that natural weather came to repeating itself in train. That is the safety margin between real weather and a copy.
- Score here is a **distance**: low means suspicious.

**Config.** `config/detector_s.yaml` gained `replay.max_lag_days`, `replay.tolerance` and `replay.columns`, which maps each variable to its station column. The old `train_similarity_quantile` and `min_block_score` were removed.

**Tests.**

- `test_replay_catches_copied_seven_day_block` now copies station values from train into a block that does not start on a multiple of 7. It checks that exactly those 7 days are flagged and nothing else.
- New: `test_replay_catches_a_copy_of_the_previous_week_inside_test` is the official attack shape (the 7 days before onset sent again). It checks that the replayed week is flagged, that only the source and replayed weeks are flagged, and that the matching lag is 7.
- The test fixture `_residual_frame` now also creates `station_<var>` columns.

---

## 4. Detector S connected to the pipeline (`src/sensorguard/detect/statistical.py`)

This file was an empty stub. It now holds the bridge between a pipeline run and the detectors.

- `detector_frame(reference, received)` puts the pipeline's standardized reference residuals (`reference_<var>`) and the station values that passed layer 1 (`station_<var>`) into one table.
- `run(reference, received, split, cfg)` fits every detector on the train years (2021–2023) and scores the validation year (2024). It returns a `DetectorSResult`:
  - `daily`: per day, `<name>_score` and `<name>_flag` for each detector, plus `flag` (OR of all flags)
  - `episodes`: the change-point episodes
  - `params`: fitted thresholds
  - `seconds`: time taken per detector
- `evaluate(daily, attacked)` gives, per detector: was the attack detected, the share of attacked days flagged, days to the first flag, and the false-alarm rate on clean days.

Because the pipeline computes the residuals itself, detector S no longer needs the missing `results/models_2021_2024/` files. The CSV-reading helpers in `base.py` are kept for anyone who does produce those files.

Usage:

```python
from sensorguard import pipeline as pl
from sensorguard.detect import statistical

cfg = pl.load_config()
r = pl.run("fawn", pl.AttackSpec(attack="step", variables=("temp_c",), onset="2024-04-01"), cfg)
res = statistical.run(r.prep.reference, r.trust.received, cfg["split"])
print(statistical.evaluate(res.daily, r.labels["attacked"]))
```

---

## 5. First measurements on real data

**Setup**

- Sites: AZMET, FAWN, Kansas.
- Fit on 2021–2023, score 2024.
- Attacker at the station (position P1: it signs its own false values, so layer 1 accepts everything and only detector S can catch the attack).
- Attacks with onset 2024-04-01:
  - 12 % step lasting 60 days
  - drift ramping to 15 % over 60 days, then held for 30 days
  - 7-day replay
- Step and drift were applied to each variable in turn.

**How large the attacks are, in residual standard deviations** (mean residual over the attacked days):

| Attack | AZMET | FAWN | Kansas |
|---|---|---|---|
| step, temp_c | 1.32 | 4.25 | 1.80 |
| step, rh_pct | **0.09** | 2.92 | 0.66 |
| step, wind_ms | 0.64 | 1.02 | **0.43** |
| step, solar_mj_m2 | 5.27 | 2.85 | 1.75 |
| drift, temp_c | 1.31 | 2.43 | 1.74 |
| drift, rh_pct | **0.12** | 2.11 | **0.08** |
| drift, wind_ms | **0.31** | 0.64 | 0.50 |
| drift, solar_mj_m2 | 2.64 | 1.83 | 1.12 |

Temperature and solar attacks are large compared with the noise. Humidity at AZMET and Kansas, and wind everywhere, are about the same size as the natural year-to-year shift in section 6. Those may not be detectable without false alarms, and the report must say so (the plan already expected this for wind and rain).

**False-alarm rate on clean 2024 data** (share of days flagged, no attack):

| Detector | AZMET | FAWN | Kansas |
|---|---|---|---|
| replay | **0.000** | **0.000** | **0.000** |
| Mahalanobis | 0.005 | 0.003 | 0.008 |
| trend | 0.000 | 0.538 | 0.164 |
| change point | 0.000 | 0.667 | 0.546 |
| CUSUM | 0.809 | 0.959 | 0.975 |

**Replay:** detected on the first replayed day at all three sites, with no false alarms. The smallest natural distance in train was 0.10 (AZMET), 0.20 (FAWN) and 0.19 (Kansas), 2 to 4 times above the 0.05 tolerance.

**Mahalanobis:** within the 1 % false-alarm target at all three sites. It is a single-day test, so it sees only the large attacks.

**CUSUM, change point, trend:** the detection numbers mean nothing yet. A detector that is already alarming before the attack "detects" everything at day 0, so they are not reported here.

**Speed:** every detector together takes about 1 s per site-year. Almost all of that is the trend detector (0.9 s); the rest take between 1 and 100 ms.

---

## 6. Open problem: residuals shift from year to year

Mean of the clean standardized reference residual per year:

| Site | Variable | 2021 | 2022 | 2023 | 2024 |
|---|---|---|---|---|---|
| AZMET | temp_c | 0.01 | 0.19 | −0.09 | −0.20 |
| FAWN | temp_c | 0.07 | −0.19 | 0.18 | **0.46** |
| FAWN | rh_pct | −0.21 | −0.14 | 0.02 | −0.30 |
| FAWN | solar_mj_m2 | −0.04 | −0.31 | 0.25 | **0.70** |
| Kansas | rh_pct | −0.30 | 0.06 | 0.22 | −0.31 |
| Kansas | wind_ms | −0.13 | −0.02 | −0.02 | −0.28 |

The calibration is fitted on 2021–2023, but the station-to-reference offset moves by 0.2 to 0.7 σ from year to year with no attack (sensor ageing, maintenance, a changed POWER product, or real climate differences between years). The CUSUM slack is 0.25 σ. Any lasting offset larger than that keeps accumulating, so the CUSUM eventually alarms and never comes back down. Change point and trend use train-derived thresholds, but 2024 is simply outside what 2021–2023 showed. This is the effect `docs/detector_s.md` already warned about ("natural year-to-year level shifts mean thresholds must be wide enough").

**Options for the next step:**

1. **Raise the slack to the natural shift** (about 0.5–0.75 σ) and set the threshold from a target false-alarm rate. This is quick, but it gives up the smallest attacks, which are exactly the humidity and wind cases in section 5.
2. **Track the slow baseline.** Subtract a robust rolling median of the residual over a long, lagged window (for example 180 days ending 60 days before the scored day). The detector then only sees changes faster than the baseline. A 12 % step and a 60-day drift are both faster than a 180-day window, so they stay visible. An attacker who drifts more slowly than the baseline adapts can evade it, which belongs in the evasion section of the report.
3. **Recalibrate every year** on the previous 12 months. This removes most of the offset but needs a full clean year before each scored year.

Option 2 is the most defensible and fits the time left. It is the planned next change.

---

## 7. Test status

| Suite | Before | After |
|---|---|---|
| `tests/test_detector_ar.py` | not importable; with `scipy`: 12 passed, 3 failed | 16 passed, 1 failed (17 tests, 2 of them new) |
| all other tests | 118 passed | unchanged (the pipeline and other modules were not edited) |

**The remaining failure** is `test_clean_noise_gives_few_alarms`: the change-point detector flags 4 % of 200 clean synthetic days, against a limit of 2 %. Its threshold is the 0.9995 quantile of a 300-day train path, so it is close to the train maximum, and a CUSUM with slack 0.25 makes long random excursions on pure noise. This is the same "slack too small" issue as section 6 and will be fixed with it, not by loosening the test.

**Environment:** `scipy` is listed in `requirements.txt` but was missing from `.venv`. It was installed with `pip install scipy`. `requirements.txt` should pin its version together with the other unpinned libraries.

---

## 8. Files changed

| File | Change |
|---|---|
| `src/sensorguard/processing/detector_s/stats.py` | CUSUM sign fix; whitening in σ units with correct lag order; new `cusum_onset`; vectorised Mann-Kendall and Sen slope |
| `src/sensorguard/processing/detector_s/base.py` | detector names fixed (no dataclass); `get` follows dotted keys |
| `src/sensorguard/processing/detector_s/mahalanobis.py` | test days scaled like train; score is d², compared with the chi-square quantile |
| `src/sensorguard/processing/detector_s/change_point.py` | rewritten: combined train threshold, CUSUM onset dating, `first_alarm` field |
| `src/sensorguard/processing/detector_s/trend.py` | combined score uses \|z\|; slope only computed when needed |
| `src/sensorguard/processing/detector_s/replay.py` | rewritten: sliding-window match on station values, any lag up to 730 days |
| `config/detector_s.yaml` | replay section replaced (`max_lag_days`, `tolerance`, `columns`) |
| `src/sensorguard/detect/statistical.py` | new: runs detector S on a pipeline run and evaluates it |
| `tests/test_detector_ar.py` | fixture adds station columns; corrected CUSUM formula test; 2 new tests; replay test now uses station values |
| `docs/detector_s-fixes.md` | this file |

---

## 9. Step 2: thresholds from a false-alarm budget

### 9.1 What the diagnosis showed

Removing the yearly shift (section 6, option 2) was implemented first (`detector_s/baseline.py`) and measured. It did **not** fix the false alarms. The monthly means of the clean residuals explain why:

| Month (clean, no attack) | FAWN temp_c | Kansas rh_pct |
|---|---|---|
| 2024-01 | +1.09 | −0.59 |
| 2024-03 | +1.45 | −0.89 |
| 2024-06 | −0.73 | −1.44 |
| 2024-09 | +0.82 | +0.79 |
| 2024-10 | +1.43 | −0.19 |

The station-minus-POWER residual wanders by about ±1 σ for one to three months at a time with no attack. NASA POWER averages a grid cell about 50 km wide, and in some weather patterns a single field reads differently from that average for weeks. A 12 % step is 1.3–4 σ (section 5), so some natural months look like a small attack. A 180-day baseline cannot follow wanderings that last one to three months.

**Consequence for the design:** no fixed threshold separates attacks from natural wandering at every site. The threshold has to be a stated trade-off between false alarms and detection, and that trade-off has to come from data.

### 9.2 CUSUM restarted after every alarm (`cusum.py`, `stats.cusum_restart`)

Before, once the CUSUM crossed its threshold it stayed above it for weeks. One natural wandering became weeks of "alarm". Now, as in Page's original CUSUM, every sum **restarts at zero after an alarm**.

- An alarm is one **event**. This matches the metric the brief requires: *false alarms per station per year*.
- A lasting attack produces **repeated alarms**, a few days apart. The repetition is itself evidence, and the trust score will use it.
- Alarms closer than 14 days (`merge_gap_days`) form one **episode**. Each episode gets an estimated onset (the day after the alarming sum was last at zero), a type (step or drift, from a Mann-Kendall test from onset to end), a direction and the variable that raised it.

The separate change-point detector computed the same CUSUM a second time, so its dating moved into `CusumDetector.episodes`. `ChangePointDetector` is now a thin subclass, kept for the `change_point.test_variables` option.

### 9.3 Thresholds from a false-alarm budget on the training years

`cusum.threshold: auto` sets the threshold *h* as the **lowest value that gives at most `target_false_alarms_per_year` alarms per year on the clean training years** (2021–2023). It is found by bisection (`stats.calibrate_threshold`), since a higher *h* never gives more alarms. The slack is now *k* = 0.5 σ, the usual choice for detecting a shift of about 1 σ.

Fitted thresholds with a budget of 1 alarm per year:

| Site | CUSUM *h* | train alarms per year reached |
|---|---|---|
| AZMET | 8.9 | 0.67 |
| FAWN | 14.2 | 0.67 |
| Kansas | 8.6 | 0.67 |

FAWN needs a much higher threshold because its residuals wander the most. The method adapts to each site without anyone setting a number by hand. This matters because the final test site is hidden.

### 9.4 Trend detector: prewhitening and a threshold that matches the score (`trend.py`)

Two errors were found while testing:

1. **Threshold and score didn't match.** The threshold was a quantile of single-variable |z| values, but the score is the **largest** |z| over 4 variables, which is naturally higher.
2. **Mann-Kendall assumes independent days.** The residuals are autocorrelated (φ ≈ 0.1–0.7), which inflates *z*. The test now runs on the AR(1) prediction errors (**prewhitening**). A real drift survives this: for x_t = a·t, the prediction error is (1 − φ)·a·t + φ·a, still a trend.

The threshold is the **larger** of:
- the theoretical critical value at significance 0.001, **Bonferroni-corrected** for the 4 variables (|z| > 3.66), which protects against a short training period (overlapping 150-day windows make three years worth only a few independent windows);
- the value calibrated on the training years for the false-alarm budget, which protects against real data noisier than the theory.

On real data the calibrated value wins (4.2–5.1 against 3.66).

### 9.5 Results on real data (budget 1 false alarm per year, baseline off)

Sites AZMET, FAWN and Kansas; fit 2021–2023, score 2024; attacker at the station (P1); onset 2024-04-01; 12 % step for 60 days, drift to 15 % over 60 days then held 30 days.

**False alarms on clean 2024 data**, as separate alarms per year, with the share of days flagged in brackets:

| Detector | AZMET | FAWN | Kansas |
|---|---|---|---|
| CUSUM | 1 (0.3 %) | 4 (1.1 %) | 3 (0.8 %) |
| Mahalanobis | 2 (0.5 %) | 1 (0.3 %) | 3 (0.8 %) |
| replay | 0 | 0 | 0 |
| trend (not in combined flag) | 0 | 7 (20 %) | 6 (8.7 %) |

**CUSUM detection**: number of sites detected out of 3, with the median days from onset to first alarm:

| Variable | 12 % step | drift to 15 % |
|---|---|---|
| temp_c | 3 / 3, 12 days | 3 / 3, 53 days |
| solar_mj_m2 | 3 / 3, 6 days | 3 / 3, 21 days |
| wind_ms | 2 / 3, 32 days | 2 / 3, 60 days |
| rh_pct | 1 / 3, 37 days | 1 / 3, 46 days |

**Replay** (section 5): detected on the first replayed day at all 3 sites, 0 false alarms.

**Reading the results:**
- Temperature and solar attacks are caught at every site. The step is caught within 1–2 weeks, the drift once it has grown to about half its final size.
- Humidity and wind attacks are often **not** caught. At AZMET and Kansas the 12 % humidity step is only 0.09–0.66 σ, smaller than the natural monthly wandering. This is a limit of comparing a point station with a 50 km reference, not a tuning problem, and the report must say so.
- **Mahalanobis "detects" every attack at day 21. This is a chance alarm, not a detection.** It raises 1–3 false alarms a year, and one happens to fall around 22 April 2024 inside every attack window. A fair detection metric must not count alarms that also occur on the same days without the attack. The evaluation step will fix this by comparing every attacked run with the clean run of the same site.

### 9.6 Choices recorded in `config/detector_s.yaml`

| Setting | Value | Why |
|---|---|---|
| `cusum.slack` | 0.5 σ | usual choice for detecting a shift of about 1 σ |
| `cusum.threshold` | auto, 1 false alarm per year on train | ties *h* to the metric in the brief; adapts to each site |
| `baseline.enabled` | false | measured: FAWN 4 → 2 but Kansas 3 → 5 false alarms per year; no clear gain, so the simpler model was kept (ablation result for the report) |
| `combined_flag_detectors` | cusum, replay, Mahalanobis | trend left out: it flags 9–20 % of clean days at FAWN and Kansas, because a 150-day window stays over the threshold for weeks |

### 9.7 Tests

All 17 detector tests pass, and the full suite gives 135 passed. `test_clean_noise_gives_few_alarms` passes without loosening it: CUSUM, trend, replay and Mahalanobis all stay under 2 % of days on 200 days of clean noise.
