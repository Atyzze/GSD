from __future__ import annotations

import hashlib
import json

from graph_scale_dynamics.reporting import science_contract as C


def test_the_science_is_every_fingerprint_and_contract_the_readings_rest_on_and_one_hash_over_them(tmp_path):
    table = tmp_path / "calibration" / "probe_calibration.json"
    table.parent.mkdir()
    table.write_bytes(json.dumps({"cells": {"square|4096|1": {"d_s": 2.0}}, "analysis_version": "a",
                                  "estimator_fingerprint": "e", "written_utc": "2026-11-25T06:23:06Z"}).encode())
    found, raw = C.science(tmp_path)
    assert raw == table.read_bytes() and found["table"] == C.TABLE_IN_BUNDLE
    assert found["calibration_table_sha256"] == hashlib.sha256(raw).hexdigest()
    parts = {k: found[k] for k in ("analysis_version", "estimator_fingerprint", "starts_fingerprint", "score",
                                   "catalogue", "engine", "calibration_cells_sha256")}
    assert found["sha256"] == hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert found["score"] == "gsd-law-score-9" and found["catalogue"] == "gsd-catalogue-2"
    assert found["contract"] == "gsd-science-contract-2"
    table.write_bytes(json.dumps({"cells": {"square|4096|1": {"d_s": 2.0}}, "analysis_version": "a",
                                  "estimator_fingerprint": "e", "written_utc": "2026-11-25T06:41:57Z",
                                  "origin": {"adopted_utc": "2026-11-23T15:56:32Z"}}).encode())
    elsewhere, _raw = C.science(tmp_path)
    assert C.same(found, elsewhere) == {"same": True, "differ": []}, (
        "two folders that installed the same table at other times read the same science (174's and 175's bundles)")
    assert elsewhere["calibration_table_sha256"] != found["calibration_table_sha256"]
    table.write_bytes(json.dumps({"cells": {"square|4096|1": {"d_s": 2.01}}, "analysis_version": "a",
                                  "estimator_fingerprint": "e"}).encode())
    moved, _raw = C.science(tmp_path)
    assert C.same(found, moved) == {"same": False, "differ": ["calibration_cells_sha256"]}
    assert C.same(found, dict(found)) == {"same": True, "differ": []}


def test_a_folder_without_a_table_says_so():
    found, raw = C.science(__import__("pathlib").Path("/nonexistent-gsd-folder"))
    assert raw is None and found["calibration_cells_sha256"] is None and found["table"] is None
