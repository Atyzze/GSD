from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

BATCH_ONE = ("0016efb0e1a38474c41eeeb828b945adc0f1acefedb94b92ed536756df8c57d2",
             "0045ca45e6d1729c3dc3c4d4ff264959ea90c586840804e38147e1197935f5f2",
             "b4d17dcdb34a44a3781df721b5388b64b89d78b6df1e95b2c8aabde8f51a4423")
CONTROL = "6f364db7b709f3a9ec8de91a7304b2d8c977c492eb166122f6a3fa2957773320"
NOWHERE = "f" * 64


def _bundle(tmp_path: Path, rows: list[dict], sha: str) -> Path:
    bundle = tmp_path / "study_174_bundle"
    (bundle / "tables").mkdir(parents=True)
    study = {"study_id": "174", "campaigns": [
        {"campaign_id": "1", "study_design": {"campaign": 0, "design_sha256": sha, "kind": "blind", "study": "174"}},
        {"campaign_id": "11", "study_design": None}]}
    (bundle / "study.json").write_text(json.dumps(study))
    with gzip.open(bundle / "tables" / "laws.ndjson.gz", "wt") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    return bundle


def test_study_174_s_laws_are_drawn_again_from_its_seeds_and_its_controls_from_their_criterion(tmp_path):
    import importlib

    from graph_scale_dynamics.dsl import dsl
    from graph_scale_dynamics.operations import study_design as SD
    tool = importlib.import_module("tools.laws_of_a_bundle")
    sha = SD.design_for(ROOT, "174")["sha256"]
    rows = [{"campaign_id": "1", "candidate_id": law} for law in BATCH_ONE]
    rows += [{"campaign_id": "11", "candidate_id": CONTROL}, {"campaign_id": "1", "candidate_id": NOWHERE}]
    found = tool.read(_bundle(tmp_path, rows, sha), ROOT)
    assert found["laws"] == 5 and found["missing"] == 1 and found["campaigns"]["1"]["missing"] == [NOWHERE]
    assert set(found["specs"]) == {*BATCH_ONE, CONTROL}
    assert all(dsl.fingerprint(spec) == law for law, spec in found["specs"].items()), "each law is its own id"
    ring = found["specs"]["b4d17dcdb34a44a3781df721b5388b64b89d78b6df1e95b2c8aabde8f51a4423"]
    assert sorted(t["op"] for t in ring["terms"]) == ["degree_cube_sum", "edge_count", "wedge_count"]
    assert ring["dynamics"]["zero_temperature"] is True, "C1-G6940, the ring from empty, as the Top 100 shows it"
    carried = rows[:1] + [{"campaign_id": "1", "candidate_id": NOWHERE,
                           "spec": {"terms": [], "note": "a law the bundle carries is taken as carried"}}]
    again = tool.read(_bundle(tmp_path / "again", carried, sha), ROOT)
    assert again["missing"] == 0 and again["carried"] == 1


def test_a_bundle_of_another_design_is_refused(tmp_path):
    import importlib
    tool = importlib.import_module("tools.laws_of_a_bundle")
    with pytest.raises(SystemExit, match="not the one its bundle ran"):
        tool.read(_bundle(tmp_path, [{"campaign_id": "1", "candidate_id": BATCH_ONE[0]}], "0" * 64), ROOT)
