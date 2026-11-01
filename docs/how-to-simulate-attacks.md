# How to simulate attacks

All commands run in **PowerShell**, from `D:\tsyp`, on the branch `feat/official-attacks`.

On this PC GNU Make is called **`mingw32-make`**. To type `make` instead, run this once per PowerShell window:

```powershell
Set-Alias make mingw32-make
```

## Commands

| What you want | Command |
|---|---|
| See all commands | `mingw32-make` |
| See the data files and attacks | `mingw32-make list` |
| Run one attack on one data file | `mingw32-make attack DATA=semiarid ATTACK=step` |
| Run only some settings | `mingw32-make attack DATA=semiarid ATTACK=step ONLY=T2M,up,value` |
| See the setting names | `mingw32-make settings ATTACK=drift` |
| Run the 3 attacks on one data file | `mingw32-make attack-data DATA=semiarid` |
| Run everything on all data files | `mingw32-make attacks-all` |
| Draw the plot | `mingw32-make plot DATA=semiarid` |
| Delete all results | `mingw32-make clean` |
| Delete one data file's results | `mingw32-make clean DATA=semiarid` |
| Delete one attack | `mingw32-make clean DATA=semiarid ATTACK=step` |
| Run the tests | `mingw32-make test` |
| Download the 3 test sites (NASA POWER) | `mingw32-make data` |

- `ATTACK` = `step`, `drift` or `replay`
- `DATA` = a file name from `data\raw` without `.csv` (now: `semiarid`, `mediterranean`, `valley`)
- `ONLY` = tags that must all be in the setting name, separated by commas (e.g. `T2M,up` or `ramp90` or `back364`)

## Where the results go

```
results\attacks\<data>\<attack>\<setting>\
```

```
results\attacks\
└── semiarid\                          <- data
    ├── step\                          <- attack (126 settings)
    │   ├── episodes.csv               one line per setting: start, end, parameters
    │   └── T2M-up-value-seed0\        <- setting
    │       ├── attacked.csv           the fake data
    │       └── labels.csv             the answer key: which day is attacked, by how much
    ├── drift\                         378 settings
    ├── replay\                        9 settings
    └── plot.png                       after mingw32-make plot DATA=semiarid
```

Each time you run an attack, its old folder is deleted first. Only the last run is kept, so files never pile up.

## Setting names

| Name | Means |
|---|---|
| `T2M-up-value-seed0` | step on temperature, pushed **up**, 12 % of the **value**, seed 0 |
| `RH2M-down-std-seed2` | step on humidity, pushed **down**, 12 % of the **standard deviation**, seed 2 |
| `T2M-up-range-ramp90-seed1` | drift on temperature, up, 15 % of the **range**, reached in **90 days**, seed 1 |
| `back364-seed0` | replay of the week **364 days back** (same week last year), seed 0 |

The same seed always gives the same files.

## A typical session

```powershell
mingw32-make list                                    # what data do I have?
mingw32-make settings ATTACK=step ONLY=T2M           # which settings exist for T2M?
mingw32-make attack DATA=semiarid ATTACK=step ONLY=T2M,up,value
mingw32-make attack-data DATA=semiarid               # all 3 attacks
mingw32-make plot DATA=semiarid                      # look at results\attacks\semiarid\plot.png
mingw32-make clean                                   # done, delete everything
```

## If you make a mistake

```
mingw32-make attack ATTACK=step
*** give DATA=<name>, one of: mediterranean semiarid valley.  Stop.

mingw32-make attack DATA=semiarid ATTACK=jump
*** give ATTACK=<name>, one of: step drift replay.  Stop.

mingw32-make attack DATA=paris ATTACK=step
*** no file data/raw/paris.csv - available: mediterranean semiarid valley.  Stop.
```
