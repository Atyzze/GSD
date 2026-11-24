from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = _load("disordered_reading")


def _chain(d: float, reach, degree: float = 6.0, *, probes=None, piece: float = 1.0, sizes=(1024, 4096, 16384)):
    rows = []
    for n in sizes:
        read = probes or {"d_s": d, "d_V": d + 0.1, "d_B": d - 0.1}
        rows.append({"n": n, **read, "d_w": 2.5, "reach": reach(n), "mean_degree": degree, "giant_fraction": piece})
    return rows


def test_a_geometry_is_counted_and_held_and_a_random_graph_is_not():
    space = R.chain_reading(_chain(3.0, lambda n: 1.2 * n ** (1 / 3)), R.RULE_2)
    assert space["counted_at"] == [4096, 16384] and space["held"]
    assert not space["sizes"]["4096"]["d_w"] == 2.0, "the walk dimension is not asked"
    wiring = R.chain_reading(_chain(5.0, lambda n: math.log(n) / math.log(5.0)), R.RULE_2)
    assert wiring["counted_at"] == [] and wiring["sizes"]["16384"]["why"].startswith("reach")


def test_a_dense_random_graph_at_reach_four_to_five_needs_the_second_rule():
    rows = _chain(5.0, {1024: 3.0, 4096: 4.0, 16384: 5.0}.get, degree=9.0,
                  probes={"d_s": 4.6, "d_V": 5.6, "d_B": None})
    assert R.chain_reading(rows, R.RULE)["counted_at"] == [4096, 16384]
    second = R.chain_reading(rows, R.RULE_2)
    assert second["counted_at"] == [] and second["sizes"]["16384"]["why"] == "reaches no further than a random wiring"


def test_a_tree_and_a_graph_in_pieces_are_not_counted():
    tree = R.chain_reading(_chain(1.3, lambda n: n ** 0.5, degree=2.0, probes={"d_s": 1.27, "d_V": 1.9,
                                                                                "d_B": 1.55}), R.RULE_2)
    assert tree["counted_at"] == [] and tree["sizes"]["4096"]["why"] == "under two dimensions"
    pieces = R.chain_reading(_chain(3.0, lambda n: 1.2 * n ** (1 / 3), piece=0.9), R.RULE_2)
    assert pieces["sizes"]["4096"]["why"] == "in pieces"


def test_report_28_s_rows_read_as_the_rule_reads_them():
    from graph_scale_dynamics.reporting.every_chain_report import VALUE_COLUMNS
    rows = _chain(3.0, lambda n: 1.2 * n ** (1 / 3))
    values = [[row.get(key) for key in VALUE_COLUMNS] for row in rows]
    assert R.chain_reading(R.rows_of(values), R.RULE_2) == R.chain_reading(rows, R.RULE_2)


def test_a_bundle_is_decoded_with_the_columns_it_recorded(tmp_path, monkeypatch):
    from graph_scale_dynamics.reporting.every_chain_report import VALUE_COLUMNS
    recorded = list(reversed(VALUE_COLUMNS))
    row = {key: None for key in VALUE_COLUMNS}
    row.update(n=4096, d_s=2.01, d_V=2.0, d_B=2.0, d_w=2.0, reach=40.0, mean_degree=4.0, giant_fraction=1.0)
    part = tmp_path / "campaign_1_reports_x"
    part.mkdir()
    report = {"body": {"every_chain": {"value_columns": recorded,
                                       "laws": {"law": {"values": {"empty": [[row[k] for k in recorded]]}}}}}}
    (part / "28-decision-engine.json").write_text(json.dumps(report))
    seen = []
    monkeypatch.setattr(R, "chain_reading", lambda rows, rule: seen.append(rows) or {})
    monkeypatch.setattr(R, "_count", lambda *a, **k: None)
    assert R.read_bundle(tmp_path)["campaigns"]["1"]["chains_read"] == 1
    assert seen == [[row]], "decoded by the bundle's columns, not the package's"


def test_a_study_s_controls_are_not_pooled_with_its_laws(tmp_path, monkeypatch):
    from graph_scale_dynamics.reporting.every_chain_report import VALUE_COLUMNS
    row = [4096] + [None] * (len(VALUE_COLUMNS) - 1)
    for campaign in ("1", "2"):
        part = tmp_path / f"campaign_{campaign}_reports_x"
        part.mkdir()
        (part / "28-decision-engine.json").write_text(json.dumps({"body": {"every_chain": {
            "value_columns": list(VALUE_COLUMNS), "laws": {f"law-{campaign}": {"values": {"empty": [row]}}}}}}))
    (tmp_path / "study.json").write_text(json.dumps({"campaigns": [
        {"campaign_id": "1", "study_design": {"study": "172"}}, {"campaign_id": "2", "name": "campaign-standing-controls"}]}))
    monkeypatch.setattr(R, "chain_reading", lambda rows, rule: {})
    monkeypatch.setattr(R, "_count", lambda *a, **k: None)
    found = R.read_bundle(tmp_path)
    assert list(found["campaigns"]) == ["1"] and found["left_out"] == ["2"]
    assert "Left out, not the study's laws" in R.render(dict(found, rule_name="2"))
    (tmp_path / "study.json").unlink()
    assert sorted(R.read_bundle(tmp_path)["campaigns"]) == ["1", "2"], "a bundle with no study reads every campaign"
