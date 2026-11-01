# Tools

Small programs for looking at the system by hand. They are not part of the pipeline; everything they show can be reproduced with the scripts in `scripts/`.

| File | What it does | Run |
|---|---|---|
| **`sensorguard_gui.py`** | **The control room.** *Assess data*: load any station file (CSV or Excel; columns recognised automatically, NASA POWER names included), give the coordinates, run the whole defence and see every stage. *Simulate attack*: choose a site, an attack and the attacker position, see layer 1 and the detectors react. *Experiments*: run the tests and the full evaluations, read their tables. *Configs & docs*: every setting and document | **`mingw32-make gui`** |
| `pipeline_gui.py` | Runs the whole chain on one site: data, attack, layer 1, residuals, a quick screen; saves a run to `results/pipeline_runs/` | `mingw32-make pipeline-gui` |
| `l1_gui.py` | Layer-1 control panel: send signed records and watch forged, modified, replayed, dropped and silent records get caught | `mingw32-make l1-gui` |
| `prep_view.py` | Window that shows the preparation figures (calibration, residuals); opened from `l1_gui.py` | — |
| `plot_attacks.py` | Plots one example of each official attack | `mingw32-make plot DATA=semiarid` |
| `fetch_power.py` | Downloads NASA POWER daily data for the 3 demo sites into `data/raw/*.csv` | `mingw32-make data` |
| `attacks.png` | Example output of `plot_attacks.py` | — |

`mingw32-make help` lists every shortcut (GNU Make is called `mingw32-make` on Windows).
