# 06 — Project plan

Track 2 — False Data Injection, in-situ sensing. Rewritten 10 October 2026 after the info-session material arrived. Target: submit **Monday 2 November**, one day ahead of the deadline (3 November, 23:59 GMT+1). That is 24 days. No code exists yet.

## What changed on 10 October

- The official reference data is **NASA POWER Daily + Sentinel-2 L2A**. The sensor is now a land weather station, not an ocean buoy.
- The standard test is known: **12 % step, drift up to 15 %, seven-sample replay**, at a hidden site.
- The deadline is confirmed as 3 November.
- The plan is reordered so that the standard scenario produces numbers first and everything else is added around it.

## Questions for the organizers

Send these now, in one message, to the contact addresses on the last slide of the info-session deck. The first three affect how the standard scenario is run.

1. In the standard test, **which series is attacked**: an independent in-situ series that we compare with NASA POWER, or a NASA POWER series itself? Does the jury supply it as a file (which format, which variables), or only coordinates and dates?
2. **What are 12 % and 15 % relative to**: the value itself, the variable's range, or its standard deviation? Which variables and which sign? For temperature, which unit?
3. **Over how many samples** does the drift reach 15 %, and where are the seven replayed samples copied from?
4. Is a **clean history** for the hidden site provided before the attacked interval? Is **network access** to NASA POWER and Sentinel-2 available during the held-out test, or must the prototype run offline?
5. How is **Sentinel-2** expected to be used, and are public mirrors of the same L2A product acceptable?
6. How is the standard test **scored**: per sample or per episode, and how is a false alarm counted?
7. **Report format:** page limit, template, file type?
8. **How is the repository submitted** while keeping it anonymous?

Until the answers arrive, the defaults in [05-evaluation-plan.md](05-evaluation-plan.md#s-std--official-standard-scenario) are used and every alternative reading is kept runnable from a config file.

## Schedule

### Now — 10 to 12 October: data and the three attacks

Goal: a real series, its reference, and the official injections exist on disk.

- Send the organizer questions.
- Repository skeleton, neutral git identity, pinned environment, test runner.
- NASA POWER client with on-disk cache and checksums.
- Choose six to eight development sites and two held-out sites; station loaders.
- The three official injections with exact labels and a config file each.
- Register for Sentinel-2 access (accounts can take time).
- **Gate:** for three sites, a plot of station against reference on clean data, and the three injected series reproducible from one command.

### Week 2 — 13 to 19 October: the standard scenario produces numbers

Goal: the first standard-scenario table exists.

- Quality control, day-boundary alignment, calibration against the reference.
- Reference residual in both forms; temporal and physical residuals; replay features.
- **Gate:** residuals on clean data are small and stay small in genuine extreme weather and across sites.
- Detector S: running-sum test, change-point search with `ruptures`, trend test, replay matcher.
- Scenario runner and metrics; file mode end to end.
- Trust module: keys, enrolment, sign, verify, sequence, hash chain, with unit tests.
- Replace the expected-difficulty table in [04-signal-processing-and-detection.md](04-signal-processing-and-detection.md) with measured numbers.
- Threat-model section of the report drafted from [03-threat-model.md](03-threat-model.md).
- **Gate:** S-STD runs on the development sites from one command and prints detection rate, latency and false alarms.

### Week 3 — 20 to 26 October: context, learning, evasion

Goal: every number the rubric asks for exists in draft.

- Sentinel-2 context extraction and the orbital-context residual.
- Detector M: PyOD benchmark, pick one; supervised reference.
- Compromise-probability calibration, trust score, the four responses.
- Decision product and the with/without comparison; stream mode at the three attacker positions.
- Thresholds chosen on validation data; freeze.
- Held-out sites; first blind rehearsal.
- Evasion suite V1 to V9, including the stealth budget.
- Latency, memory and overhead measurement.
- Architecture, signal-processing and detector sections of the report drafted.
- **Gate:** all result tables filled, even if rough.

### Week 4 — 27 October to 2 November: harden and write

Goal: a stranger can reproduce it and the report reads cleanly.

- Full runs with final seeds; confidence intervals.
- Remaining injection-suite scenarios; held-out injection result.
- Second blind rehearsal at a new site.
- Final figures.
- Report complete by **Thursday 29 October**; internal review Friday.
- Fresh-clone reproduction test on a second laptop by someone who did not write the code.
- Export to a repository with clean history; anonymity checklist ([01-phase1-requirements.md](01-phase1-requirements.md#anonymity-checklist)).
- README and documentation pass.
- **Freeze Sunday 1 November. Submit Monday 2 November.**

## Workstreams

Five workstreams for up to five members. Assign by role; one person owns each.

| Stream | Owns | Main deliverable |
|---|---|---|
| **A — Data and remote sensing** | `data`, Sentinel-2 context, orbital-context residual | NASA POWER and Sentinel-2 ready to use for any coordinates; site selection; extreme-weather and fault labels; dataset documentation |
| **B — Signal processing** | `processing` | Quality control, alignment, calibration, temporal, physical, reference and replay residuals; the validation gate |
| **C — Trust and attacks** | `trust`, `sensor`, `transport`, `attacks`, threat model | Signed records, verifier, ledger; injection and evasion library, the three official attacks first |
| **D — Detection and evaluation** | `detect`, `eval` | Detectors S and M, probability and trust score, metrics, all tables and figures |
| **E — Integration and report** | `response`, `product`, scripts, repository, report | One-command pipeline, file mode, response policy, reproducibility, the anonymous report |

Interfaces between streams are fixed in the first three days: the table schema for readings, the residual vector layout, the label format for injections, and the config keys. Stream C's injections act on stream A's data, stream B's residuals consume both, and stream D consumes the residuals — agree the reading and residual formats first.

## Mapping work to points

| Rubric line | Pts | Stream | Evidence in the submission |
|---|---|---|---|
| Threat model & relevance | 15 | C, A | Threat-model section; injection taxonomy; ground-truth framing; the insider motive |
| Architecture & trust mechanism | 15 | C, E | Diagrams; record spec; tested verifier; ledger; provenance of reference data; measured overhead |
| Signal processing | 15 | B, A | Calibration for spatial and temporal mismatch; five residual families; validation on clean data including extreme weather |
| Detector design & evaluation | 20 | D | Two detectors against a QC baseline; calibrated probability and trust score; ROC; TPR at fixed FPR; ablation |
| Standard scenario & evasion | 20 | D, C | S-STD tables on development and held-out sites; blind rehearsal; evasion suite; stealth budget |
| Feasibility & local execution | 10 | E | Laptop CPU run time; zero-cost bill of materials; one command; offline cache |
| Clarity & reproducibility | 5 | E | README; pinned environment; fresh-clone test |

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A 12 % step is not detectable on some variables (wind, daily rain) | High | High | Measure it in week 2; use the log-ratio residual and accumulated totals; report per variable; ask the organizers which variables are tested |
| The organizers' meaning of "12 %", or the series they attack, differs from our default | Medium | High | Ask today; every reading kept runnable from config; reference built from neighbouring cells when the series is NASA POWER itself |
| The detector does not transfer to the hidden site | Medium | High | Site-agnostic design; cold-start mode; held-out sites; blind rehearsals |
| Detector flags real weather as attacks | High | High | Detect on residuals, not raw values; validation gate in week 2; extreme-weather false-alarm metric |
| Sentinel-2 access is harder than expected (registration, formats, cloud cover) | Medium | Medium | Register in the first days; read small windows only; the pipeline runs without it and the ablation shows its share |
| Sentinel-2 adds little against a 12 % step | High | Low | Present it honestly as the independent arbiter; show where it helps (drift, replay against the sky) |
| The reference is not independent of the station | Medium | Medium | Check per variable; prefer stations unlikely to have been used; state the limitation |
| Real sensor faults contaminate "clean" data | High | Medium | Use provider flags; report fault detection separately |
| Detector overfits to our own injection library | Medium | High | One-class training; held-out injection type and sites; frozen thresholds |
| Time-correlated data leaks between train and test | Medium | High | Split by time and site only; block bootstrap |
| No network during the held-out test | Low | High | Local cache; ask the organizers; document an offline run |
| Scope creep (dashboard, deep learning, more sensor types, a second scenario) | High | Medium | Priority list in [01-phase1-requirements.md](01-phase1-requirements.md#priority-order-if-time-runs-short) |
| Anonymity breach through git history or metadata | **Certain unless handled** — the working history carries a real identity | High — possible disqualification | Export to a clean history before submission; checklist |
| Report written in the last two days | High | Medium | Draft each section in the week its work is done |
| Results not reproducible on another machine | Medium | Medium | Pinned versions; fresh-clone test in week 4 |

## Definition of done for Phase 1

- [ ] Report covers all six deliverables and all five required metrics.
- [ ] The official standard scenario is reported on the official reference data, on development and held-out sites, per variable.
- [ ] One command reproduces every table and figure on a laptop CPU.
- [ ] File mode takes a series and coordinates and returns trust scores, episodes and actions.
- [ ] With/without comparison shows an injection changing the decision undefended and not when defended.
- [ ] False-alarm rate reported separately for genuine extreme weather.
- [ ] At least one evasion experiment per defence layer, with the stealth budget stated.
- [ ] Tests pass on a fresh clone.
- [ ] Anonymity checklist complete, including the clean-history export.
- [ ] Submitted by 2 November.

## Looking ahead to Phase 2

Carries 70 % of the final score. Design choices now that pay off later:

- **Held-out standard attack.** File mode, cold-start calibration, held-out sites and blind rehearsals are preparation for exactly this criterion and for the first tie-break.
- **Replayable demo.** A scenario is a config file plus cached data, so an attack can be replayed live: true data, falsified readings, the trust score falling, the decision holding.
- **Operator view.** A simple display of station trust and product confidence makes a seven-minute pitch land; keep `response` output structured so a display can be added without touching the core.
- **Low false alarms.** Second tie-break. Keep false alarms per station per year, and in extreme weather, visible from the start.
