"""CUSUM detector: a lasting offset in the residuals, caught by adding it up over days.

How it works, in order:

1. Whitening.  Each monitored residual is autocorrelated (today looks like
   yesterday).  An AR model fitted on the train years predicts each day from the
   day before; the prediction error, divided by its train standard deviation, is
   close to independent noise of variance 1.  CUSUM theory assumes exactly that.
2. Two-sided CUSUM, one pair of sums per variable.  ``up`` adds every positive
   error larger than the slack k, ``down`` every negative one.  Noise inside +/-k
   cancels out; a lasting offset larger than k keeps growing.
3. Alarm and restart.  When the largest sum (over variables and sides) crosses
   the threshold h, the day is an alarm and all sums restart at zero (Page's
   CUSUM).  An alarm is therefore an event, and a lasting attack produces
   repeated alarms.
4. Threshold.  ``cusum.threshold`` is either a number or ``auto``.  With
   ``auto``, h is the lowest value giving at most
   ``cusum.target_false_alarms_per_year`` alarms per year on the clean train
   years.  This ties h to the metric the brief asks for (false alarms per
   station per year) instead of a guess.
5. Episodes.  Each alarm gets an estimated onset: the day after the alarming
   sum was last at zero.  Alarms closer than ``cusum.merge_gap_days`` are one
   episode.  The episode is typed "drift" when a Mann-Kendall trend from onset
   to end is significant, otherwise "step".

Daily output: ``score`` is the CUSUM statistic, ``flag`` is 1 on alarm days.  A
day with any monitored variable missing gets score NaN and flag 0; the sums
hold their value across it (nan_policy "hold").
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from sensorguard.processing.detector_s import stats
from sensorguard.processing.detector_s.base import Detector, monitored_variables

__all__ = ["CusumDetector"]


class CusumDetector(Detector):
    name = "cusum"
    section = "cusum"

    # ------------------------------------------------------------------ helpers

    def _variables(self, cfg: dict) -> list[str]:
        return list(monitored_variables(cfg))

    @staticmethod
    def _whitened(frame: pd.DataFrame, params: dict) -> np.ndarray:
        cols = []
        for v, col in zip(params["variables"], params["columns"]):
            cols.append(stats.whiten(frame[col].astype(float), np.asarray(params["coef"][v], dtype=float),
                                     params["sigma"][v], params["order"][v]).to_numpy(dtype=float))
        return np.column_stack(cols)

    def _run(self, frame: pd.DataFrame, params: dict) -> dict[str, np.ndarray]:
        return stats.cusum_restart(self._whitened(frame, params), params["slack"], params["threshold"])

    # ------------------------------------------------------------------ contract

    def fit(self, train: pd.DataFrame, cfg: dict) -> dict:
        c = cfg.get(self.section, {})
        variables = self._variables(cfg)
        whitening = bool(c.get("ar_whitening", True))
        order = int(c.get("ar_order", 1)) if whitening else 0
        min_days = int(c.get("min_train_days_per_variable", 100))
        if str(c.get("nan_policy", "hold")) != "hold":
            raise ValueError(f"unsupported {self.section}.nan_policy: {c.get('nan_policy')!r}")
        params: dict = {
            "variables": variables,
            "columns": [cfg["residual_variables"][v] for v in variables],
            "order": {}, "coef": {}, "sigma": {},
            "slack": float(c.get("slack", 0.5)),
            "ar_whitening": whitening,
        }
        for v, col in zip(variables, params["columns"]):
            x = train[col].astype(float)
            if int(x.notna().sum()) < min_days:
                raise ValueError(f"{self.name} needs {min_days} train days for {v}, got {int(x.notna().sum())}")
            coef, sigma = stats.fit_ar(x, order)
            params["order"][v] = order
            params["coef"][v] = [float(a) for a in coef]
            params["sigma"][v] = float(sigma)
        threshold = c.get("threshold", "auto")
        if str(threshold).lower() == "auto":
            target = float(c.get("target_false_alarms_per_year", 1.0))
            h, reached = stats.calibrate_threshold(self._whitened(train, params), params["slack"], target)
            params.update(threshold=h, threshold_source="auto", train_alarms_per_year=reached)
        else:
            params.update(threshold=float(threshold), threshold_source="config")
        return params

    def score(self, test: pd.DataFrame, params: dict, cfg: dict) -> pd.DataFrame:
        r = self._run(test, params)
        any_nan = test[params["columns"]].isna().any(axis=1).to_numpy()
        return pd.DataFrame({"score": np.where(any_nan, np.nan, r["stat"]),
                             "flag": (r["alarm"] & ~any_nan).astype(int)}, index=test.index)

    def per_variable(self, test: pd.DataFrame, params: dict, cfg: dict) -> dict[str, pd.DataFrame]:
        r = self._run(test, params)
        out = {}
        for i, (v, col) in enumerate(zip(params["variables"], params["columns"])):
            st = np.maximum(r["up"][:, i], -r["down"][:, i])
            st = np.where(test[col].isna().to_numpy(), np.nan, st)
            out[v] = pd.DataFrame({"score": st, "flag": (st > params["threshold"]).astype(int)}, index=test.index)
        return out

    def episodes(self, test: pd.DataFrame, params: dict, cfg: dict) -> list[dict]:
        """Group alarms into episodes, each with an estimated onset date and a type.

        ``start`` is the estimated change date, ``first_alarm`` the first alarm
        day (detection latency is first_alarm minus the true onset), ``end``
        the last alarm of the episode.
        """
        c = cfg.get(self.section, {})
        gap = int(c.get("merge_gap_days", 14))
        alpha = float(cfg.get("change_point", {}).get("drift_alpha", 0.05))
        z_crit = float(norm.ppf(1.0 - alpha / 2.0))
        w = self._whitened(test, params)
        r = stats.cusum_restart(w, params["slack"], params["threshold"])
        any_nan = test[params["columns"]].isna().any(axis=1).to_numpy()
        alarms = np.flatnonzero(r["alarm"] & ~any_nan)
        groups: list[list[int]] = []
        for a in alarms:
            if groups and a - groups[-1][-1] <= gap:
                groups[-1].append(int(a))
            else:
                groups.append([int(a)])
        episodes = []
        for g in groups:
            first, last = g[0], g[-1]
            up, down = r["up"][first], r["down"][first]
            i = int(np.argmax(np.maximum(up, -down)))           # variable that raised the alarm
            side = r["up"][:, i] if up[i] >= -down[i] else -r["down"][:, i]
            prev_alarm = alarms[alarms < first]
            floor = int(prev_alarm[-1]) + 1 if prev_alarm.size else 0
            zero = np.flatnonzero(side[floor : first + 1] <= 0.0)
            onset = floor + int(zero[-1]) + 1 if zero.size else floor
            values = w[onset : last + 1, i]
            values = values[np.isfinite(values)]
            typ = "step"
            if values.size >= 3:
                _, _, z = stats.mann_kendall(values)
                typ = "drift" if abs(z) > z_crit else "step"
            episodes.append({
                "start": str(test.index[onset].date()),
                "first_alarm": str(test.index[first].date()),
                "end": str(test.index[last].date()),
                "alarms": len(g),
                "type": typ,
                "direction": "up" if up[i] >= -down[i] else "down",
                "variable": params["variables"][i],
                "max_score": float(r["stat"][first : last + 1].max()),
            })
        return episodes
