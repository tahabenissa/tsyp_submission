# 00 — Challenge brief

Sources: the two-page brief *Ground Truth Under Attack: Securing the Earth Observation Chain*, the info-session deck (dated 20 September 2026) and the one-page *Official Reference Resources* sheet. The deck and the sheet reached us on 10 October 2026. Everything below is taken from those documents unless marked **[ours]**.

## What the challenge is about

Earth-observation (EO) products drive decisions in agriculture, insurance, water management and disaster response. Their trustworthiness depends on evidence of **origin, time, integrity and processing history** across the sensing, communication and product chain. Plausible-looking data may still be untrustworthy, and the failure can be silent: the pipeline keeps running while a corrupted observation reaches the analyst.

Four focus areas: **provenance, integrity verification, anomaly detection, controlled adversarial testing.**

The prototype must combine three kinds of expertise: remote sensing, signal/image processing, and computational intelligence / security analytics.

## Tracks (choose exactly one)

| Track | Segment | Question | Official reference data | Our choice |
|---|---|---|---|---|
| 1 — Secure Ground-Link Testbed | ground link | Can a stored signal or sequence be authenticated? | SatNOGS Network Observations | no (first plan, dropped) |
| 2 — False Data Injection | in-situ sensing | Is this sensor stream consistent with its context? | **NASA POWER Daily API + Copernicus Sentinel-2 L2A** | **Yes** |
| 3 — Trust the Pixel | imagery | Was this image altered or falsely attributed? | EuroSAT (Sentinel-2) | no |

All tracks share the same workload, metrics and scoring rubric.

## Track 2 in detail

> Use a real environmental time series and public orbital / contextual observations. Detect a step bias, gradual drift and replay while accounting for spatial/temporal mismatch and natural variability.

| Aspect | What the deck asks for |
|---|---|
| Processing | Time series, change points, sensor / context fusion |
| AI / detection | Compromise probability or gradual trust score |
| Output | Alert, quarantine, verification request, or de-weighting |

### The standard test

> Inject a **12 % step bias**, a **gradual drift up to 15 %**, and a **seven-sample replay** into a real series. Validate against contextual / orbital indicators. **Site and interval are hidden in the final test.**

### Official resources for Track 2

| Resource | Kind | What it is | How the organizers describe its use |
|---|---|---|---|
| NASA POWER Daily API | Dataset (official) | Daily weather and solar data: temperature, humidity, wind, solar radiation | Compare a sensor's readings against a trusted reference to spot inconsistencies |
| Copernicus Browser (Sentinel-2 L2A) | Dataset (official) | Platform to browse satellite imagery, including the Sentinel missions | Observe an area and compare how it changes across different dates |
| `ruptures` | Tool (optional) | Python change-point detection: sudden bias, gradual drift, regime change | Detect the step bias and gradual drift injected into the series |
| PyOD | Tool (optional) | 40+ anomaly-detection algorithms behind one API | Benchmark several methods and pick the one that best separates the attack from normal readings |

The sheet states that the datasets are the official reference data for each track's standard test, and that none of the tools is mandatory.

## Six mandatory deliverables

1. Threat model & segment analysis
2. Platform / architecture / trust anchor
3. Signal / image processing
4. AI or statistical detection
5. Adversarial validation & response
6. Documentation using the official reference datasets

## Challenge goal

- Use authentic public data.
- Apply the common standard scenario.
- Detect or prevent the attack.
- Report **detection quality, false alarms, latency, memory and security overhead**.
- No purchase required: a software or emulated trust anchor and local laptop execution are fully valid. Optional hardware earns no scoring advantage.

## Phases

| | Phase 1 | Phase 2 |
|---|---|---|
| Nature | Anonymous report + code | Working prototype + live or replayable attack demo |
| Deliverables | Anonymous report, GitHub repository, prototype, documentation | Final prototype, pitch |
| Anonymity | **Fully anonymous** | Non-anonymous |
| Weight | 30 % | 70 % |
| Outcome | Every registered team gets a score; up to 7 finalists | 3 winners |
| Pitch | — | English, 7 min + 3 min Q&A |

The administrative committee assigns a team code and sanitizes the repository before forwarding it to the jury. The same jury scores both phases.

## Dates

| Event | Date |
|---|---|
| Infosession | 20/09/2026 |
| Phase 1 deadline | **03/11/2026, 23:59 GMT+1** |
| Preselection announcement | 08/11/2026 |
| Final deadline | 11/12/2026 |

The two-page brief gave both 3 and 8 November for Phase 1. The info-session deck settles it: 3 November is the deadline, 8 November is the announcement.

## Scoring

Final score = 30 % × Phase 1 + 70 % × Phase 2.

**Phase 1 (100 points)**

| Criterion | Points |
|---|---|
| Threat model & relevance | 15 |
| Architecture & trust mechanism | 15 |
| Signal / image processing | 15 |
| Detector design & evaluation | 20 |
| Standard scenario & evasion | 20 |
| Feasibility & local execution | 10 |
| Clarity & reproducibility | 5 |

**Phase 2 (100 points)**

| Criterion | Points |
|---|---|
| End-to-end functional prototype | 20 |
| Provenance / security control | 15 |
| Processing & local detection | 15 |
| Held-out standard attack & evasion | 20 |
| Metrics, efficiency & accessibility | 10 |
| Documentation & reproducibility | 10 |
| Pitch & technical questions | 10 |

**Tie-break order:** held-out attack score, then lower false-alarm rate, then documented jury decision. No bonus points.

## Rules

- Student Branches only; maximum 5 members per team.
- Exactly one track.
- The official reference datasets are required for the standard scenario.
- Phase 1 anonymous, Phase 2 non-anonymous.

## What this tells us **[ours]**

- **The official data fixes the scenario.** NASA POWER is daily weather and solar data; Sentinel-2 is optical imagery of land and coastal areas. The sensor that fits is a **land weather station reporting daily values**, not an ocean buoy. Other authentic public data is allowed for our own extra scenarios, but the standard test must run on the official data.
- **The standard attacks are small.** A 12 % step and a drift up to 15 % are about the size of the ordinary disagreement between a point sensor and a gridded reference. No single reading gives them away; evidence has to be accumulated over days.
- **The final site is hidden.** The detector cannot be tuned to one station. It must work from coordinates and a series, wherever the jury points it.
- **40 of 100 Phase 1 points are evaluation** (detector evaluation 20 + standard scenario & evasion 20). A beautiful design with thin measurements loses to a simple design with rigorous numbers.
- **Evasion is scored explicitly, twice,** and the held-out attack is the first tie-break in Phase 2. This pushes us toward one-class / anomaly methods trained on clean data rather than a classifier trained on our own injected samples.
- **False-alarm rate is the second tie-break.** Report it prominently and pick operating points deliberately.
- **The expected output is a score, not a yes/no.** A compromise probability or gradual trust score, driving four graded responses.
- **Feasibility and local execution are worth 10 points.** Everything must run on a laptop, CPU only, from one command.

## Still open

To be obtained from the organizers. The first three affect the design of the standard-scenario run.

1. **Which series is attacked in the standard test:** an independent in-situ series that we compare against NASA POWER, or a NASA POWER series itself? Does the jury supply the series as a file, or only coordinates and dates?
2. **What the percentages are relative to:** the value itself, the variable's range, or its standard deviation? Which variables, which sign, and for temperature which unit?
3. **Shape of the drift and the replay:** over how many samples the drift reaches 15 %, and where the seven replayed samples are copied from.
4. Whether a clean history for the hidden site is provided before the attacked interval, and whether network access to the two data services is available during the held-out test.
5. How Sentinel-2 is expected to be used, and whether public mirrors of the same L2A product are acceptable.
6. Metric definitions for the standard test: per sample or per episode, and how a false alarm is counted.
7. Report format: page limit, template, language, file type.
8. How the repository is submitted so anonymity holds.
