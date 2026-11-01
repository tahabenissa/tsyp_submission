# Evaluation of the official standard scenario

How the results tables for the official standard scenario are produced, and what they show. Reproduce them with:

```powershell
.\.venv\Scripts\python.exe scripts\run_all.py            # full grid, about 15 minutes
.\.venv\Scripts\python.exe scripts\run_all.py --quick    # 10 scenarios per site, to check the setup
```

Code: `src/sensorguard/eval/runner.py` (runner), `src/sensorguard/eval/metrics.py` (metrics), `config/evaluation.yaml` (scenario grid). Outputs: `results/eval/standard/` (`summary.md` holds the tables, `runs.csv` every individual result).

---

## 1. What is tested

**The official standard scenario** (docs/05, S-STD): a 12 % step bias, a gradual drift up to 15 %, and a seven-sample replay.

**Mode:** file mode, attacker at the station (position P1). The station signs its own false values, so layer 1 (signatures, sequence numbers, ledger) accepts every record and the attack reaches detection unchanged. This is the hardest case for the defence and the one the jury tests: they hand over a series with the injection already inside. Attacks on the telemetry link (P2) or inside the pipeline (P3) are stopped by layer 1 and are covered by the trust-module tests and the pipeline GUI.

**Sites:** AZMET (Arizona, semi-arid), FAWN (Florida, humid subtropical), Kansas (continental).

**Time split:** every model is fitted on 2021–2023. Every attack is placed in 2024 and every number is measured on 2024.

**The scenario grid** (`config/evaluation.yaml`), run at each of the 3 sites:

| Attack | Variables | Signs | Meaning of "12 %" | Other parameters | Runs per site |
|---|---|---|---|---|---|
| 12 % step, 60 days | temp, humidity, wind, solar | up, down | value, range, std | 4 onsets, one per season | 96 |
| drift to 15 %, then held 30 days | same 4 | up, down | value, range, std | ramp 30, 60 or 90 days; 2 onsets | 144 |
| 7-day replay | the whole record | — | — | source 7, 28 or 364 days back; 4 onsets | 12 |

That gives 252 attacked runs per site and 756 in total, each scored by every detector.

**Why three meanings of "12 %"?** The organizers have not said what the percentage is relative to:
- **value:** x → 1.12 x
- **range:** x → x + 0.12 × (1st-to-99th percentile span)
- **std:** x → x + 0.12 × standard deviation

All three are run, so the table is ready whichever is confirmed. The range and the std are measured on the days before the attack only, so the attacker's own values do not change the size of the attack.

**Precipitation is not monitored by detector S.** Its residual is undefined on dry days, so it is not in the grid.

---

## 2. Detectors compared

| Name in the tables | What it is |
|---|---|
| **S** | Detector S, the statistical baseline. The combined flag is CUSUM OR replay matcher OR Mahalanobis (see [detector_s-fixes.md](detector_s-fixes.md)) |
| S:cusum, S:replay, S:mahalanobis, S:trend | The parts of S on their own. Trend is reported but is not part of the combined flag |
| **M** | Detector M, the learned detector: a one-class LOF model on residual-window features, trained on clean windows only (`detect/learned.py`), scored from its saved model |
| S or M | Alarm if either raises one |

D4 asks for a statistical detector and a learned one, compared on the same data. This runner does that: the same series, the same scenarios and the same metric.

---

## 3. How a result is counted

### 3.1 Fit once, score many

Per site, the preparation (calibration against NASA POWER) and every detector are fitted **once**, on the 2021–2023 part of the **clean** series. Each attacked run then:

1. injects the attack into the clean series,
2. recomputes the residuals with the same calibration,
3. scores 2024 with the same fitted detectors.

This is exact, not an approximation. The attack never touches 2021–2023, so a refit would give the same parameters. The runner refuses any scenario whose attack reaches the training years.

### 3.2 Fair detection

A detector with one or two false alarms a year will sometimes alarm inside an attack window **by chance**. Counting that as a detection makes every detector look good. The step 2 measurements showed it: Mahalanobis "detected" every attack 21 days after onset, because of one natural alarm in late April. So every attacked run is compared with the **clean run of the same site and detector**:

> an alarm counts for the attack only if the clean run has no alarm on that day.

- An **episode is detected** if at least one such new alarm falls between its first and last attacked day (detected before it ends, as docs/05 defines it).
- **Latency** is the first new alarm minus the onset, in days. With daily data, 0 means flagged on the first attacked day.
- **Onset error** is the estimated onset minus the true one. The estimate is the start of the first CUSUM episode that alarms inside the attack and is not present in the clean run. Replay detections have no CUSUM episode, so their onset error is not reported.

**Known simplification:** an attack can shift a natural alarm by a few days. The shifted alarm then counts as "new", which slightly favours detection. Ignoring every alarm within a few days of a clean alarm would be stricter, and is listed as future work.

### 3.3 False alarms

These are measured on the clean 2024 series of each site, two ways:
- **alarm events per year:** a run of consecutive flagged days counts once. This is the "false alarms per station per year" metric of the brief.
- **share of days flagged.**

### 3.4 Confidence intervals

Detection rates come with a 95 % Wilson interval (`metrics.wilson`). It stays inside 0–100 % and is honest for small counts: 10 detections out of 10 gives 72–100 %, not "100 %".

**Caveat:** the runs are not fully independent. They share 3 sites and one year, so the intervals are somewhat too narrow. A block bootstrap over sites and onsets is listed as future work.

---

## 4. Limits to state in the report

- **Detector M no longer sees 2024 (fixed).** A first version set M's thresholds on clean 2024 and chose its model on the 2024 attacks, so its numbers were inflated. Now the model type is chosen on attacks injected into 2023 (candidates fitted on 2021–2022), the thresholds are the 99th percentile of leave-one-year-out scores on 2021–2023, and the threshold granularity (global, per site, per site and season) is the one that keeps the false-alarm rate nearest 1 % on a held-out training year (global won). The final model is fitted on all of 2021–2023. Its honest numbers are lower: steps by value 32 %, drifts by value 33 %, replays 92 %, about 1.7 false alarms per station-year (section 5).
- **M's replay features look back exactly 7, 28 and 364 days,** the same offsets as the replay scenarios. A replay from another offset would be harder for M. Detector S's replay matcher searches every lag from 1 to 730 days.
- **Only 3 sites and one test year,** so false alarms per station-year rest on 3 station-years.
- **No held-out site yet.** All 3 sites are development sites. docs/05 asks for at least two sites the pipeline never saw.

---

## 5. Results

756 attacked runs (252 per site). Each detector scores every run. Total run time 10 min on a laptop CPU. Full tables: `results/eval/standard/summary.md`.

### 5.1 False alarms on the clean 2024 series

Alarm events per station-year:

| Detector | AZMET | FAWN | Kansas | Mean |
|---|---|---|---|---|
| **S** (combined) | 3.0 | 5.0 | 6.0 | **4.7** |
| S:cusum | 1.0 | 4.0 | 3.0 | 2.7 |
| S:mahalanobis | 2.0 | 1.0 | 3.0 | 2.0 |
| S:replay | 0 | 0 | 0 | **0** |
| S:trend (not combined) | 0 | 7.0 | 4.0 | 3.7 |
| **M** | 3.0 | 2.0 | 0 | **1.7** |
| S or M | 6.0 | 7.0 | 6.0 | 6.3 |

S flags 1.3 % of clean days. Its CUSUM budget was 1 false alarm a year on 2021–2023, but 2024 produced 2.7 a year. The test year wanders more than the training years. This is the gap between a threshold set on past data and its behaviour on new data, and it is reported rather than hidden by retuning on 2024.

### 5.2 Detection of the official attacks

Episodes detected before they end, with the 95 % Wilson interval and the median latency in days:

| Attack | "12 %" of | **S** | **M** | S or M |
|---|---|---|---|---|
| 12 % step | value | 67/96 = 70 % (60–78), 12 d | 31/96 = 32 % (24–42), 19 d | 75 %, 12 d |
| 12 % step | range | 86/96 = 90 % (82–94), 6.5 d | 48/96 = 50 % (40–60), 16.5 d | 91 %, 6 d |
| 12 % step | std | 34/96 = 35 % (27–45), 27.5 d | 9/96 = 9 % (5–17), 5 d | 39 %, 23 d |
| drift to 15 % | value | 117/144 = 81 % (74–87), 40 d | 48/144 = 33 % (26–41), 54.5 d | 83 %, 40.5 d |
| drift to 15 % | range | 136/144 = 94 % (89–97), 30 d | 84/144 = 58 % (50–66), 54 d | 95 %, 31 d |
| drift to 15 % | std | 71/144 = 49 % (41–57), 48 d | 5/144 = 3 % (1–8), 102 d | 51 %, 52 d |
| 7-day replay | — | **36/36 = 100 % (90–100), 0 d** | 33/36 = 92 % (78–97), 0 d | 100 %, 0 d |

**Onset error** of S (median, absolute): 2–6.5 days for steps, 24–36 days for drifts. A drift starts at zero, so its true start is invisible for weeks, and the CUSUM dates it from when it became measurable.

### 5.3 What decides whether an attack is caught

**The size of the attack relative to the station's normal disagreement with NASA POWER.** Median size of each attack in residual standard deviations (σ):

| Variable | 12 % of value | 12 % of range | 12 % of std |
|---|---|---|---|
| temp_c | 1.63 | 2.97 | 0.71 |
| solar_mj_m2 | 1.80 | 2.81 | 0.93 |
| rh_pct | 1.24 | 1.31 | 0.35 |
| wind_ms | 0.51 | 1.27 | 0.34 |

Detector S detection rate per variable:

| Variable | step, value | step, range | step, std | drift, value | drift, range | drift, std |
|---|---|---|---|---|---|---|
| temp_c | 0.83 | 1.00 | 0.46 | 0.97 | 1.00 | 0.67 |
| solar_mj_m2 | 0.88 | 0.96 | 0.54 | 0.97 | 1.00 | 0.69 |
| wind_ms | 0.38 | 0.88 | 0.21 | 0.53 | 0.97 | 0.36 |
| rh_pct | 0.71 | 0.75 | 0.21 | 0.78 | 0.81 | 0.25 |

- **Above about 1.5 σ** (temperature and solar, value or range reading), attacks are caught almost always, steps within about a week.
- **Below about 0.7 σ** (every "12 % of std" case, and wind by value), they are mostly missed. They are smaller than the natural one-to-three-month wandering of the residual (docs/detector_s-fixes.md, section 9.1).
- **Humidity** sits in between (1.2–1.3 σ) since the regression witness replaced the plain POWER humidity, and is now caught in 71–81 % of value or range cases (38–50 % before).
- **Little influence:** the sign (up 62 %, down 67 % for steps) and the onset season (60–74 %).
- **Ramp length helps:** drifts ramping over 90 days are caught more often than over 30 days (82 % against 65 %), because the full 15 % is held longer within the episode.
- **By site,** humidity is weakest at FAWN (48 % of steps and drifts detected, against 62 % at AZMET and 67 % at Kansas). Clipping at 100 % is ruled out (no attacked day was clipped). FAWN has the largest natural wandering of the three sites (its CUSUM threshold is the highest, 14.9), which is the likely cause; not yet verified.

### 5.4 Replay

The replay matcher catches all 36 replays on their first day, with no false alarm at any site. Two other parts catch most of them independently: Mahalanobis (35/36) and CUSUM (29/36). A replayed week no longer agrees with the current NASA POWER week. **Replay is caught twice:** by its own copy, and by its disagreement with the independent witness.

### 5.5 Statistical against learned (D4)

- **S detects more than M** in every cell once M is tuned without 2024: 70 % against 32 % for steps by value, 81 % against 33 % for drifts by value.
- **M still adds a little on top of S:** "S or M" gains 1–5 points per cell (for example steps by value 70 → 75 %), and in the fusion M lifts the per-day ROC-AUC from 0.721 to 0.728.
- **S is the better replay detector** (100 % against 92 %). It searches every lag; M only looks 7, 28 and 364 days back.
- **S explains itself.** Every alarm comes with a variable, a direction, an estimated onset and an attack type. M gives a score.
- **Together** ("S or M"), they reach 75–95 % on steps and drifts by value or range, at the cost of 6.3 false alarms per station-year. The trust score combines them better than a plain OR: it requires agreement or persistence before quarantining a station (docs/trust-and-response.md).

### 5.6 Headline for the report

- On the three development sites, with the attacker signing false values at the station, detector S catches **every seven-day replay on its first day**, and catches 12 % steps and drifts up to 15 % in **70–94 %** of cases when the percentage is read as relative to the value or the range. That costs **4.7 false alarms per station-year** for S and 1.7 for M.
- Attacks smaller than about 0.7 σ of the station-to-reference difference are mostly missed. That includes every "12 % of the standard deviation" case and most wind cases. **This is the physical limit of checking a point sensor against a 50 km reference,** and closing it needs a second independent witness: neighbouring stations, or Sentinel-2.
