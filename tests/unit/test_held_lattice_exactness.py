from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import held_lattice_exactness as X  # noqa: E402

COLUMNS = ["n", "d_s", "d_V", "d_B", "d_w", "reach", "mean_degree", "giant_fraction", "triangles_per_node",
           "squares_per_node", "kappa"]


def _row(n, degree, squares, triangles=0.0):
    return [n, None, None, None, None, None, degree, 1.0, triangles, squares, None]


def test_the_bands_read_degree_squares_and_triangles_together():
    assert X.band("tesseract", 8.0, 6.0) == "within 0.1%"
    assert X.band("tesseract", 8.03, 6.0) == "within 1%", "a degree 0.4% off"
    assert X.band("cubic", 6.0, 3.12) == "within 5%", "squares 4% off"
    assert X.band("honeycomb", 3.0, 0.3, 0.5) == "further", "rewired at its degree: squares and triangles it never had"
    assert X.band("cubic", 6.0, 3.0, 0.02) == "within 5%", "a triangle in fifty nodes, which no exact lattice has"
    assert set(X.exact()) >= {"square", "triangular", "cubic", "bcc", "fcc", "tesseract"}, "every lattice start's own"
    assert X.exact()["fcc"] == (12.0, 33.0, 8.0) and X.exact()["triangular"] == (6.0, 3.0, 2.0)
    assert X.band("fcc", 12.0, 33.0, 8.0) == "within 0.1%" and X.band("triangular", 6.0, 3.0, 2.08) == "within 5%"


def _bundle(tmp_path, laws: dict, *, arm_laws: dict | None = None) -> Path:
    campaigns = []
    for cid, chains, arm in (("1", laws, None), ("6", arm_laws or {}, "natural units")):
        part = tmp_path / f"campaign_{cid}_reports_x"
        part.mkdir()
        body = {"every_chain": {"value_columns": COLUMNS, "laws": chains}}
        (part / "28-decision-engine.json").write_text(json.dumps({"body": body}))
        campaigns.append({"campaign_id": cid, "law_budget": 10000, "bundle": part.name,
                          **({"study_design": {"arm": arm}} if arm else {})})
    (tmp_path / "study.json").write_text(json.dumps({"campaigns": campaigns}))
    return tmp_path


def _law(at_n, fates, values, *, cls="holds", score=None):
    return {"starts_reading": {"class": cls, "at_n": at_n, "fates": {k: [v, 1.0] for k, v in fates.items()}},
            "values": values, "score": score or {"score": 0}, "top_n": at_n}


def test_a_bundle_s_held_lattices_and_scored_laws_are_banded(tmp_path):
    laws = {
        "a" * 64: _law(65536, {"cubic": "holds", "tesseract": "holds", "honeycomb": "melted"},
                       {"cubic": [_row(65536, 6.0, 3.0)], "tesseract": [_row(65536, 8.02, 6.05)],
                        "honeycomb": [_row(65536, 3.0, 0.3, 0.5)]},
                       score={"score": 17, "chain": "tesseract", "to_n": 1048576}),
        "b" * 64: _law(4096, {"honeycomb": "holds"}, {"honeycomb": [_row(4096, 3.0, 0.31, 0.5)]}, cls="selects"),
        "c" * 64: _law(1024, {"cubic": "holds"}, {"cubic": [_row(1024, 6.0, 3.4)]}),
        "d" * 64: _law(4096, {"cubic": "unmoved"}, {"cubic": [_row(4096, 6.0, 3.0)]}, cls="forgets"),
    }
    arm = {"e" * 64: _law(4096, {"cubic": "holds"}, {"cubic": [_row(4096, 6.0, 3.0)]})}
    found = X.read(_bundle(tmp_path, laws, arm_laws=arm))
    held = found["held"]
    assert held["lattices"] == 3, "the shape laws' held lattices from 4,096; not below it, not a forgetting law's, not the arm's"
    assert held["by_lattice"]["cubic"]["within 0.1%"] == 1 and held["by_lattice"]["tesseract"]["within 1%"] == 1
    assert held["by_lattice"]["honeycomb"]["further"] == 1 and held["by_band"]["within 0.1%"] == 1
    assert held["laws_by_band"]["further"] == ["bbbbbbbbbbbb:honeycomb"]
    assert found["scored"] == {"laws": 1, "by_band": {"within 0.1%": 0, "within 1%": 1, "within 5%": 0, "further": 0}}, (
        "a scored law read at the largest size at or below the one it scored to")
