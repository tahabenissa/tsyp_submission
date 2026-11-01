"""Train the deployment fusion model and trust bands on all three development sites, and save them.

    python scripts/train_fusion.py

The evaluation (scripts/run_trust.py) fits the fusion leave-one-site-out, to
measure it honestly.  For scoring NEW data (the GUI, scripts/assess.py) the
model is fitted once on every run of all three sites and frozen.

Two variants are saved, because detector M only exists for the three sites it
was trained on:

    with_m   all seven features (development sites)
    s_only   detector S features only (any other station, e.g. the jury's)

Output: results/models_fusion/fusion.joblib (a few kilobytes).
"""

from __future__ import annotations

import json
import time
import warnings

import joblib
import pandas as pd

from sensorguard import pipeline as pl
from sensorguard.detect import fusion, trust_score
from sensorguard.eval.runner import load_eval_config, scenarios
from sensorguard.eval.trust_eval import _stack, collect_site, load_trust_config

OUT = pl.REPO_ROOT / "results" / "models_fusion"
S_ONLY = [f for f in fusion.FEATURES if not f.startswith("m_")]


def main() -> int:
    warnings.filterwarnings("ignore")
    t0 = time.perf_counter()
    tcfg, ecfg, prep_cfg = load_trust_config(), load_eval_config(), pl.load_config()
    grid = scenarios(ecfg)
    collected = [collect_site(s, grid, ecfg, prep_cfg, tcfg) for s in pl.sites(prep_cfg)]
    x, y = _stack(collected)
    tc = tcfg["trust"]
    saved = {"meta": {"sites": [c["site"] for c in collected], "runs": len(grid) * len(collected),
                      "days": int(len(y)), "attacked_share": float(y.mean())}}
    for name, features in (("with_m", fusion.FEATURES), ("s_only", S_ONLY)):
        model = fusion.fit(x, y, c=float(tcfg["fusion"]["regularization_c"]), feature_names=list(features))
        clean_trust = pd.concat([trust_score.trust_series(model.probability(c["clean_x"]), tc["fall_rate"], tc["recovery_rate"])
                                 for c in collected])
        bands = trust_score.fit_bands(clean_trust, tc["deweight_clean_share"], tc["quarantine_clean_share"])
        saved[name] = {"model": model, "bands": bands}
        saved["meta"][name] = {"coefficients": model.coefficients(), "bands": bands.as_dict()}
    OUT.mkdir(parents=True, exist_ok=True)
    joblib.dump(saved, OUT / "fusion.joblib")
    (OUT / "fusion.json").write_text(json.dumps(saved["meta"], indent=2), encoding="utf-8")
    print(json.dumps(saved["meta"], indent=2))
    print(f"saved to {OUT} in {(time.perf_counter() - t0) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
