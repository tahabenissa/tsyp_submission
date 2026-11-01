# The architecture of our project, explained simply

> **Scope:** how our Track 2 system is built and why — the weather stations, the three checks, the trust score, the decision. It does not cover the schedule or the scoring; those are in `docs/`.
> **Prerequisites:** none for section 1. For section 2: what a digital signature is, and what "standard deviation" means.

---

## 1. The Simple Version

In a field there is a weather station [a small machine that measures temperature, humidity, wind, rain and sunshine]. Once a day it sends its numbers to an office. The office uses the numbers to decide things: how much water a crop needs, whether there is a drought, whether an insurance contract must pay a farmer.

The problem: the office believes whatever numbers arrive. If someone changes the numbers, the office makes the wrong decision. And the change does not need to be big. Make the station read 12 % too hot, or let it drift a little more every week, or send last week's dry days again during a rainy week — and a decision tips the other way. Nobody notices, because every number still looks like ordinary weather.

Our project is a guard that stands between the stations and the office. Before any number is used, the guard asks three questions:

1. **Did this number really come from that station, and has nobody touched it on the way?** Each station puts a secret stamp on its numbers. Change one digit and the stamp no longer matches.
2. **Does the number make sense for this station?** The minimum cannot be above the maximum. The sun cannot shine more strongly than a clear sky allows. The exact same week does not happen twice.
3. **Do independent witnesses agree?** The guard compares the station with NASA POWER [a NASA service that gives the weather for any place on Earth, day by day] and with Sentinel-2 [a European satellite that photographs the ground every few days]. A station that keeps disagreeing with both is lying or broken.

If a number fails question 1, it is thrown away. Questions 2 and 3 do not give a yes or a no: they move a **trust score** for the station, between 0 and 1. As the score falls, the guard first listens to the station less, then asks someone to check it, then stops listening and uses the witnesses instead.

What we actually build is a **computer program on a laptop**. There are no real stations and no real attacker. We take real recorded weather data from the internet, replay it as if it were arriving live, change some of it ourselves to play the attacker, and measure how often the guard catches us.

**The analogy:** Think of a shopkeeper whose scale reads 12 % heavy. No single sale looks wrong — 1.12 kg of apples is a perfectly normal amount of apples. An inspector who checks one sale sees nothing. But an inspector who brings a reference weight and compares it with the scale every day sees the same small gap, in the same direction, every time. One gap is chance. Twenty gaps in a row is a rigged scale. Our guard is that inspector, and NASA POWER is the reference weight.

**In one sentence:** We sign every station measurement, then compare it day after day with its own past, with physics, with NASA POWER and with Sentinel-2, so that a false measurement — even a small one — cannot quietly drive a decision.

---

## 2. The Professional Explanation

### 2.1 Definition

The system is a **defence-in-depth pipeline for in-situ sensor data**. It combines cryptographic provenance (origin, integrity and freshness of each reading) with residual-based anomaly detection (truthfulness of each reading), and a response policy graded by a per-station trust score.

The distinction that drives the whole design:

- **Integrity** — the reading was not changed after the station produced it. Cryptography guarantees this.
- **Truthfulness** — the reading reflects the real weather. Cryptography cannot guarantee this, because a compromised station signs false data with a valid key. Only comparison with independent evidence can.

### 2.2 How it actually works

The data moves through eight stages. Each exists for a reason.

| # | Stage | What it does | Why it is there |
|---|---|---|---|
| 1 | **Station** | Measures, puts the day's values in a record with a sequence number, a date and the hash of the previous record, and signs it with the station's own private key | Binds each reading to one device, one day and one position in the stream |
| 2 | **Telemetry** | Carries the record to the service over a mobile or low-power radio link | Untrusted: anyone on this path can read, change, replay or drop messages |
| 3 | **Provenance verifier (layer L1)** | Checks the signature, that the station is enrolled, that the sequence number is new, that the hash chain is unbroken, and that the station is still reporting on schedule | Stops forgery, modification and replay outright; turns a silent station into a visible event |
| 4 | **Quality control and alignment** | Standard range, spike and flat-line tests; lines the station's days up with the reference's days | Removes ordinary sensor faults and crude manipulation cheaply |
| 5 | **Calibration and residuals** | Learns the station's normal offset from the reference, then computes for each reading how far it is from what was expected according to five sources of expectation | Converts "is this value true?" into numbers that are near zero when the station is honest — on ordinary days and in heatwaves alike |
| 6 | **Detectors** | A statistical detector (interpretable tests that accumulate evidence over days) and a learned detector (a one-class model trained on clean data only) | Two views of the same evidence; the learned one is not trained on our own attacks, so it can catch attacks we did not think of |
| 7 | **Trust score and response** | Turns the detectors' output into a compromise probability per reading and a trust score per station; de-weights, requests verification, quarantines, alerts | Turns scores into graded actions with a readable reason |
| 8 | **Decision product** | Computes an indicator (a 30-day water balance) from trusted data, signs it, and attaches which readings and which reference data were used | The analyst, or an auditor later, can see what the decision was based on |

The five residuals of stage 5:

| Residual | Expectation comes from | Catches | Misses |
|---|---|---|---|
| Temporal | The season and the station's own recent days | Frozen values, spikes, sudden invented events | A 12 % step or a slow drift — both smaller than ordinary weather |
| Physical | The relationships between the station's own variables (sunshine has a ceiling; temperature range follows sunshine; humidity follows temperature and dew point) | One variable changed without the others | All variables changed together consistently |
| Reference | NASA POWER for the same place and day, corrected for the station's usual offset | A station that shifts away and stays away, or drifts away | An offset smaller than the reference's own error |
| Orbital context | Sentinel-2: cloud, snow, vegetation and moisture around the station | A station that contradicts what the satellite saw; helps decide whether the station or the reference is wrong | Anything during cloudy periods; small short-lived changes |
| Replay | The station's own archive, and the reference's day-to-day changes | Old days sent again | A careful replay of a very similar week with noise added |

Each residual has a blind spot, and the blind spots do not overlap. That is the argument for using all five.

Trust bands and responses:

| Trust | State | Response |
|---|---|---|
| High | Trusted | Data used at full weight |
| Reduced | De-weighted | The station counts for less; a verification request is raised |
| Low | Quarantined | Data excluded, replaced by the corrected reference; operator alerted |
| — | Silent | Stopped reporting; excluded; treated as unknown |

A record that fails L1 is rejected outright and never reaches the score. A decision that would change because of a station that is not trusted is held until it has been verified, and the product is marked DEGRADED.

### 2.3 Key terms

| Term | Meaning |
|---|---|
| In-situ sensor | An instrument that measures at the location itself, as opposed to a satellite measuring from orbit |
| Ground truth | The measurement taken as the reference for what is really happening |
| False-data injection | An attack that replaces true measurements with false ones while the system keeps running normally |
| Step bias | From one day onward, every value is off by the same proportion |
| Drift | The error grows slowly over time |
| Replay | Genuine old data sent again as if it were new |
| Trust anchor | The thing every other check ultimately relies on; here an offline root key that certifies each station's key |
| Digital signature | A value computed from a message and a private key; anyone with the matching public key can check that the message is unchanged and came from the key's owner |
| Sequence number | A counter that goes up by one with each record; an old record sent again has an old number |
| Hash chain | Each record contains a fingerprint of the previous one, so a missing or reordered record is detectable |
| Provenance | The record of where data came from and what was done to it |
| Residual | Reported value minus expected value, divided by how much they normally differ |
| Calibration | Learning the normal, harmless difference between a station and its reference, so that it is not mistaken for an attack |
| Running sum (CUSUM) | A total that adds up each day's small disagreement; honest noise cancels out, a persistent bias does not |
| Change point | The day on which the behaviour of a series changes |
| One-class model | A model that learns only what normal data looks like and flags anything unlike it |
| Trust score | A number between 0 and 1 saying how much a station's data should count |
| Quarantine | Temporarily excluding a sensor whose data cannot be trusted |
| Stealth budget | The largest change an attacker can make without any check firing |

### 2.4 Variants / types

**Where the attacker can stand**

| Position | Example | What stops it |
|---|---|---|
| At the station | Shading a sensor, covering the rain gauge, or altering the software so the station signs false values | Only the residual checks — the signature is valid |
| On the telemetry | Changing or replaying messages on the radio link | The signature and the sequence number |
| In the data pipeline | Editing values in a database | The signature, checked end to end, and the hash-chained log |

**The three official attacks**

| Attack | Size in the standard test | What catches it |
|---|---|---|
| Step bias | 12 % | The running sum and the change-point search on the reference residual |
| Gradual drift | Up to 15 % | The trend test and the change-point search on the reference residual |
| Replay | Seven samples (one week of daily data) | The sequence number in transit; at the station, the exact-repeat search and the loss of agreement with the reference's day-to-day weather |

**Two ways to run it**

| Mode | Input | When |
|---|---|---|
| Stream mode | Signed records, one per day | The full prototype, all three layers |
| File mode | A plain series plus coordinates | The jury's test: the false values are already inside the series, so only detection can help |

**Which detector**

| Detector | Strength | Weakness |
|---|---|---|
| Statistical | Explains its verdict and dates the start of the attack; needs no training on attacks; almost free to run | Each test is built for one kind of attack |
| Learned one-class | Picks up combinations of small deviations | Harder to explain; quality depends on how clean the training data is |

### 2.5 Trade-offs and limits

- **Good at:** attacks in transit and in the pipeline (prevented, not just detected); a persistent bias on temperature, humidity, solar radiation or pressure; replayed data.
- **Slow by nature:** data is daily, so detection takes days. A small bias needs a week or more of evidence.
- **Bad at:** a bias smaller than the reference's own error; daily rain and wind, which a grid cell tens of kilometres wide represents poorly.
- **Sentinel-2 is a weak witness for small changes:** one clear picture every few days at best, none under cloud, and it sees the effects of weather rather than weather itself. It is still the one witness nobody on the ground can tamper with.
- **Does not tell you:** whether a wrong reading is an attack or a worn-out sensor. A drifting humidity sensor and a drift attack look the same, and the response is the same.
- **Unknown site:** the final test is at a place we do not know in advance, so nothing may be tuned to one station.
- **Cost:** 118 extra bytes per record, and a dependency on two external data services (answers are cached locally).

---

## 3. Examples

### Example 1 - Basic: the stamp on a reading

This is check 1 on its own: a station signs a reading, and a changed reading no longer passes. It needs the `cryptography` package (`pip install cryptography`).

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.exceptions import InvalidSignature

# The station creates its key pair once. The private key never leaves the station.
station_private_key = Ed25519PrivateKey.generate()
station_public_key = station_private_key.public_key()   # registered with the service

# The station measures, then signs.
reading = b"station=17;seq=412;date=2026-07-14;tmax_c=41.8;rh_pct=22"
signature = station_private_key.sign(reading)
print("signature length in bytes:", len(signature))

# At the service: the genuine reading passes.
station_public_key.verify(signature, reading)
print("genuine reading  -> accepted")

# An attacker changes 41.8 to 36.8 on the way.
tampered = b"station=17;seq=412;date=2026-07-14;tmax_c=36.8;rh_pct=22"
try:
    station_public_key.verify(signature, tampered)
    print("tampered reading -> accepted")
except InvalidSignature:
    print("tampered reading -> rejected")
```

Output:

```
signature length in bytes: 64
genuine reading  -> accepted
tampered reading -> rejected
```

**What happens:**

1. The station makes two keys. The private one stays on the station; the public one is given to the service.
2. `sign` produces 64 bytes that depend on every byte of the reading and on the private key.
3. `verify` on the unchanged reading succeeds silently.
4. The attacker changes `41.8` to `36.8`. The attacker does not have the private key, so cannot produce a new matching signature. `verify` raises `InvalidSignature` and the reading is rejected.

The 64 bytes are the main part of the 118-byte overhead per record.

### Example 2 - Realistic: one heatwave, five messages

A heatwave is in progress. NASA POWER, corrected for this station's usual offset, says the maximum temperature today should be about 41.0 °C. Five different messages arrive claiming to be record number 412 from station 17. This script uses only the Python standard library.

```python
LAST_ACCEPTED_SEQ = 411       # the service remembers the last number it accepted
SPREAD_C = 1.5                # how much a healthy station normally differs from its reference
LIMIT = 3.0                   # more than 3 spreads away = suspicious on a single day


def check(name, seq, signature_ok, tmax_c, reference_c):
    # Check 1: is it really from the station, unchanged?
    if not signature_ok:
        return f"{name}: REJECT (signature does not match)"
    # Check 1 again: is it new, or an old record sent again?
    if seq <= LAST_ACCEPTED_SEQ:
        return f"{name}: REJECT (old record replayed, seq {seq})"
    # Check 3: does it agree with the independent reference?
    residual = (tmax_c - reference_c) / SPREAD_C
    if abs(residual) > LIMIT:
        return f"{name}: SUSPECT (expected {reference_c:.1f} C, got {tmax_c} C, residual {residual:.2f})"
    return f"{name}: ACCEPT (expected {reference_c:.1f} C, got {tmax_c} C, residual {residual:.2f})"


heatwave_reference = 41.0     # NASA POWER for this place and day, corrected for the station's usual offset

print(check("A genuine heatwave reading ", 412, True, 41.8, heatwave_reference))
print(check("B changed on the link      ", 412, False, 30.0, heatwave_reference))
print(check("C old record replayed      ", 405, True, 30.0, heatwave_reference))
print(check("D hacked station, big lie  ", 412, True, 30.0, heatwave_reference))
print(check("E hacked station, 12 % lie ", 412, True, 36.8, heatwave_reference))

# The trap: a detector that only knows "normal" for this station.
normal_tmax_c, normal_spread_c = 31.0, 3.0
naive_score = (41.8 - normal_tmax_c) / normal_spread_c
print(f"Naive detector on the genuine heatwave: score {naive_score:.1f} -> flags the real heatwave as an attack")
```

Output:

```
A genuine heatwave reading : ACCEPT (expected 41.0 C, got 41.8 C, residual 0.53)
B changed on the link      : REJECT (signature does not match)
C old record replayed      : REJECT (old record replayed, seq 405)
D hacked station, big lie  : SUSPECT (expected 41.0 C, got 30.0 C, residual -7.33)
E hacked station, 12 % lie : ACCEPT (expected 41.0 C, got 36.8 C, residual -2.80)
Naive detector on the genuine heatwave: score 3.6 -> flags the real heatwave as an attack
```

**What happens:**

- **A** is the true reading. Residual: $(41.8 - 41.0)/1.5 = 0.53$. Well inside the limit of 3. Accepted, even though 41.8 °C is an extreme value.
- **B** was changed on the radio link. The signature fails. Rejected before anyone looks at the value.
- **C** is a genuine, correctly signed record from last week (number 405) sent again. The signature is fine but the number is old. Rejected.
- **D** is a compromised station that signs 30.0 °C with a fresh number. Check 1 passes. Residual: $(30.0 - 41.0)/1.5 = -7.33$. Far outside the limit. Suspect.
- **E** is the same compromised station being careful: it lowers the true value by 12 %, to 36.8 °C. Residual: $(36.8 - 41.0)/1.5 = -2.80$. **Inside the limit. Accepted.** This is the official attack, and a single-day check does not see it. Example 3 shows what does.
- **The last line** is the opposite mistake. A detector that only knows this station's usual 31 °C scores the true heatwave at $(41.8 - 31.0)/3.0 = 3.6$ and throws away the truth.

| Reading | Unusual value? | Disagrees with the reference? | Naive detector | Single-day check against the reference |
|---|---|---|---|---|
| 41.8 °C in a real heatwave (true) | Yes | No | False alarm | Accept |
| 36.8 °C in a real heatwave (false, −12 %) | Hardly | A little | Borderline | **Accept — missed** |

So: B and C are stopped by the stamp, D is stopped by the witness, and E needs more than one day.

### Example 3 - Edge case or common trap: the lie that is too small to see in one day

The trap is to judge each day separately. A 12 % bias is about the size of the normal gap between a station and its reference, so every single day looks fine.

Here are 20 days of residuals (station minus reference, in units of the normal spread). Days 1–10 are honest. From day 11 the station reads 12 % too high; on an ordinary day of about 16 °C that is about 2 °C, or 1.3 spreads.

```python
# Station minus reference for 20 days, in units of the normal spread.
# Days 1-10 are honest. From day 11 a 12 % bias adds about +1.3 to every day.
residuals = [0.4, -0.7, 1.1, -0.2, 0.6, -1.3, 0.3, 0.9, -0.5, 0.1,
             1.5, 0.7, 2.1, 1.2, 1.8, 0.4, 1.7, 2.3, 1.0, 1.3]

SINGLE_DAY_LIMIT = 3.0   # the rule from example 2
SLACK = 0.5              # ignore deviations smaller than this
ALARM = 4.0              # raise the alarm when the running total passes this

total = 0.0
single_day_alarm = None
running_total_alarm = None
for day, r in enumerate(residuals, start=1):
    if single_day_alarm is None and abs(r) > SINGLE_DAY_LIMIT:
        single_day_alarm = day
    total = max(0.0, total + r - SLACK)      # the running total (CUSUM)
    if running_total_alarm is None and total > ALARM:
        running_total_alarm = day
    print(f"day {day:2d}  residual {r:+.1f}  running total {total:.1f}")

print("single-day rule fired on day:", single_day_alarm)
print("running total fired on day:  ", running_total_alarm)
```

Output:

```
day  1  residual +0.4  running total 0.0
day  2  residual -0.7  running total 0.0
day  3  residual +1.1  running total 0.6
day  4  residual -0.2  running total 0.0
day  5  residual +0.6  running total 0.1
day  6  residual -1.3  running total 0.0
day  7  residual +0.3  running total 0.0
day  8  residual +0.9  running total 0.4
day  9  residual -0.5  running total 0.0
day 10  residual +0.1  running total 0.0
day 11  residual +1.5  running total 1.0
day 12  residual +0.7  running total 1.2
day 13  residual +2.1  running total 2.8
day 14  residual +1.2  running total 3.5
day 15  residual +1.8  running total 4.8
day 16  residual +0.4  running total 4.7
day 17  residual +1.7  running total 5.9
day 18  residual +2.3  running total 7.7
day 19  residual +1.0  running total 8.2
day 20  residual +1.3  running total 9.0
single-day rule fired on day: None
running total fired on day:   15
```

**What happens:**

- The single-day rule never fires. The largest residual in the attacked period is 2.3, under the limit of 3.
- The running total stays near zero for the ten honest days: positive and negative days cancel, and the slack of 0.5 absorbs small noise.
- From day 11 every day pushes the same way. The total climbs — 1.0, 1.2, 2.8, 3.5, 4.8 — and passes the alarm level on **day 15, five days after the attack began**.

**Why:** honest noise has no preferred direction, so it adds up to nothing. A bias always points the same way, so it adds up without limit. The numbers here are made up to show the mechanism; measuring the real delay for each variable is one of the main results of the project.

The same idea handles the other two official attacks. A drift makes the running total rise slowly and then faster. A replay makes the station stop following the reference's daily ups and downs for exactly seven days.

---

## 4. Common Mistakes

| Mistake | Why it happens | Correct approach |
|---|---|---|
| "If we sign the data, we are done" | Signatures feel like complete protection | A signature proves who sent it and that it was not changed. It does not prove it is true. A hacked station signs lies perfectly |
| Flagging extreme values | Anomaly detection is usually taught as "find the outliers" | Detect disagreement with independent sources, not extremes |
| Judging each day on its own | It is the simplest rule to write | The official attacks are too small for that. Add up the evidence over days |
| Treating the station–reference gap as an error | They "should" be equal | A point and a grid cell always differ. Learn the normal gap first, then look for a change in it |
| Tuning everything on one station | It is the data we have | The final test is at a hidden site. Test on places the system has never seen |
| Training the detector on our own attacks | It gives excellent scores quickly | The jury tests with an attack we have not seen. Train on clean data only |
| Expecting Sentinel-2 to reveal a 12 % bias | It is the "satellite" in the challenge title | It is a slow, sparse witness. Use it as an independent arbiter and say what it adds |
| Calling a detected reading "an attack" | We built it to find attacks | The system knows the reading is wrong, not why. Worn-out sensors look the same |
| Claiming the defence is perfect | It sounds stronger | Small enough changes get through. Measure how small, and say so |

---

## 5. Summary

**The core idea:** A decision is only as trustworthy as the measurements behind it. We make each station sign its measurements so nobody can change them on the way, and we compare each station day after day with independent witnesses — NASA POWER and Sentinel-2 — so a station that lies, even slightly, loses trust and stops counting.

**Cheat sheet:**

| Question | Answer |
|---|---|
| What is it? | A guard between field weather stations and the decisions taken on their data |
| Why does it exist? | Because false measurements produce wrong decisions, silently |
| What are the three checks? | Is it from the station and unchanged? Does it make sense on its own? Do independent witnesses agree? |
| What stops an attacker on the link? | The signature and the sequence number |
| What stops a hacked station? | The comparison with NASA POWER and Sentinel-2, accumulated over days |
| What are the official attacks? | A 12 % step bias, a drift up to 15 %, a seven-sample replay |
| What does the system output? | A compromise probability per reading and a trust score per station |
| What do we actually build? | A Python program that replays real weather data, injects attacks, and measures detection |
| Biggest gotcha? | The attacks are small. No single day shows them; the running total does |

**Test yourself:**

1. An attacker changes a temperature on the radio link. Which check stops it, and why can the attacker not fix the signature?
2. A station's software is hacked and it signs every value 12 % too high. Why does check 1 pass, and why does a single-day comparison with the reference also pass?
3. A station honestly reports 42 °C in a real heatwave. Why does our system accept it when a simple outlier detector would reject it?
4. Why does a running total catch a small bias when a daily limit does not?
5. Name one attack this system cannot catch, and explain why.

<details>
<summary>Answers</summary>

1. The signature check. The signature depends on every byte of the reading and on the station's private key, which never leaves the station. Without that key the attacker cannot produce a signature that matches the changed reading.
2. Check 1 passes because the hacked station uses its real key, so the signature is valid and the sequence number is fresh. The single-day comparison passes because 12 % is about as large as the normal difference between a station and a grid-cell reference, so one day's residual stays under the limit.
3. Because we do not ask whether the value is unusual; we ask whether it disagrees with the other evidence. In a real heatwave NASA POWER shows the heat too, so the residual is small.
4. Honest differences go both ways and cancel out when added up. A bias always goes the same way, so the total keeps growing until it passes the alarm level.
5. A bias smaller than the reference's own error — for example a few per cent on wind speed. Every residual stays inside its normal range for as long as anyone watches, so nothing fires. Also acceptable: a replay of a past week chosen to match the current weather closely, with a little noise added.

</details>

**Go deeper:**

- `docs/02-architecture.md` — the full design, record format, verification steps and trust score.
- `docs/03-threat-model.md` — the eleven injection attacks and nine evasion strategies.
- `docs/04-signal-processing-and-detection.md` — calibration, each residual, and the detectors.
- `docs/05-evaluation-plan.md` — how the three official attacks are run and measured.
- CUSUM change detection and change-point search (the `ruptures` library) — the two statistical tools behind the detection of steps and drifts.
