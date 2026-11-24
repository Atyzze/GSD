from __future__ import annotations

from pathlib import Path

from graph_scale_dynamics.research.classification_report import place
from graph_scale_dynamics.research.measured_anchors import measured_anchors
from tests.support.explorer_study import calibration_table, write_study

ROOT = Path(__file__).resolve().parents[2]


def test_a_law_is_placed_at_every_rung_it_read_two_probes_and_judged_at_its_top():
    anchors = measured_anchors(calibration_table())
    square = {"d_s": 1.97, "d_V": 1.98, "d_B": 1.96, "d_w": 2.07}
    placed = place([(1024, square, 4.0), (256, {"d_s": 1.9, "d_V": 1.91}, 4.0), (64, {"d_s": 1.4}, 4.0),
                    (4096, {"d_s": 2.6, "d_V": None}, 4.0)], anchors=anchors)
    assert set(placed["by_n"]) == {256, 1024}, "a rung with one probe read has no family to be compared with"
    family, distance = placed["by_n"][1024]
    assert family == "periodic_square_lattice" and distance <= 1.0, "within the square lattice's own seed spread"
    assert (placed["n"], placed["placed_n"], placed["nearest"]) == (4096, 1024, "periodic_square_lattice"), (
        "judged at its top rung read, placed at the top rung two probes read")
    assert set(placed) == {"by_n", "n", "placed_n", "nearest", "distance"}, "no verdict since 646"
    assert place([(64, {}, 3.0)], anchors=anchors) is None
    theory = place([(1024, square, 4.0)], anchors=None)
    assert theory["by_n"][1024][0] and theory["by_n"][1024][1] is not None, "without a table, against theory's bands"


def test_the_explorer_carries_each_rung_s_distance_and_each_law_s_placement(tmp_path):
    import json

    from graph_scale_dynamics.reporting import study_explorer as E
    study = write_study(tmp_path, laws=12, ledger_only=3)
    record = json.loads((study / "study.json").read_text())["campaigns"][0]
    part = E.read_part(study / record["bundle"], record, calibration=calibration_table())
    keys = [key for key, *_ in E.ROW_FIELDS]
    at = keys.index("family_distance")
    placed = [values[at] for index, values, _p in part["rows"] if index < 12]
    assert placed and all(v is not None for v in placed), "every rung of report 05's laws reads two probes or more"
    assert all(values[at] is None for index, values, _p in part["rows"] if index >= 12), "the ledger's laws are not"
    law = part["laws"][0]
    assert law["nearest"] in ("square", "cubic") and law["nearest_distance"] is not None and "verdict" not in law
    assert part["basis"] == "measured"
    data = E.document([{"campaign": record, "part": part}], title="t", study={})
    assert data["classify_basis"] == "measured" and "family_distance" in [f["key"] for f in data["row_fields"]]
    assert "nearest" in {f["key"] for f in data["law_fields"]}
    plain = E.read_part(study / record["bundle"], record, place=False)
    assert all(values[at] is None for _i, values, _p in plain["rows"]) and plain["laws"][0]["nearest"] is None
