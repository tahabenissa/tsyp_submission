# Project docs

Working title: **Trusted in-situ weather data for agriculture and water decisions** (TSYP14 technical challenge, Track 2 — False Data Injection, in-situ sensing segment).

One-sentence pitch: *field weather stations are the ground truth behind irrigation advice, drought monitoring and index insurance; we prove each reading's origin, score how far each station can be trusted by checking it against NASA POWER and Sentinel-2, and keep a falsified reading — a step bias, a slow drift or a replayed week — from driving a decision.*

| File | What it answers |
|---|---|
| [00-challenge-brief.md](00-challenge-brief.md) | What the challenge asks, the Track 2 standard test, official data, scoring, dates, what is still open |
| [01-phase1-requirements.md](01-phase1-requirements.md) | Exactly what we must hand in for Phase 1, mapped to the 100 points |
| [02-architecture.md](02-architecture.md) | System architecture, modules, trust anchor, record format, trust score, repo layout |
| [03-threat-model.md](03-threat-model.md) | Assets, attacker positions, injection attacks, evasion, controls, residual risk |
| [04-signal-processing-and-detection.md](04-signal-processing-and-detection.md) | Calibration against the reference, residuals, statistical and ML detectors, trust score, response |
| [05-evaluation-plan.md](05-evaluation-plan.md) | Data, the standard scenario, baselines, metrics, how each number is measured |
| [06-project-plan.md](06-project-plan.md) | Schedule to 2 November, workstreams, risks, questions for the organizers |
| [cahier_des_charges.pdf](cahier_des_charges.pdf) | Project specification for Phase 1: goals, scope, requirements, tests, risks |
| [guard_architecture.pdf](guard_architecture.pdf) | The architecture as seven layers, in plain words, on four pages |
| [code-architecture.pdf](code-architecture.pdf) | The repository and package layout, file by file, with the owner of each file |
| [project-plan-4-members.pdf](project-plan-4-members.pdf) | The plan for a team of four: one role each, week by week |

**What was built, and what it measured** (one file per stage, in pipeline order):

| File | What it answers |
|---|---|
| [datasets.md](datasets.md) | The three stations and NASA POWER: sources, dates, cleaning, checksums |
| [trust-module.md](trust-module.md) | Layer 1: station keys, signed records, verification, anti-replay, hash-chained ledger |
| [official-attacks.md](official-attacks.md) | The three official attacks: what "12 %" can mean, labels, scenario files |
| [how-to-simulate-attacks.md](how-to-simulate-attacks.md) | The commands to run and clean the three official attacks |
| [preparation.md](preparation.md) | Calibration against NASA POWER and the standardized residuals |
| [detector_s.md](detector_s.md) | Detector S, the statistical detector: CUSUM, Mahalanobis, replay matcher, trend |
| [detector_s-fixes.md](detector_s-fixes.md) | The review of detector S: bugs fixed, thresholds from a false-alarm budget, first numbers |
| [detector_m.md](detector_m.md) | Detector M, the learned one-class detector (LOF) |
| [evaluation.md](evaluation.md) | **The official standard scenario: 756 attacked runs, detectors S and M, results** |
| [trust-and-response.md](trust-and-response.md) | **Compromise probability, trust score, the four responses, decisions with and without the defence** |

## Read this first

1. **The standard test is the centre of the project.** A 12 % step bias, a gradual drift up to 15 % and a seven-sample replay, injected into a real series, at a site and interval hidden in the final test. It is worth 20 points in each phase and is the first tie-break.
2. **The official data is fixed:** NASA POWER Daily API and Copernicus Sentinel-2 L2A. They must be used for the standard scenario.
3. **Some details are still open** — which series is attacked, and what the percentages are relative to. See [06-project-plan.md](06-project-plan.md#questions-for-the-organizers).
4. **The deadline is 3 November 2026, 23:59 GMT+1.** We submit on 2 November.
5. **Phase 1 is anonymous.** No names, unit names, logos or identifying repository metadata anywhere — including git author fields, PDF metadata and absolute paths in notebook outputs. Checklist in [01-phase1-requirements.md](01-phase1-requirements.md#anonymity-checklist).

## How the idea got here

| | First idea (Track 1) | Second plan (Track 2, ocean buoys) | Current (Track 2, official data) |
|---|---|---|---|
| Protected segment | Satellite link to a vessel | Ocean buoys and their data path | **Land weather stations** and their data path |
| What the attacker falsifies | The alert message on the link | Wave and wind measurements | **Daily weather measurements** |
| Independent witness | — | Neighbouring buoys, satellite altimeter and scatterometer | **NASA POWER reference, Sentinel-2 L2A indicators** |
| Headline attack | Injected "no danger" message | A storm hidden by replayed calm data | **The three official attacks: 12 % step, 15 % drift, 7-sample replay** |
| Decision at stake | A ship's route | A storm warning | **Irrigation advice, drought class, insurance trigger** |
| Cadence | Radio frames | Minutes to hours | **Daily** |
| Detector output | Legitimate / suspicious | Accept / suspect / reject | **Compromise probability and trust score** |

What stayed the same through both changes: sign every reading at the source, then detect disagreement between a sensor and independent witnesses rather than unusual values, and measure the result with and without the defence.

The buoy plan was dropped on 10 October 2026 because the official data cannot support it: NASA POWER has no wave data, and Sentinel-2 is optical imagery that cannot observe a storm at sea.
