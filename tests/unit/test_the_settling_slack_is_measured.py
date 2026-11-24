from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.calibration import finite_size as F

ROOT = Path(__file__).resolve().parents[2]
SEED = json.loads((ROOT / "calibration" / "seed_table.json").read_text(encoding="utf-8"))
RUNGS = (64, 256, 1024, 4096, 16384, 65536, 262144, 1048576)


def test_the_committed_fits_are_the_table_s_they_name_and_frozen_with_the_rule():
    assert set(F.committed()["families"]) == set(F.FAMILIES)
    assert F.committed() == F.measure(SEED), "fitted on the seed: python3 tools/finite_size_tolerance.py --write"
    assert F.committed()["source"]["estimator_fingerprint"] == SEED["estimator_fingerprint"]


def _errors_of_the_means() -> dict:
    import math
    values: dict = {}
    for cell in SEED["cells"].values():
        channel = cell["channels"].get("d_s") or {}
        if cell["family"] in F.FAMILIES and channel.get("valid"):
            values.setdefault(cell["family"], {}).setdefault(cell["n"], []).append(channel["value"])
    out = {}
    for family, rungs in values.items():
        for n, v in rungs.items():
            mean = sum(v) / len(v)
            spread = math.sqrt(sum((x - mean) ** 2 for x in v) / max(1, len(v) - 1))
            out[(family, n)] = spread / math.sqrt(len(v))
    return out


def test_every_known_geometry_s_own_flow_is_settled_at_every_step_of_its_ladder():
    errors = _errors_of_the_means()
    for family, points in F._means(SEED).items():
        points = F.in_the_flow(points)
        for (n_a, d_a), (n_b, d_b) in zip(points, points[1:], strict=False):
            ok, why = F.settled(d_a, errors[(family, n_a)], n_a, d_b, errors[(family, n_b)], n_b)
            assert ok, (family, n_a, n_b, why)


def test_a_small_world_s_climb_is_not_settled():
    ok, why = F.settled(6.0, 0.05, 4096, 7.0, 0.05, 16384)
    assert not ok and why["finite_size"] < 0.2


def test_the_slack_shrinks_with_size_and_is_traceable():
    from graph_scale_dynamics.decisions.engine import Policy
    decided_from = max(Policy().base_sizes)
    assert decided_from == 4096, "the base block runs to 4,096 nodes whatever d_s does: the first step judged ends there"
    read = [n for n in RUNGS if n >= decided_from // 4]
    steps = [F.tolerance(a, b) for a, b in zip(read, read[1:], strict=False)]
    assert all(later <= earlier + 1e-9 for earlier, later in zip(steps, steps[1:], strict=False)), steps
    assert 0.05 < steps[-1] < steps[0] < 0.35
    slowest = F.committed()["families"]["periodic_hypercubic_lattice_4d"]
    assert slowest["n_min"] > 1024 and F.tolerance(256, 1024) < steps[0], (
        "under the size d_s first reads the 4D lattice at, that lattice adds no drift: the step to 1,024 is the cubic's")
    assert F.committed()["source"]["estimator_fingerprint"] == SEED["estimator_fingerprint"]
