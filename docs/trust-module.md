# The trust module (layer 1)

> Branch: `feat/official-attacks` · date: Tuesday 21 October 2026
> Companion to [official-attacks.md](official-attacks.md) (the three attacks). This is the **next** deliverable from section 9: the trust module.

---

## 1. In 30 seconds

The attacks make fake data. The **trust module** is the first wall that catches the fakes that happen **in transit or in the pipeline** — before any signal analysis runs.

It answers one question for every record that arrives: **did this reading really come from the station it claims, in order, unchanged, and not replayed?**

It does this with cryptography, not statistics, so it is exact: a record either carries a valid signature or it does not.

| What it stops | How |
|---|---|
| **Forgery** (someone makes up a reading) | every record is signed by the station's private key |
| **Modification** (someone changes a value in transit) | the signature covers every field; one flipped bit fails it |
| **Replay** (someone resends an old real record) | a counter that must strictly increase |
| **Suppression** (someone deletes records) | a hash chain: each record names the one before it, so a hole shows |
| **Silence** (a station stops reporting) | a watchdog that marks a station silent instead of assuming a quiet day |

What it is **blind to**: a station that is itself hacked or physically fooled. That data is validly signed, so it passes L1. Catching **that** is Member 2 and Member 4's job (L2 history/physics, L3 compare with NASA POWER and Sentinel-2). L1 is the first of three layers, not the whole defence.

---

## 2. Where I started and where I ended

Before: the five files in `src/sensorguard/trust/` were one-line stubs (just a docstring each). Nothing worked.

After: all five are implemented, there are **30 tests (all pass)**, and the full project test suite is **57 passed** (my 27 attack tests still green). No internet needed, runs in ~0.2 s.

```
src/sensorguard/trust/
├── record.py      the signed record format (encode / decode)      158 lines
├── keys.py        the keys and the "secure element" boundary      105 lines
├── enrolment.py   certificates, the station registry, revocation  129 lines
├── verify.py      the verifier, replay state, the watchdog         135 lines
├── ledger.py      the tamper-evident log                            71 lines
└── __init__.py    what the rest of the project imports              71 lines
tests/test_trust.py                                                 321 lines
```

---

## 3. Each file, in plain words

### 3.1 `record.py` — the signed record

A record is one station reading, packed into a fixed byte layout so anyone can read it without asking us for a schema first.

| Field | Size | What it is |
|---|---|---|
| `version` | 1 B | format number, in case we change it later |
| `type` | 1 B | reading / status / heartbeat |
| `sensor_id` | 4 B | which station |
| `key_id` | 2 B | which of the station's keys (so a key can be rotated) |
| `seq` | 4 B | a counter that must go **up** every record — this is what kills replay |
| `t_obs` | 8 B | when the station observed the reading (unix seconds) |
| `prev_hash` | 32 B | the SHA-256 of the **previous** record — this is the chain |
| `payload_len` | 2 B | how long the payload is |
| `payload` | varies | the day's values (fixed-point) + a status byte |
| `signature` | 64 B | the Ed25519 signature over **everything above** |

**The fixed cost is exactly 118 bytes** (everything except the payload). I measured it, it is in a test, and the architecture doc promised that number — so the "overhead per record" claim in the report is now real, not a guess.

The signature covers the header **and** the payload, so changing any single field — the value, the date, the station id, anything — makes the signature fail. `decode()` refuses bytes that are too short or whose length does not match `payload_len`, so a malformed record is rejected cleanly instead of crashing.

The payload codec is a small one: a status byte, then each value stored as an integer (value × 1000, so three decimals). The order of the variables is agreed once (in the certificate / schema), not repeated in every record, to keep records small.

### 3.2 `keys.py` — keys, and the "secure element" wall

Three levels of keys, exactly like the architecture:

- a **root key**, offline, held by the operator. It signs **only certificates**, nothing else.
- one **station key** per device. The private part is generated on the device and **never leaves it**.
- (a service key for signing products — same idea, used later.)

The important design point: a real station keeps its private key in a hardware chip that will only ever do two things for you — *sign this* and *tell me your public key*. You can never read the private key out. I modelled that wall with a class called `SecureElement` that exposes **only** `sign()` and `public_key()`. The prototype version keeps the key in a file (`FileSecureElement`), but the rest of the code can only sign and read the public key. If we ever get real hardware, we implement the same two methods and nothing else changes. (A test checks the object really does not expose the private key.)

### 3.3 `enrolment.py` — certificates and revocation

A **certificate** is the root key's signed statement: *"this public key belongs to station 7, at this position, valid between these two dates."*

Position is **inside** the signed certificate on purpose. We look up the NASA POWER reference and the satellite context **by position**. If a station could lie about where it is, we would check it against the wrong witnesses. So the position is nailed down at enrolment.

The **registry** is the operator's list of enrolled stations. `enrol()` refuses any certificate the root did not actually sign. `revoke()` marks a station as compromised: it stays in the list (so its past is still on record) but from then on it is treated as unknown and its readings are rejected.

### 3.4 `verify.py` — the actual decision (the heart of it)

For each arriving record, in this exact order:

| Step | Check | If it fails |
|---|---|---|
| 1 | can we parse the bytes? | REJECT — malformed |
| 2 | is the station known, not revoked, and its certificate valid on that date? | REJECT — unknown station |
| 3 | is the signature valid for that station's key? | REJECT — forged / modified |
| 4 | is `seq` higher than the last one we accepted? | REJECT — replay |
| 5 | is the date sane vs. when it arrived? | REJECT if from the future (stale); FLAG if just late (delayed) |
| 6 | does `prev_hash` match the last record we accepted? | ACCEPT, but raise a **gap** (records are missing) |
| 7 | remember this `seq` and hash | ACCEPT |

The only thing we remember per station is **two values**: the last sequence number and the last hash. That is all it takes to stop replay and detect gaps. Cheap and simple.

The **cadence watchdog** (`silent_stations`): stations are supposed to report once a day. If one goes quiet past the expected interval plus a margin, it is listed as **silent**. Silence is reported, never read as "an uneventful day" — because an attacker who wants to hide something might just cut the station off.

### 3.5 `ledger.py` — the tamper-evident log

Once records are accepted, they (and the decisions and products) are appended to a **hash-chained log**. Each entry carries the hash of the previous one. If anyone later goes back and edits or deletes an old entry — an attacker *inside* the pipeline, after verification — the chain breaks and `verify()` returns False. Tests prove both an altered entry and a removed entry are caught.

---

## 4. How to check it yourself

PowerShell, from `D:\tsyp`, on branch `feat/official-attacks`:

```powershell
mingw32-make trust-test                                    # -> 30 passed
.venv\Scripts\python -m pytest -q                          # -> 57 passed (whole project)
```

### See the pipeline catch an attack (the quickest way to understand L1)

```powershell
mingw32-make l1                     # send records: honest ones accepted, then every attack caught
mingw32-make l1 ATTACK=replay       # just one: forged | modified | replay | dropped | silent
```

`mingw32-make l1` sets up a real root key, a real station key and the verifier,
sends 3 honest signed records (all ACCEPTED), then runs each attack and prints
the verdict:

```
honest stream (3 daily records, each signed by the station):
  2023-07-01 -> ACCEPT ok                seq 0
  2023-07-02 -> ACCEPT ok                seq 1
  2023-07-03 -> ACCEPT ok                seq 2

now the attacks L1 must catch:
  [forged]   -> REJECT forged            impostor's signature does not match the enrolled key
  [modified] -> REJECT forged            one changed byte breaks the signature
  [replay]   -> REJECT replay            seq 0 <= last accepted seq
  [dropped]  -> ACCEPT gap   GAP RAISED  prev_hash mismatch: a record is missing
  [silent]   -> SILENT watchdog          no valid record for 3 days -> station reported silent
```

The demo lives in `src/sensorguard/trust/demo.py`. It is a transcript for us and
the jury, not part of the product and not a test.

### Or click it: the control panel

```powershell
mingw32-make l1-gui                 # opens a window
```

A Tkinter window (no install needed) that drives the **real** trust module —
real Ed25519 keys, the real verifier, nothing faked for the screen. It is a
**live link monitor**: a station sends one signed record per "day" on a timer.

- **▶ Start / ⏸ Pause** and a **day every N s** speed box — watch records flow and
  get ACCEPTED (green), one per tick, seq and date advancing live.
- **Intercept** checkbox — tick it and the next record is **HELD on the link**
  (you are now the attacker sitting on the telemetry link). Its fields appear:
  `sensor_id, key_id, seq, t_obs, prev_hash, payload, signature`.
- While a record is held you can **edit any field**, then:
  - **Forward →** — deliver it. Edit a value but don't re-sign → REJECT *forged*.
  - **Re-sign (station)** then Forward → ACCEPT. **Re-sign (impostor)** → REJECT *forged*.
  - Set an old `seq` and Forward → REJECT *replay*.
  - **Drop ✖** — don't deliver it; the station moved on, so the next record raises a **GAP**.
- **Revoke station** — its records REJECT afterwards. **Reset** — fresh keys and chain.
- The **certificate box** shows the enrolled identity (id, position, validity, root
  signature "verifies: YES"); the status bar shows last accepted seq and chain head.

It lives in `tools/l1_gui.py`.

### Or drive it yourself in Python

Start `.venv\Scripts\python` and paste:

```python
from sensorguard import trust
from sensorguard.trust import record as rec

# operator makes a root key and a registry
root = trust.generate_root()
registry = trust.Registry(root.public_key())

# a station makes its own key; the root enrols it at a position
station = trust.FileSecureElement.generate()
cert = trust.issue_certificate(root, sensor_id=1, public_key=station.public_key(),
                               position=(35.68, 10.10), valid_from=0, valid_to=2**40)
registry.enrol(cert)

# the station signs a reading
r = trust.sign_record(station, rec.Record(
    sensor_id=1, key_id=0, seq=0, t_obs=1_700_000_000,
    prev_hash=rec.ZERO_HASH, payload=rec.encode_payload([20.1, 55.0, 18.3])))

# the verifier accepts it...
v = trust.Verifier(registry)
print(v.verify(r.encode(), arrival_time=1_700_000_000).reason)   # ok

# ...but rejects it if a single byte is changed
raw = bytearray(r.encode()); raw[60] ^= 0xFF
print(v.verify(bytes(raw), arrival_time=1_700_000_000).reason)   # forged
```

---

## 5. What I did NOT touch, on purpose

- **`schema.py`** is still the empty stub. Team rule: changing it needs all four of us. The record and certificate formats here are ready to lift into it once we agree the format.
- The **sensor emulator** (`sensor/station.py`) and the **transport emulator** (`transport/link.py`) are still stubs — that is my 20–26 Oct work. The trust module is ready to plug into them: the station signs, the transport loses/delays/duplicates, the verifier catches it.

---

## 6. What I need from the team now

- **Member 4:** confirm the verdict shape is enough for your metrics. Each verdict gives `decision` (accept/flag/reject), `reason`, and a `gap` flag. L1 rejections and the gap/silent signals are detections you can score for latency too.
- **Member 1:** the real `sensor_id` ↔ position mapping will come from `scenarios/sites.yaml`; the certificate takes the position from there.
- **Everyone:** still waiting on the format agreement (see README section 7) before anything goes into `schema.py`.

---

## 7. What comes next for me

| When | What |
|---|---|
| Now | First draft of the **threat-model** section of the report (`docs/03-threat-model.md`) |
| 20–26 Oct | Station + transport emulation, attacks at the three positions (station / link / pipeline), evasion attacks, overhead measurement (the 118 bytes is already measured), blind rehearsal 1 |
