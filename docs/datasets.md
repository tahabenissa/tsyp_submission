# Datasets (report part D6)

Each site has two daily series for the same days: a **station series** (the
sensor we test) and a **reference series** (NASA POWER, the independent
witness). Both follow the shared format of `src/sensorguard/schema.py`.

Period for all development sites: 2023-01-01 to 2024-12-31 (731 days).
Access date: 2026-10-18.

## Sites

| Site | Role | Network | Climate | Station | Latitude | Longitude |
|---|---|---|---|---|---|---|
| `site_a` | development | AZMET (Arizona) | dry | TO DECIDE WITH TEAM (id or neutral) | 32.480 | -109.930 |
| `site_b` | development | FAWN (Florida) | humid | TO DECIDE WITH TEAM | 28.68165 | 81.88565 |
| `site_c` | development | Kansas Mesonet | continental | TO DECIDE WITH TEAM | 39.20857 | -96.59169 |

Held-out sites (never used to build or tune, Q6): not chosen yet.

## Station series

| Site | Original resolution | Original units | Conversion to shared format | Wind sensor height |
|---|---|---|---|---|
| `site_a` | daily | degC, %, m/s, mm, MJ/m2 | none (values already in shared units) | 9.8 ft (3.0 m)  (AZMET variables page) |
| `site_b` | every 15 minutes | degC, %, mph, inch, W/m2 | daily mean (temperature, humidity, wind, solar), daily sum (rain), mph to m/s, inch to mm, W/m2 x 0.0864 = MJ/m2/day, wind from 10 m to 2 m (FAO-56) | about 10 m, TO VERIFY (FAWN technical page) |
| `site_c` | daily | degC, %, m/s, mm, W/m2 | rain = larger of two gauges, W/m2 x 0.0864 = MJ/m2/day | 2 m |

A day with fewer than 90 % of its 15-minute readings gets NaN (site_b).
Missing values are always NaN, never 0.

## Reference series

| Source | Product | Variables | Notes |
|---|---|---|---|
| NASA POWER | Daily API, point, community AG | T2M, RH2M, WS2M, PRECTOTCORR, ALLSKY_SFC_SW_DWN | Grid model, so a constant gap with the stations is normal. Solar unit checked: MJ/m2/day. |
| Sentinel-2 L2A | via Copernicus Data Space | cloud, vegetation, moisture | Not done yet (F15). |

## Licence and citation

| Source | Rule | Checked |
|---|---|---|
| AZMET | free, asks users to cite the network and the access date | yes, on the AZMET API page |
| FAWN | data free to the public | yes, on the FAWN site; TO FILL exact citation wording |
| Kansas Mesonet | the `ksmesopy` package is MIT licensed; TO FILL data policy from mesonet.k-state.edu | no |
| NASA POWER | TO FILL (check the POWER data policy) | no |

## Files and how to get them

| Site | Local file (not for the report) | How to get it | SHA-256 |
|---|---|---|---|
| `site_a` | `data/raw/stations/azmet_*.csv` | automatic, `fetch_azmet_daily` | in `data/raw/stations/manifest.json` |
| `site_b` | `data/raw/fawn/2023.csv`, `2024.csv` | by hand from the FAWN "FTP: Yearly CSV Data" page |  E998F0408453F3E8956A92528977DE620CC9FBEB7F9A3EC1F5... 
C73A9A771A26B77ACBDA01C6F64F882EB65F622CA89CC448AA...  (`Get-FileHash <file>`) |
| `site_c` | `data/raw/stations/kansas_*.csv` | automatic, `fetch_kansas_daily` | in `data/raw/stations/manifest.json` |
| all | `data/raw/power/power_*.json` | automatic, `fetch_power_daily` | in `data/raw/power/manifest.json` |

## Known limits

- Rain agrees least with NASA POWER (point against grid average), at every site.
- One station per site, so the gaps are not valid for a whole climate.
- FAWN daily values depend on the time zone of the file (to verify).