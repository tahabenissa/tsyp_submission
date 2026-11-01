# 05 — Evaluation plan

Track 2 — False Data Injection, in-situ sensing. Covers **standard scenario & evasion (20 pts)** and the evaluation half of **detector design & evaluation (20 pts)**, plus the five metrics the brief requires.

## The claim we are testing

> With the defence, a falsified sensor stream does not turn into a wrong decision; without it, it does. The defence detects the three official attacks at a site it has never seen, costs little, does not mistake real weather for an attack, and bounds how large a bias even a fully informed attacker can sustain.

Every experiment below supports or bounds one part of that sentence.

## Data

### Official reference datasets

| Dataset | Role | Access | Notes |
|---|---|---|---|
| **NASA POWER Daily API** | The trusted daily reference for any point on Earth | Public web API, no account; responses cached locally with a checksum | Gridded: a cell is tens of kilometres wide. Record the API version returned with each response |
| **Copernicus Sentinel-2 L2A** | The orbital context: cloud, snow, vegetation and moisture indicators around the site | Copernicus Data Space (free account), or a public catalogue mirroring the same L2A product | Only small windows are read. Record product identifiers and sensing times. Keep credentials out of the repository |

### The sensor series

The deck says "a real environmental time series". Until the organizers say which, both readings of that sentence are supported:

| Reading | Sensor series | Reference |
|---|---|---|
| **A — independent station** (our main case) | An authentic public weather-station record | NASA POWER at the station's position + Sentinel-2 |
| **B — the official series itself** | A NASA POWER series for a site | Neighbouring NASA POWER cells, the other variables, Sentinel-2 — never the same cell |

Candidate public station archives for reading A. Check each licence and record the exact stations and date ranges used.

| Candidate | Why |
|---|---|
| US Climate Reference Network, daily product | High-quality stations with temperature, rain, solar radiation and humidity in one record |
| NOAA Global Summary of the Day | Worldwide, including North Africa; temperature, dew point, wind, pressure, rain |
| Global Historical Climatology Network, daily | Worldwide, very long records; mainly temperature and rain |

### Development sites

Six to eight sites in contrasting climates — semi-arid Mediterranean (at least one in North Africa), temperate, continental, humid — chosen in the first days. The final test site is hidden, so no result may rest on one site.

### What "clean" means

Real records contain genuine faults. Before injecting anything:

- periods flagged by the provider are labelled **fault**, not clean and not attack;
- the detector's behaviour on real faults is reported separately — flagging them is correct behaviour, but it is not an attack detection;
- extreme-weather periods (heatwaves, cold spells, heavy-rain weeks) are labelled from the reference so false alarms can be measured on them specifically.

### Splits

| Set | Content | Used for |
|---|---|---|
| Train | Clean data, earlier years, a subset of sites | Calibration, baselines and the one-class model |
| Validation | A later period + injections with one parameter range | Thresholds, trust bands, probability calibration |
| Test | A still later period **including genuine extreme weather** + injections with different parameter ranges and seeds | Every reported number |
| Held-out sites | At least two sites absent from training and validation | Does it work where it has never been? This mirrors the hidden site |
| Held-out injection | An injection **type** absent from validation | Generalisation claim |

Splits are by time and by site, never random: neighbouring days are highly correlated and a random split leaks. Thresholds are frozen before the test set is touched.

## Configurations compared

| ID | Configuration | Purpose |
|---|---|---|
| **C0** | No security | The "without" baseline |
| **C1** | Standard quality control only | What operational practice already catches |
| **C2** | Provenance only (L1) | What cryptography alone achieves |
| **C3** | L1 + single-sensor analysis (L2) | Without independent context |
| **C4** | Full system (L1 + L2 + L3) | The proposal |

C1 matters: it is the fair baseline. Beating "nothing" is easy; the claim is that we beat what a careful operator already does. Reporting C2 and C3 separately shows each layer earns its place.

## Scenarios

### S-STD — official standard scenario

Reported first and separately in the report.

| Attack | Official parameter | Our default until the organizers specify | Swept |
|---|---|---|---|
| Step bias | 12 % | Every value multiplied by 1.12 or 0.88 from a random onset day | Variable, sign, onset season |
| Gradual drift | Up to 15 % | Linear ramp from 0 to 15 % over 30, 60 and 90 days | Variable, sign, ramp length |
| Replay | Seven samples | Seven consecutive days replaced by seven consecutive days from earlier in the same series | Source offset, variables replayed |

Run three ways:

1. **File mode on development sites** — the series arrives with the injection already inside, as the jury will supply it.
2. **File mode on held-out sites** — same, at sites never used for anything.
3. **Stream mode at the three attacker positions** — to show that the same injection is *prevented* in transit and in the pipeline, and *detected* at the station.

Each injection is also run under the alternative meanings of "12 %" (of the value, of the variable's range, of its standard deviation), so the result table is ready whichever the organizers confirm.

### Blind rehearsal

One team member picks a site and an interval the others do not know, injects the three attacks with parameters of their choosing, and hands over only the series and the coordinates. The others run file mode once, without tuning. The outcome is reported as it is. Repeat once more after fixes, with a new site.

### Injection suite

Our own scenarios beyond the official three. Each run at every attacker position where it applies.

| ID | Scenario | Attack | Varied parameters |
|---|---|---|---|
| S0 | Clean operation, ordinary and extreme weather | none | Period, site — measures false alarms |
| S1 | Step bias sweep | F1 | Magnitude from 2 % to 20 %, variable, sign |
| S2 | Drift sweep | F2 | Final offset, ramp length |
| S3 | Replay sweep | F3 | Length from 3 to 14 days, source offset |
| S4 | Freeze | F4 | Duration |
| S5 | Event masking or fabrication | F5 | Event type, size |
| S6 | Noise and spikes | F6 | Level, rate |
| S7 | Suppression | F7 | Duration, timing |
| S8 | Delay / date shift | F8 | Shift length |
| S9 | Coordinated | F9 | Number of variables, number of stations |
| S10 | Provenance stripping | F10 | — |
| S11 | Station key compromise | F11 | Combined with S1–S5 |

S1 gives the curve the jury will want next to the official number: detection rate and latency against bias size, with 12 % marked on it.

### Evasion suite

| ID | Evasion | Question answered |
|---|---|---|
| V1 | Slower, smaller drift (E1) | How slow must a drift be to pass, and how long does it then take to matter? |
| V2 | Stay in bounds (E2) | What does quality control alone miss? |
| V3 | Consistent multi-variable lie (E3) | What remains detectable when the physics is respected? |
| V4 | Analogue replay (E4) | Replay of the past week that best matches the current reference weather |
| V5 | Perturbed replay (E5) | How much added noise defeats exact matching, and does the reference still catch it? |
| V6 | Hide in the reference's error (E6) | Detection per variable and season; with and without a clear Sentinel-2 view |
| V7 | Baseline poisoning (E7) | Effect of an injection present during calibration; calibrated versus cold-start mode |
| V8 | Fault mimicry (E8) | Injection shaped like common sensor ageing |
| V9 | White-box optimisation (E9) | The largest undetected manipulation |

The key result is the **stealth budget**: for each variable, the largest bias a white-box attacker can sustain for 30 days while keeping every score under threshold, in per cent and in physical units. Below 12 % means the official step is within reach for that variable; above means it is not, and the report says so.

Evasion results are reported including the failures. A defence presented with no weak point is less convincing than one with a measured boundary.

## Metrics and how each is measured

### Detection quality

| Metric | Definition |
|---|---|
| Episode detection rate | Injection episodes flagged before they end; per attack type, per variable, per site |
| Detection rate (TPR) | Injected readings flagged / injected readings |
| TPR at fixed FPR | Detection rate at 1 % and 0.1 % false-positive rate |
| ROC-AUC, PR-AUC | Threshold-free comparison of detectors S and M |
| Onset error | Days between the true onset and the estimated one |
| Type identification | Share of detected episodes labelled with the right attack type |
| **Probability calibration** | Reliability diagram and Brier score of the compromise probability |
| **Wrong-decision rate** | Share of attack episodes in which the decision level differs from the one the true data would have given. Headline number for C0 versus C4 |
| Estimate error under attack | Error of the fused value used for the product, with and without the defence |

Report at three levels: **reading**, **episode**, and **decision** (what the analyst experiences).

### False alarms

- False-positive rate per reading on S0.
- **False alarms per station per year.**
- **False alarms during genuine extreme weather**, reported as its own number. This is the test a naive anomaly detector fails.
- False alarms per site, to show none of the climates is a weak spot.
- False quarantines: clean stations wrongly excluded, and for how long.
- Second tie-break in Phase 2, so it gets its own table.

### Latency

| Quantity | Measured as |
|---|---|
| Detection latency | Days from injection onset to first flag, to de-weighting and to quarantine |
| Margin to harm | Detection latency compared with the time the injection needs to change the decision level |
| Suppression detection time | From first missing reading to the silent state |
| Processing time | Wall-clock time per reading for verification, residuals and detection |

Cadence sets a floor: with daily data, a detector cannot react in less than a day, and a seven-day replay is over within a week. State the cadence beside every latency number.

### Memory

- Peak resident memory of the pipeline, with and without the defence.
- Persistent state per station in bytes.
- Size on disk of models, calibration tables and the reference cache.

### Security overhead

- Bytes added per record, as an absolute number and relative to the payload.
- Sign time on the station side, verify time at the service.
- CPU time per reading for the whole defence relative to plain ingestion.
- If compact signing is implemented: overhead versus tamper-detection delay as batch size changes.

### Statistical rigour

- Every rate with a confidence interval (Wilson for proportions, bootstrap for AUC). Use a block bootstrap, because days are correlated.
- Several seeds for injection placement and parameters; report mean and spread.
- State the number of readings, episodes and sites behind every figure.
- State the hardware (CPU model, RAM, OS) and software versions.

## Result tables to fill

Standard scenario, file mode, test period:

| Attack | Sites | Episodes | Detected | Median latency (days) | Onset error (days) | False alarms per station-year |
|---|---|---|---|---|---|---|
| 12 % step | development | | | | | |
| 12 % step | held-out | | | | | |
| Drift to 15 % | development | | | | | |
| Drift to 15 % | held-out | | | | | |
| 7-sample replay | development | | | | | |
| 7-sample replay | held-out | | | | | |

Standard scenario per variable (episode detection rate, median latency):

| Variable | 12 % step | Drift to 15 % | 7-sample replay |
|---|---|---|---|
| Temperature | | | |
| Humidity | | | |
| Wind | | | |
| Solar irradiance | | | |
| Pressure | | | |
| Precipitation | | | |

Headline table, decision level:

| Scenario | C0 wrong decisions | C1 | C2 | C3 | C4 | C4 detection latency |
|---|---|---|---|---|---|---|
| S-STD step | | | | | | |
| S-STD drift | | | | | | |
| S-STD replay | | | | | | |
| S4 freeze | | | | | | |
| S5 masking / fabrication | | | | | | |
| S6 noise and spikes | | | | | | |
| S7 suppression | | | | | | |
| S8 delay | | | | | | |
| S9 coordinated | | | | | | |
| S10 provenance stripping | | | | | | |
| S11 key compromise | | | | | | |

Detector comparison, reading level, on the test set:

| Detector | ROC-AUC | TPR @ 1 % FPR | TPR @ 0.1 % FPR | Held-out injection TPR | Held-out site TPR | FPR in extreme weather | Time per reading | Memory |
|---|---|---|---|---|---|---|---|---|
| Quality control only | | | | | | | | |
| S statistical | | | | | | | | |
| M one-class (best PyOD model) | | | | | | | | |
| Supervised reference | | | | | | | | |

Ablation, which residual groups matter:

| Residuals used | Step detected | Drift detected | Replay detected | FPR in extreme weather |
|---|---|---|---|---|
| Temporal only | | | | |
| + physical | | | | |
| + replay features | | | | |
| + NASA POWER reference | | | | |
| + Sentinel-2 context (all) | | | | |

Cost table:

| Component | Bytes per reading | Time per reading | Memory |
|---|---|---|---|
| Record + signature | | | |
| Quality control and alignment | | | |
| Residual generation | | | |
| Detector S | | | |
| Detector M | | | |
| Total vs plain ingestion | | | |

## Figures for the report

1. System architecture.
2. Map of development and held-out sites.
3. Station against reference on clean data, before and after calibration.
4. Residuals on clean data, ordinary days versus genuine extreme weather (the validation gate).
5. One 12 % step over time: true data, injected data, reference residual, running sum, trust score, actions.
6. The same for the drift and for the replay.
7. Detection rate and latency against bias size, with 12 % marked.
8. ROC curves, quality control versus detector S versus detector M.
9. Reliability diagram of the compromise probability.
10. Wrong-decision rate, C0 to C4, per scenario.
11. Stealth budget per variable against 12 %.
12. What Sentinel-2 adds: detection with and without it, split by cloud cover.

## Reproducibility

- One command regenerates every table and figure from a fresh clone.
- Each experiment is a YAML file under `scenarios/`; the report cites the file name beside each result.
- Seeds fixed and recorded; dependency versions pinned.
- Reference data fetched by script and cached with checksums; the cache for the reported sites is small enough to ship, so results reproduce without a network connection. Nothing large is committed.
- A reduced "quick" mode on one site and a short period finishes in a few minutes for reviewers; the full mode reproduces the report numbers.
