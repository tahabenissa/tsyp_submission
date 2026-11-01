# 01 — Phase 1 requirements

What we must hand in by **3 November 2026, 23:59 GMT+1**, why each item exists, and how we will know it is done. Track 2 — False Data Injection, in-situ sensing.

## Framing we must get right first

The challenge title is *Ground Truth Under Attack*. In-situ sensors **are** the ground truth: satellite products are calibrated against them and decisions are taken on them directly. The track's question is: *is this sensor stream consistent with its context?* Our scenario:

> A weather station in a field reports daily temperature, humidity, wind, rain and solar radiation. Those numbers feed irrigation advice, drought monitoring and index-based crop insurance. An attacker falsifies them — a step bias, a slow drift, or a week of old data played again — so that a decision goes the way the attacker wants. We prove where each reading came from, score how far each station can be trusted by checking it against independent context, and keep a falsified reading from driving a decision.

Four consequences:

- Every measurement in the prototype comes from an **authentic public dataset**. Attacks are injected into real records, so ground-truth labels are exact.
- **The official reference data is the independent witness.** NASA POWER gives a daily reference for the same place and day; Sentinel-2 L2A gives a view from orbit that no ground attacker can touch. A station that drifts away from both is lying or broken. This is where the remote-sensing expertise enters, and it must be visible in the report.
- **The three official attacks come first.** A 12 % step bias, a gradual drift up to 15 % and a seven-sample replay are implemented, evaluated and reported before anything else.
- **The site is hidden in the final test.** Nothing in the pipeline may depend on a particular station. The input is a series plus coordinates.

The maritime idea we started from is no longer the scenario: the official data has no wave measurements and Sentinel-2 cannot see a storm at sea. What carries over is the method — signed readings, then detection of disagreement between a sensor and independent witnesses.

## The four things to submit

| Item | Content | Done when |
|---|---|---|
| **Anonymous report** | PDF covering the six deliverables, results, limitations | Every rubric line has a section and at least one figure or table; PDF metadata is clean |
| **GitHub repository** | Source, scenario configs, tests, docs, pinned dependencies | A fresh clone reproduces every number in the report with one command |
| **Prototype** | Runnable end-to-end pipeline: reading → sign → telemetry → inject → verify → align with context → detect → trust score → respond → product | `run_all` completes on a laptop CPU in minutes and writes metrics and figures |
| **Documentation** | README, this `docs/` folder, dataset instructions | A stranger can install, run and understand it without contacting us |

## The six deliverables, concretely

### D1 — Threat model & segment analysis (15 pts)

Required content:

- Segment description: sensors, logger, telemetry, platform, processing, decision — with trust boundaries.
- Assets and the property each needs (origin, integrity, freshness, availability, truthfulness).
- Attacker profiles: at the sensor, on the telemetry, inside the data pipeline — including the insider who benefits from a false reading.
- A taxonomy of injection attacks with preconditions, effect and real-world impact, the three official attacks first.
- Evasion strategies an informed attacker would use.
- Attack-to-control mapping and stated residual risk.
- Evidence the threat is real.

Acceptance: every injection in the evaluation appears in the threat model, and every attack in the threat model is either evaluated or explicitly declared out of scope with a reason.

Specification: [03-threat-model.md](03-threat-model.md).

### D2 — Platform / architecture / trust anchor (15 pts)

Required content:

- Block diagram of the whole system and a sequence diagram of one reading becoming a decision.
- The trust anchor: per-station identity keys, where they live, how stations are enrolled with their position, how keys rotate and are revoked.
- Provenance record: what is bound to each reading and carried through processing into the product — including which reference data was consulted.
- Record format with byte-level overhead.
- Verification algorithm at the service, including anti-replay state.
- Justification that it is affordable (software only, standard primitives).

Acceptance: the trust mechanism is implemented, unit-tested, and its overhead is measured rather than estimated.

Specification: [02-architecture.md](02-architecture.md).

### D3 — Signal processing (15 pts)

Required content:

- Pre-processing of the daily series: quality control, calendar alignment, gap handling.
- **Handling of spatial and temporal mismatch** between a point sensor and a gridded reference: per-site calibration, day-boundary alignment, accumulation for rainfall.
- Temporal modelling: what the station should read, given the season and its own recent history.
- Physical-consistency residuals between variables.
- Reference residuals against NASA POWER.
- Orbital-context residuals against Sentinel-2 L2A indicators.
- Replay analysis and change-point detection.
- At least one figure showing a residual on clean versus injected data.

Acceptance: on clean data, each residual is shown to be small and well-behaved **during genuine extreme weather and across climates**. This is the gate that makes every later result credible.

Specification: [04-signal-processing-and-detection.md](04-signal-processing-and-detection.md).

### D4 — AI or statistical detection (20 pts)

Required content:

- A statistical detector (interpretable baseline) **and** a learned detector, compared on the same data.
- The output the track asks for: a **compromise probability and a gradual trust score**, with evidence that the probability is calibrated.
- Training protocol: clean data only for the main model; strict train / validation / test separation by time and by site.
- Threshold selection method and the chosen operating point.
- ROC and precision-recall curves, detection rate at fixed false-alarm rates, confidence intervals.
- Ablation: which residual groups matter, including what Sentinel-2 adds.
- Latency and memory of the detector itself.

Acceptance: results are reported on test data never used for training or threshold tuning, and on at least two sites the pipeline never saw.

Specification: [04-signal-processing-and-detection.md](04-signal-processing-and-detection.md) and [05-evaluation-plan.md](05-evaluation-plan.md).

### D5 — Adversarial validation & response (20 pts, "standard scenario & evasion")

Required content:

- Results on the **official standard scenario** — 12 % step, drift up to 15 %, seven-sample replay — on the official reference data.
- A blind rehearsal: one team member injects at a site and interval the others do not know.
- Results on our own injection suite.
- Results against **adaptive attackers** who try to evade each layer, including the cases where they succeed.
- The with/without comparison: how often a falsified reading changes the decision **without** the defence and **with** it.
- The response policy with the four graded actions: de-weighting, verification request, quarantine, alert.

Acceptance: at least one evasion experiment per defence layer, with an honest statement of where the defence stops working.

Specification: [05-evaluation-plan.md](05-evaluation-plan.md).

### D6 — Documentation using the official reference datasets (5 pts clarity + part of the 10 pts feasibility)

Required content:

- Dataset table: name, provider, licence, sites, date range, request or product identifiers, checksum.
- Scripts that download or locate the data; no large data committed.
- One-command reproduction, pinned dependency versions, fixed random seeds.
- Hardware used and wall-clock run time.

Acceptance: a team member who did not write the code reproduces the headline table on a different laptop.

## Mandatory metrics

The brief names five. Each must appear in the report as a number with a method.

| Metric | What we report |
|---|---|
| Detection quality | Episode detection rate per attack type; detection rate at fixed false-alarm rates; ROC-AUC; onset-date error; calibration of the compromise probability; wrong-decision rate |
| False alarms | False-positive rate per reading; false alarms per station per year; **false alarms during genuine extreme weather**; false quarantines |
| Latency | Days from injection onset to first flag and to quarantine; processing time per reading |
| Memory | Peak resident memory of the pipeline; model size on disk; per-station state |
| Security overhead | Extra bytes per record; sign and verify time; CPU time of the whole defence relative to plain ingestion |

## The central difficulty

Two problems, and the design turns on both.

**Real weather looks like an anomaly.** A heatwave, a cold front or a week of heavy rain is rare and extreme. A naive detector flags it — exactly when the data matters most. The answer is to detect **disagreement, not extremes**:

- In **real weather**, everything agrees: the station, the reference for that place and day, and what the satellite sees.
- In an **injection**, the falsified station disagrees with at least one independent witness.

**The official attacks are small.** A 12 % bias is about as large as the normal difference between a point station and a 50 km grid cell. On any single day it hides in that difference. The answer is to **accumulate evidence over days**: a small disagreement that never averages out is not noise.

The report must show both explicitly: false-alarm numbers computed on real extreme-weather periods, and detection latency for attacks that no single-day test can see.

## Priority order if time runs short

1. NASA POWER client with caching, a real station series, the three official injections with exact labels.
2. Calibration against the reference, reference residual, statistical detector (cumulative-sum test, change points, replay matcher); the standard-scenario table with false-alarm numbers.
3. Signed readings and verification; trust score and the four responses; the with/without comparison.
4. Sentinel-2 context indicators and their residual.
5. Learned detector and comparison with the statistical one; held-out sites.
6. Evasion experiments and the stealth budget.
7. Our own extra injections beyond the official three.
8. Polished figures, dashboard, extras.

Items 1–6 are the submission. Item 7 strengthens it. Item 8 is Phase 2 material.

## Anonymity checklist

Run this before submitting, even though the committee also sanitizes.

- [ ] `git config user.name` and `user.email` are neutral. **The working repository's history already carries a real author identity on every commit**, so the submission is exported to a fresh repository with a clean history.
- [ ] Repository is not hosted under an account or organisation name that identifies anyone (confirm the submission method with the organizers).
- [ ] No names, university, student-branch or chapter names, or logos in the report, README, code comments, licence file, figures or slides.
- [ ] PDF metadata cleared (author, creator, company).
- [ ] Notebook outputs cleared; no absolute paths containing a username.
- [ ] No screenshots showing usernames, desktops, browser profiles or chat windows.
- [ ] Source sketches and scratch notes kept out of the repository unless reviewed.
- [ ] Citations to our own prior work, if any, written in the third person.
- [ ] No data-service account names, API keys or tokens committed (the Copernicus Data Space account in particular).
