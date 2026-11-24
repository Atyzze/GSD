from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.research import control_verdict as CV

NAME = "controls_of_two_campaigns.json"
CONTRACT = "gsd-controls-criterion-of-two-campaigns"
P1_TO_N = 16384


def of_two_campaigns() -> dict:
    two = CV.load_criterion(CV.READINGS / "controls_criterion_2.json")
    laws = [dict(law, expect=dict(law["expect"], given_probes=dict(law["expect"]["given_probes"], to_n=P1_TO_N)))
            if law["label"] == "P1" else law for law in two["laws"]]
    shared = {key: value for key, value in two.items() if key not in ("contract", "campaign", "rungs", "seeds", "laws")}
    return dict(shared, contract=CONTRACT, campaigns={
        "campaign-standing-controls": {"rungs": two["rungs"], "seeds": two["seeds"], "laws": laws},
        "campaign-cooling-controls": {"rungs": two["rungs"], "seeds": two["seeds"], "laws": two["laws"][:2]}})


def written(folder: Path) -> Path:
    path = Path(folder) / NAME
    path.write_text(json.dumps(of_two_campaigns(), indent=1), encoding="utf-8")
    return path
