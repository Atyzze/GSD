from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))



def test_a_rung_is_certified_by_its_seeds_certificates_and_nothing_else():
    from graph_scale_dynamics.scaleflow.equilibration import rung_certified

    def seed(reason, failures=()):
        return {"health": {"rung_terminal": {"reason": reason, "classification": reason.upper(),
                                             "failures": [{"code": "X", "detail": d} for d in failures]}}}

    assert rung_certified([]) == {"certified": None, "failures": []}
    assert rung_certified([{"health": {}}])["certified"] is None
    assert rung_certified([seed("completed"), seed("completed")])["certified"] is True
    failed = rung_certified([seed("completed"), seed("ceiling", ["the chains disagree in structure"])])
    assert failed["certified"] is False and "disagree in structure" in failed["failures"][0]
