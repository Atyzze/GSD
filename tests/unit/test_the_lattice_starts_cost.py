from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import lattice_cost as LC  # noqa: E402

LAW, OTHER = "a" * 64, "b" * 64


def _chain(law, n, seed, chain, work, accepted, seconds=1.0, campaign="1", **extra):
    return {"campaign_id": campaign, "candidate_id": law, "n": n, "seed": seed, "chain": chain, "ran": True,
            "evidence": "compact", "work_units": work, "moves": 1000, "accepted_moves": accepted, "seconds": seconds,
            **extra}


def _bundle(tmp_path: Path, rows: list) -> Path:
    root = tmp_path / "study_x"
    (root / "tables").mkdir(parents=True)
    (root / "study.json").write_text(json.dumps({"study_id": "173", "campaigns": [
        {"campaign_id": "1", "study_design": {"study": "173"}}, {"campaign_id": "2"}]}))
    with gzip.open(root / "tables" / "chains.ndjson.gz", "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return root


def test_the_lattices_share_of_the_work_above_4096_and_the_frozen_chains(tmp_path, monkeypatch):
    rows = []
    for seed in range(3):
        rows += [_chain(LAW, 1024, seed, "empty", 100, 50), _chain(LAW, 1024, seed, "cubic", 100, 0),
                 _chain(LAW, 4096, seed, "empty", 100, 40), _chain(LAW, 4096, seed, "given", 100, 30, seconds=2.0),
                 _chain(LAW, 4096, seed, "cubic", 300, 0, seconds=3.0),
                 _chain(LAW, 4096, seed, "bcc", 500, 0 if seed < 2 else 7, seconds=5.0),
                 _chain(OTHER, 16384, seed, "square", 1000, 12, seconds=10.0)]
    rows.append(_chain(LAW, 4096, 0, "fcc", 10 ** 9, 0, campaign="2"))
    rows.append({"campaign_id": "1", "candidate_id": OTHER, "n": 4096, "chain": None, "ran": None, "evidence": "lost"})
    monkeypatch.setattr(LC, "scoring", lambda root: [
        {"law": LAW, "score": 7, "by": "lattice", "chain": "bcc", "to_n": 16384, "twins_points": 0.0},
        {"law": OTHER, "score": 3, "by": "kept", "chain": "square", "to_n": 16384, "twins_points": 2.0}])
    found = LC.read(_bundle(tmp_path, rows))
    assert found["chains_read"] == found["chains_with_work"] == 21, "the controls and a lost run are not read"
    at = found["sizes"]["4096"]
    assert at["groups"]["twins"]["work_units"] == 600 and at["groups"]["lattices"]["work_units"] == 2400
    assert at["lattice_share_of_work"] == 0.8 and at["by_start"]["cubic"]["unmoved"] == 3
    assert at["lattice_chains_frozen"] == {"cubic": 1}, "bcc moved on one seed of three, so it is not frozen there"
    assert found["sizes"]["1024"]["lattice_chains_frozen"] == {"cubic": 1}
    above = found["above"]
    assert above["lattice_share_of_work"] == round(5400 / 6000, 4)
    assert above["lattice_share_of_seconds"] == round((9 + 15 + 30) / (3 + 6 + 9 + 15 + 30), 4)
    law, other = found["scoring"]
    assert law["lattice_share_of_its_work"] == 0.8 and law["only_a_lattice_reads"]
    assert other["lattice_share_of_its_work"] == 1.0 and not other["only_a_lattice_reads"]
    text = LC.render(found)
    assert "the six lattice starts took 90% of the work" in text and "| 4,096 | 600 | 2,400 | 80% | cubic 1 |" in text


def test_a_bundle_made_before_841_says_it_has_no_work_to_read(tmp_path, monkeypatch):
    old = [{k: v for k, v in _chain(LAW, 4096, 0, "cubic", 1, 0).items()
            if k not in ("work_units", "moves", "accepted_moves", "seconds")}]
    monkeypatch.setattr(LC, "scoring", lambda root: [])
    found = LC.read(_bundle(tmp_path, old))
    assert found["chains_read"] == 1 and found["chains_with_work"] == 0
    assert "carries no chain's work (it was made before 841)" in LC.render(found)
