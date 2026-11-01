# Compromise probability, trust score, responses and the with/without comparison

Step 4 turns the detector outputs into what the track asks for ("a compromise probability or gradual trust score, driving four graded responses") and measures the effect on a decision. Reproduce with:

```powershell
.\.venv\Scripts\python.exe scripts\run_trust.py            # full grid, about 15 minutes
.\.venv\Scripts\python.exe scripts\run_trust.py --quick    # 20 scenarios per site
```

**Code**

| File | Role |
|---|---|
| `src/sensorguard/detect/fusion.py` | compromise probability |
| `src/sensorguard/detect/trust_score.py` | trust and bands |
| `src/sensorguard/response/policy.py` | the four responses |
| `src/sensorguard/product/water_balance.py` | decision product |
| `src/sensorguard/eval/trust_eval.py` | evaluation |
| `config/trust.yaml` | every setting |

Results: `results/eval/trust/summary.md`.

```
residuals ─► detector S, detector M ─► daily features ─► compromise probability p
           ─► trust (falls fast, recovers slowly) ─► band: trusted / de-weighted / quarantined
           ─► responses: de-weight, verification request, quarantine, alert
           ─► series used downstream ─► 30-day water balance ─► decision level
```

---

## 1. Compromise probability (`fusion.py`)

The detectors speak different units: a CUSUM sum, a squared distance, a copy distance, an LOF score. Each day they become nine features, all **causal** (that day and earlier only):

| Feature | Meaning |
|---|---|
| `cusum_ratio` | CUSUM statistic / its threshold (1 = at the alarm level) |
| `cusum_recent` | CUSUM alarms in the last 30 days: a lasting attack keeps re-alarming |
| `maha_log` | log(1 + Mahalanobis d² / threshold): one unusual day |
| `replay_log` | log(tolerance / copy distance): above 0 when today's week copies an earlier one |
| `trend_ratio` | trend \|z\| / its threshold |
| `gap7`, `gap30` | largest \|7-day\| and \|30-day\| mean standardized residual over temperature, humidity, wind and solar, divided by the same station's 95th percentile on its training years. A drift is invisible day by day but clear as a monthly average. Without the per-station scale, the feature quarantined 47 clean FAWN days, whose month-long gaps are naturally larger (95th percentile 1.68 σ against about 1.03 σ elsewhere). |
| `m_flag`, `m_recent` | detector M alarm today, and in the last 30 days |

A **logistic regression** maps them to the probability that the day is attacked. It is fitted by maximum likelihood on labelled runs (attacked days = 1, all other days = 0). Its coefficients are readable and are reported per fit.

**Leave one site out.** The model applied at a site is fitted on the attacked and clean runs of the **two other sites** only. Every probability at a site comes from a model that never saw that site, which is what the hidden final-test site will be.

**Calibration** is checked on the held-out sites:
- a **reliability table**: of the days scored near 0.3, about 30 % should really be attacked;
- the **Brier score**, against the no-skill score of always predicting the base rate;
- ROC-AUC.

The probability is relative to the share of attacked days in the evaluation runs (about 15 %). A deployment where attacks are rarer shifts it with `fusion.prior_shift` (Bayes on the odds); the trust bands below are set on the same scale.

## 2. Trust score (`trust_score.py`)

Each day:

```
risk_t = risk_{t-1} + a · (p_t − risk_{t-1})        trust_t = 1 − risk_t
a = 0.5  if p_t > risk_{t-1}   (bad evidence: trust falls fast)
a = 0.05 otherwise             (good evidence: trust recovers slowly)
```

One day at p = 0.9 takes trust from 1 to 0.55. Half of the lost trust comes back only after about 14 quiet days. The asymmetry is deliberate:
- one calm day cannot restore a station that has just been caught;
- an attacker cannot reset trust by pausing for a day.

**Bands, set on data and frozen.** The limits are quantiles of the trust reached on **clean** days of the fitting sites:

| Band | Limit |
|---|---|
| **de-weighted** | trust below the level clean days go under 5 % of the time |
| **quarantined** | trust below the level clean days go under 0.5 % of the time |

The cost on honest stations is therefore fixed before any attack result is seen. Quarantine has **hysteresis**: a station is released only when trust climbs back above the de-weight limit.

## 3. The four responses (`policy.py`)

| Response | When | What happens |
|---|---|---|
| **De-weighting** | band de-weighted | value used = w · station + (1 − w) · calibrated reference. w falls linearly from 1 to 0 across the band |
| **Verification request** | de-weighted and trust still falling | ask for independent evidence: the next clear Sentinel-2 view, a neighbouring station, a technician. At most once every 14 days |
| **Quarantine** | band quarantined | w = 0: the implicated variables are replaced by the calibrated reference |
| **Alert** | on entering quarantine | the operator gets the reason: the feature that contributed most to the probability, plus the variable, direction, type and estimated onset of the CUSUM episode |

**Calibrated reference.** NASA POWER moved to the station's scale with the per-season calibration offsets: POWER + offset, or the inverse of the log ratio for wind.

**Only implicated variables are replaced.** A first version replaced the whole record in quarantine, rain included. Measured on 60 runs, that made decisions **worse**: wrong-decision days went from 14 % to 33 %. Rain is where a point gauge and a 50 km grid differ most, so substituting POWER's rain changes the 30-day water balance by itself. A variable is now implicated when its standardized residual against NASA POWER has a 14-day mean beyond 1 σ. A detected replay implicates the whole record, since the whole record was copied. Rain is never replaced otherwise. The official attacks do not touch it and detector S does not monitor it.

**Product confidence.** A decision is issued as **TRUSTED** only if the station was trusted on every day of the 30-day window behind it. Otherwise it is **DEGRADED** (pending verification).

## 4. Decision product (`water_balance.py`)

Irrigation advice, drought classes and index-insurance triggers are all thresholds on a water balance. The product is:

- **ET0**, the FAO-56 Penman-Monteith reference evapotranspiration, computed daily from temperature, humidity, wind and solar radiation.
- **B**, the 30-day water balance: B = Σ(rain − ET0).
- **The decision level**, per site and calendar month, from the clean training years:

| Level | Condition | Meaning |
|---|---|---|
| 0 | B ≥ 30th percentile | normal |
| 1 | B below the 30th percentile | dry, irrigation advised |
| 2 | B below the 10th percentile | severe drought, insurance trigger |

**Why an attacker cares.** +12 % on temperature or solar radiation raises ET0, makes the balance look drier, and can trigger a payout or an irrigation order.

**Stated simplifications:**
- only the daily mean temperature is available (FAO-56 prefers the daily maximum and minimum);
- wind is used as measured, with no height correction;
- soil heat flux is 0 for daily steps;
- elevation is 0 m.

These do not bias the with/without comparison, because truth, C0 and C4 all go through the same formula.

## 5. With and without (`trust_eval.py`)

For every attacked run, three decision series are compared over the attack and the 30 days after it (the 30-day balance keeps the attack in it that long):

| Series | Built from |
|---|---|
| **truth** | the clean station series |
| **C0, no defence** | the attacked series |
| **C4, full system** | the attacked series after de-weighting and quarantine |

**Metrics:**
- **Wrong-decision episode:** at least one day in the window where the level differs from the truth.
- **Wrong days:** the share of days in the window where it differs.
- **Wrong and issued as TRUSTED:** a wrong decision that the system issued without any warning. This is the attacker's real win. A wrong decision issued as DEGRADED has already been flagged for verification.

**Cost on honest stations,** from the clean 2024 run of each held-out site:
- de-weighted days;
- quarantine days and quarantines per year;
- verification requests per year;
- decision days that the defence itself changed.

At P1 (file mode), provenance alone (configuration C2) changes nothing, because the station signs its own false values. So C2 = C0 here, and the comparison that matters is C0 against C4.

---

## 6. Results

The same 756 attacked runs as the detection evaluation, plus the clean 2024 run of each site, leave one site out. Run time 16 min. All tables: `results/eval/trust/summary.md`. Every run: `results/eval/trust/runs.csv`.

### 6.1 The compromise probability is calibrated on sites it never saw

| Held-out site | Brier | Brier, no skill | ROC-AUC (per day) |
|---|---|---|---|
| AZMET | 0.122 | 0.162 | 0.76 |
| FAWN | 0.132 | 0.162 | 0.73 |
| Kansas | 0.139 | 0.162 | 0.72 |
| all | 0.131 | 0.162 | 0.73 |

Reliability, all held-out days (277,794 days):

| Probability bin | Mean probability | Share really attacked |
|---|---|---|
| 0.0–0.1 | 0.07 | 0.10 |
| 0.1–0.2 | 0.14 | 0.13 |
| 0.2–0.3 | 0.25 | 0.24 |
| 0.3–0.4 | 0.34 | 0.30 |
| 0.4–0.5 | 0.44 | 0.46 |
| 0.5–0.6 | 0.55 | 0.59 |
| 0.6–0.7 | 0.64 | 0.70 |
| 0.7–0.8 | 0.75 | 0.59 |
| 0.8–0.9 | 0.85 | 0.76 |
| 0.9–1.0 | 0.97 | 0.95 |

- **"0.3 means 30 %"** holds within a few points in most bins; 0.7–0.9 is over-confident by about 10–16 points. The model was fitted on the two other sites, so this is calibration on unseen sites.
- **The per-day AUC of 0.73 is modest.** It counts every attacked day, including the first days of an attack before any evidence has built up, and the many small attacks (the "12 % of std" reading, wind) that are invisible in the data (docs/evaluation.md section 5.3). The probability is honest about those days: it stays low.
- **What the fusion learned** (coefficients similar on all three fits): the week- and month-long gaps carry the largest weights (`gap7` 1.05–1.67, `gap30` 1.51–2.07); an unusual day (`maha_log` 0.55–0.90) and a detector M alarm (`m_flag` 0.20–0.73) also raise the probability. The CUSUM ratio adds little once the gaps are known (−0.05 to 0.69). The trend feature gets a **negative** weight (−0.40 to −1.40): once the gaps are known, a high trend score mostly marks natural wandering, so the model discounts it.

### 6.2 Cost on honest stations (clean 2024)

| Site | De-weighted days | Quarantine days / year | Quarantines / year | Verification requests / year | Decision days changed by the defence |
|---|---|---|---|---|---|
| AZMET | 3.3 % | 0 | 0 | 1 | 0 % |
| FAWN | 0 % | 0 | 0 | 0 | 0 % |
| Kansas | 9.0 % | 29 | 1 | 2 | 1.1 % |

AZMET and FAWN are never quarantined. Kansas has one false quarantine of 29 days, caused by a long natural humidity gap in January. The quarantine level is the 0.5 % quantile of the clean trust of the two other sites, so it rests on about four days of clean data and moves with a single clean episode (AZMET 0.31, FAWN 0.40, Kansas 0.34). The defence itself changes an honest station's decision on at most 1.1 % of days.

### 6.3 Responses during the attack

| Attack | "12 %" of | De-weighted | Median days | Quarantined (+ alert) | Median days |
|---|---|---|---|---|---|
| 7-day replay | — | 81 % | 0 | **83 %** | **1** |
| 12 % step | range | 81 % | 8.5 | 68 % | 13 |
| 12 % step | value | 66 % | 14 | 51 % | 19 |
| 12 % step | std | 23 % | 31 | 12 % | 31 |
| drift to 15 % | range | 88 % | 34 | 75 % | 40.5 |
| drift to 15 % | value | 74 % | 37.5 | 57 % | 40.5 |
| drift to 15 % | std | 40 % | 50 | 15 % | 47 |

(Each cell counts episodes where the station reached that band during the attack while the clean run of the same site did not on those days.)

- A replay is quarantined the day after it starts.
- A 12 % step is quarantined within 2–3 weeks when it is large compared with the natural disagreement (value or range reading).
- A drift is quarantined after about 40 days, once it has grown.
- The "12 % of std" attacks mostly escape, as in the detection results.

**Per variable:** temperature and solar attacks are quarantined in 56–72 % of runs; humidity and wind in 19–40 %.

### 6.4 Decisions with and without the defence

Share of the decision window (attack + 30 days) where the decision level is wrong:

| Attack | "12 %" of | C0, no defence | C4, full system | Reduction |
|---|---|---|---|---|
| replay | — | 16.1 % | 14.0 % | −13 % |
| step | range | 10.5 % | 5.2 % | **−50 %** |
| step | value | 6.1 % | 4.5 % | −26 % |
| step | std | 2.4 % | 2.7 % | +14 % |
| drift | range | 11.0 % | 5.8 % | **−47 %** |
| drift | value | 7.3 % | 4.9 % | −33 % |
| drift | std | 2.5 % | 3.1 % | +23 % |
| **all** | | **7.1 %** | **4.9 %** | **−32 %** |

**The wrong decisions an attacker wants are the silent ones.** Without the defence, nothing warns the user, so every wrong decision is issued as if it were sound. 599 of the 756 attacks changed the decision on at least one day without defence. With the full system:

| Attack | Attacks that changed the decision (C0) | Still wrong at some point (C4) | Wrong **and issued as TRUSTED** (C4) |
|---|---|---|---|
| replay | 21 | 86 % | **5 %** (1 of 21) |
| step, range | 82 | 85 % | **28 %** |
| step, value | 76 | 87 % | 38 % |
| step, std | 65 | 98 % | 78 % |
| drift, range | 129 | 90 % | 43 % |
| drift, value | 127 | 89 % | 48 % |
| drift, std | 99 | 97 % | 73 % |

Reading:

1. **Most attacks still produce at least one wrong day.** A decision can flip in the first days of an attack, before the evidence is strong enough to act on (step latency 6–12 days, drift 30–40 days). Daily data and a 12 % change set that floor. No defence that avoids false alarms on honest stations can act on the first day.
2. **The defence cuts wrong-decision days by 32 % overall, and by 47–50 % for steps and drifts by range.** Quarantine replaces the implicated variable by the calibrated reference, so the decision comes back towards the truth.
3. **The bigger gain is that wrong decisions stop being silent.** One replay of 21 harmful ones produced a wrong decision issued as TRUSTED: a replay is detected on day 1, but a station whose trust was high can take a few days to fall below the de-weighting band. For 12 % steps by range, 72 % of the harmful attacks were either corrected or flagged DEGRADED (pending verification). Overall, 49 % of the harmful attacks (and 61 % outside the "of std" reading) never produced a silent wrong decision.
4. **For the smallest attacks ("12 % of std"), the defence slightly increases wrong days (2.5 → 2.9 % on average over steps and drifts).** These attacks are rarely detected (section 6.3), but they push the station a little closer to its thresholds. The resulting partial de-weighting, and substitution by a reference that is itself off by about 1 σ, can move a decision that was close to a level boundary. This is reported, not tuned away. Making de-weighting require a larger probability is the obvious next trial; it trades against latency on the large attacks.

### 6.5 Example: what the operator sees

AZMET, +12 % temperature step from 15 April to 13 June 2024 (`results/eval/trust/example_*.csv`):

| Date | Action | Trust | Reason given |
|---|---|---|---|
| 23 Mar | verification request | 0.58 | week-long gap against NASA POWER |
| 8 May | verification request | 0.54 | month-long gap against NASA POWER; temp_c up, step since about 12 Apr |
| 25 May | verification request | 0.48 | month-long gap against NASA POWER |
| 8 Jun | verification request | 0.36 | month-long gap against NASA POWER; temp_c up, step since about 8 May |
| 13 Jun | quarantine + alert | 0.31 | month-long gap against NASA POWER; temp_c up, step since about 8 May |
| 5 Jul | release | 0.59 | agrees with its context again |

The 23 March request comes before the attack: it is the site's one natural verification request of 2024. The attack itself is first dated to 12 April (3 days before the true onset), is de-weighted with three verification requests, and reaches quarantine on its last day. Every action carries a reason an operator can check.

### 6.6 Headline for the report

- The compromise probability is **calibrated on sites it never saw**: of days scored 0.3–0.4, 30 % are attacked; of days scored 0.9–1.0, 95 % are.
- The four responses fire in a graded way. A replay is quarantined the day after it starts; a 12 % step (value or range reading) within 2–3 weeks in 51–68 % of runs; a drift to 15 % after about 40 days in 57–75 %.
- AZMET and FAWN are never quarantined on clean 2024; Kansas has one 29-day false quarantine. The defence changes at most 1.1 % of an honest station's decision days.
- **With the defence, wrong-decision days fall by 32 % overall (up to 50 %), and only 1 of 36 replays produces a wrong decision issued as trusted.** The attacks below about 0.7 σ of the station-to-reference difference are not stopped, and the report says so.
