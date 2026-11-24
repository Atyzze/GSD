from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _tool():
    spec = importlib.util.spec_from_file_location("top_laws_alike", ROOT / "tools" / "top_laws_alike.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _law(ops, zero=False):
    return {"terms": [[op, None, c0, "one", None] for op, c0 in ops], "beta": 2.0, "zero_temperature": zero,
            "locality": 0.5, "swap_share": 0.2, "local_move": "toggle", "regime": "equilibrium", "sweeps": 30}


def _score(points, by="lattice", chain="bcc", d=3.0):
    return {"score": 10 if points else 0, "items": {"d_s": points, "d_V": 1, "d_B": 0, "d_w": 0, "einstein": 0},
            "by": by, "chain": chain, "d": d, "to_n": 65536}


def _bundle(tmp_path, laws):
    folder = tmp_path / "study_x" / "campaign_1_reports_x"
    folder.mkdir(parents=True)
    rows = [{"candidate_id": law, "spec": spec, "kind": "sees cycles", "mean_degree": {"4096": 6.0}}
            for law, spec, _score, _top in laws]
    chains = {law: {"score": score, "top_n": top} for law, _spec, score, top in laws}
    (folder / "28-decision-engine.json").write_text(json.dumps({"campaign_id": "1", "body": {
        "law_ledger": {"rows": rows}, "every_chain": {"laws": chains}, "laws": []}}), encoding="utf-8")
    return folder.parent


def test_a_term_twice_as_common_among_the_top_laws_reads_twice_and_a_frozen_or_read_only_law_is_not_top(tmp_path):
    T = _tool()
    root = _bundle(tmp_path, [
        ("a" * 64, _law([("square_edge_overlap", -0.1), ("degree_cube_sum", 0.08)]), _score(2), 65536),
        ("b" * 64, _law([("square_edge_overlap", -0.2)]), _score(3, chain="cubic"), 65536),
        ("c" * 64, _law([("edge_count", 0.1)]), _score(1), 65536),
        ("d" * 64, _law([("edge_count", 0.3), ("degree_cube_sum", 0.1)]), _score(2, by="frozen"), 16384),
        ("e" * 64, _law([("triangle_count", 1.0)], zero=True), _score(0), 1024),
    ])
    found = T.read(root, rescore=False)
    assert found["top"] == 2 and found["population"] == 4 and found["laws"] == 5
    by_term = {row["term"]: row for row in found["enrichment"]}
    assert by_term["square_edge_overlap"]["top"] == 2 and by_term["square_edge_overlap"]["population"] == 2
    assert by_term["square_edge_overlap"]["ratio"] == 2.0 and by_term["square_edge_overlap"]["top_negative"] == 2
    assert by_term["edge_count"]["top"] == 0 and by_term["edge_count"]["ratio"] == 0.0
    sets = {row["terms"]: row for row in found["term_sets"]}
    assert sets["square_edge_overlap"]["chains"] == {"cubic": 1}
    assert sets["degree_cube_sum + square_edge_overlap"]["d"] == [3.0]
    assert found["by_dimension"][0]["d"] == "about 3" and found["by_dimension"][0]["laws"] == 2
    page = T.render(found)
    assert "| square_edge_overlap | 2 | 1.0 | 2 | 0.5 | 2.0 | 0 / 2 |" in page
    assert "—" not in page and "–" not in page
