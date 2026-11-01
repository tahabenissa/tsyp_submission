"""Change-point dating: the CUSUM detector restricted to ``change_point.test_variables``.

Change-point dating is done by ``CusumDetector.episodes``: every alarm is dated
back to the day after the alarming sum was last at zero, which is the classic
CUSUM estimate of when the change happened.  This class only exists so the
dating can run on a different set of variables (``change_point.test_variables``)
while sharing the CUSUM settings (slack, threshold, AR order) from the
``cusum`` section.  It is not part of the daily OR in ``detect/statistical.py``
because its alarms are the CUSUM's alarms.
"""

from __future__ import annotations

from sensorguard.processing.detector_s.base import monitored_variables
from sensorguard.processing.detector_s.cusum import CusumDetector

__all__ = ["ChangePointDetector"]


class ChangePointDetector(CusumDetector):
    name = "change_point"

    def _variables(self, cfg: dict) -> list[str]:
        variables = list(monitored_variables(cfg))
        chosen = [v for v in cfg.get("change_point", {}).get("test_variables", variables) if v in variables]
        if not chosen:
            raise ValueError(f"No configured change-point test variables in {variables}")
        return chosen
