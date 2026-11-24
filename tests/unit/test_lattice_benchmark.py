from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.benchmark_campaign import DEFAULT_SPEC, benchmark_spec, lattice_laws, lattice_spec
from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.scheduling.campaign import validate_campaign


def _base():
    return json.loads(DEFAULT_SPEC.read_text())


def test_every_lattice_law_is_a_valid_hand_written_hamiltonian():
    laws = lattice_laws()
    assert len(laws) >= 40
    spec = lattice_spec(_base())
    for law in laws:
        problems = dsl.validate(law["spec"], complexity_budget=spec["complexity_budget"],
                                operator_whitelist=spec["operator_whitelist"])
        assert not problems, (law["label"], problems)
        assert law["spec"]["init"] == "empty"
        assert all(t["coeff"]["scale"] == "one" for t in law["spec"]["terms"]), law["label"]
    labels = [law["label"] for law in laws]
    assert len(set(labels)) * 2 == len(labels) or len(set(labels)) == len(labels)
    assert any("overlap=1.0" in l and "square: a=2 b=1" in l for l in labels)
    assert any("no overlap penalty" in l for l in labels)
    assert any(l.startswith("control: anchor d=4") for l in labels)


def test_the_engine_benchmark_spec_still_validates():
    assert validate_campaign(benchmark_spec(_base())) == []
