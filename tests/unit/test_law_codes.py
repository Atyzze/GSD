from __future__ import annotations

import copy
import json
from pathlib import Path

from graph_scale_dynamics.research.hamiltonian_preflight import dynamics_signature, equilibrium_identity

ROOT = Path(__file__).resolve().parents[2]


def test_cooling_joins_the_signature_only_where_a_law_has_it():
    standing = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "readings" / "controls_criterion_2.json").read_text())["laws"]
    cooled = [{"label": law["label"], "spec": dict(law["spec"], dynamics=dict(
        law["spec"]["dynamics"], cooling={"from_beta": law["spec"]["dynamics"]["beta"] / 4, "over_sweeps": 600}))}
        for law in standing]
    for plain, cool in zip(standing, cooled, strict=True):
        signature = dynamics_signature(plain["spec"])
        assert signature is None or "cooling" not in signature
        assert dynamics_signature(cool["spec"])["cooling"] == cool["spec"]["dynamics"]["cooling"]
        assert equilibrium_identity(plain["spec"])[0] != equilibrium_identity(cool["spec"])[0], plain["label"]


def test_the_standing_controls_keep_the_function_hash_they_had():
    before = {"P1": "78be0f36215807cdbf2344d9"}
    law = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "readings" / "controls_criterion_2.json").read_text())["laws"][0]
    assert law["label"] == "P1" and equilibrium_identity(copy.deepcopy(law["spec"]))[0] == before["P1"]
