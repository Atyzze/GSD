from __future__ import annotations

from graph_scale_dynamics.services.calibration_core import run_probe_ladders


def _families_the_owed_seed_predates() -> set:
    import json

    from graph_scale_dynamics.calibration import owed
    from graph_scale_dynamics.calibration.cells import suite_families
    if owed.recalibration_owed() is None:
        return set()
    seeded = {cell["family"] for cell in json.loads(owed.SEED.read_text(encoding="utf-8"))["cells"].values()}
    return {family["name"] for family in suite_families()} - seeded


def test_every_calibration_family_is_within_declared_tolerance():
    study = run_probe_ladders(seeds=2, max_nodes=5000, verbose=False)
    failures = {
        name: family["gated_failures"]
        for name, family in study["families"].items()
        if family["verdict"] != "PASS"
    }
    assert study["verdict"] == "PASS", (
        "calibration ladder gate FAILED; an estimator has drifted outside its "
        f"declared tolerance or lost a refusal: {failures}"
    )
    refusal = study["families"]["random_4_regular"]
    assert refusal["false_confidence_readings"] == 0, (
        "a probe read a dimension on a graph that has none: "
        f"{refusal['gated_failures']}"
    )
    predates = _families_the_owed_seed_predates()
    for name, family in study["families"].items():
        if family["expectation"] != "MEASURE" or name in predates:
            continue
        gated = [v for row in family["rows"] for v in row["channels"].values()
                 if v["status"] in ("WITHIN_TOLERANCE", "OUT_OF_TOLERANCE", "REFUSED")]
        assert gated, f"{name} has no gated cells; the gate is not exercising it"
    for name, family in study["families"].items():
        if family["expectation"] != "REFUSE":
            continue
        held = [v for row in family["rows"] if row["n"] >= 4096 for v in row["channels"].values()]
        assert held or name == "balanced_binary_tree", "a binary tree has 4,095 nodes and then 8,191"
        assert {v["status"] for v in held} <= {"REFUSED_OK"}, (
            f"{name} is held from 4,096 nodes, the size a verdict is relied on, and every probe refuses it there")
