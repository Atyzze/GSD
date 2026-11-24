from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import bundle_growth as G  # noqa: E402


def _bundle(root: Path, laws: int, decision_bytes: int) -> Path:
    folder = root / "study_9_2026-11-21T00-00-00Z"
    (folder / "tables").mkdir(parents=True)
    with gzip.open(folder / "tables" / "laws.ndjson.gz", "wt") as out:
        for index in range(laws):
            out.write(json.dumps({"candidate_id": f"law-{index}"}) + "\n")
    with gzip.open(folder / "tables" / "decisions.ndjson.gz", "wt") as out:
        for index in range(2 * laws):
            out.write(json.dumps({"decision_id": index, "facts_json": "x" * decision_bytes}) + "\n")
    (folder / "study.json").write_text(json.dumps({"study_id": "9", "build_number": 838, "built_utc": "t",
                                                   "read_utc": {"tables": "u", "reading": "words"}}))
    part = folder / "campaign_1_reports_x"
    (part / "evidence").mkdir(parents=True)
    (part / "manifest.json").write_text(json.dumps({"cycle_seconds": 12.5}))
    controller = {"pass_seconds": 0.02, "passes_total": 10, "passes_idle": 4, "rest_seconds": 8.0}
    (part / "evidence" / "system.json").write_text(json.dumps({"services": [
        {"role": "api", "last_message": "{}"}, {"role": "controller", "last_message": json.dumps(controller)}]}))
    return folder


def test_the_tables_parts_and_controller_are_read_from_the_bundle(tmp_path):
    found = G.sizes(_bundle(tmp_path, 10, 100))
    assert found["laws"] == 10 and found["study_id"] == "9" and found["read_utc"] == {"tables": "u"}
    decisions = found["tables"]["decisions.ndjson.gz"]
    assert decisions["rows"] == 20 and decisions["raw_bytes"] > 20 * 100 > decisions["bytes"]
    part = found["parts"]["campaign_1_reports_x"]
    assert part["cycle_seconds"] == 12.5 and part["controller"]["pass_seconds"] == 0.02


def test_one_bundle_scales_in_proportion_and_two_fit_a_line():
    found = {"laws": 100, "bytes": 1000, "tables": {"decisions.ndjson.gz": {"raw_bytes": 500}},
             "readers": {"counters_reading": {"seconds": 10.0, "peak_bytes": 300}}}
    alone = G.scaled(found, targets=(1000,))["1000"]
    assert alone["bytes"] == 10000 and alone["readers"]["counters_reading"]["peak_bytes"] == 3000
    assert alone["how"] == ["in proportion to the laws, an upper bound"]
    earlier = {"laws": 50, "quantities": {"bytes": 600, "decisions_raw_bytes": 250, "counters_reading.seconds": 6.0,
                                          "counters_reading.peak_bytes": 200}}
    line = G.scaled(found, targets=(1000,), earlier=earlier)["1000"]
    assert line["bytes"] == 1000 + 8 * 900 and line["decisions_raw_bytes"] == 500 + 5 * 900
    assert line["readers"]["counters_reading"] == {"seconds": 82.0, "peak_bytes": 300 + 2 * 900,
                                                   "fits_the_sandbox": True}
    assert line["how"] == ["a line through two bundles"]


def test_a_reader_s_peak_and_time_are_its_own_child_s():
    hold = "import sys, time; block = bytearray(64 * 1024 * 1024); time.sleep(0.6); sys.exit(3)"
    found = G.measured_child([sys.executable, "-c", hold])
    assert found["exit"] == 3 and found["peak_bytes"] >= 64 * 1024 * 1024 and found["seconds"] >= 0.5
    small = G.measured_child([sys.executable, "-c", "import time; time.sleep(0.6)"])
    assert small["exit"] == 0 and 0 < small["peak_bytes"] < 48 * 1024 * 1024, "the child's own, not its parent's"


def test_the_tool_reads_a_folder_against_an_earlier_point(tmp_path):
    folder = _bundle(tmp_path, 20, 50)
    earlier = tmp_path / "earlier.json"
    earlier.write_text(json.dumps({"study_id": "8", "laws": 10, "quantities": {"bytes": 1, "decisions_raw_bytes": 1}}))
    out = tmp_path / "growth.json"
    assert G.main([str(folder), "--readers", "none", "--against", str(earlier), "--json", str(out)]) == 0
    found = json.loads(out.read_text())
    assert found["contract"] == G.CONTRACT and found["against"] == {"study_id": "8", "laws": 10}
    assert found["scaled"]["100000"]["how"] == ["a line through two bundles"]
    committed = json.loads(G.EARLIER.read_text())
    assert committed["study_id"] == "171" and committed["laws"] == 1005 and committed["quantities"]["bytes"] > 0
