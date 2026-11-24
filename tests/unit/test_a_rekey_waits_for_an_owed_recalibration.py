from __future__ import annotations

from graph_scale_dynamics.calibration import owed as OWED
from graph_scale_dynamics.calibration import rekey as R


def test_a_rekey_is_refused_while_a_recalibration_is_owed(monkeypatch):
    monkeypatch.setattr(OWED, "recalibration_owed", lambda: {"build": 691})
    report = R.rekey(root="/nonexistent", var="/nonexistent", apply=True, justification="x", log=lambda *_: None)
    assert report["status"] == "REFUSED_RECALIBRATION_OWED" and report["sampled"] == report["restamped"] == 0
    early = R.rekey(root="/nonexistent", var="/nonexistent", apply=True, log=lambda *_: None)
    assert early["status"] == "REFUSED_NO_JUSTIFICATION", "an argument's refusal still comes first"
