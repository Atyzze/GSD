from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from graph_scale_dynamics.reporting.every_chain_report import decided_law

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import fleet_reading as F  # noqa: E402
import holds_reading as HR  # noqa: E402
import law_rows as L  # noqa: E402

from tests.unit.test_report_28_scores_every_chain import _bundle  # noqa: E402


def _edit(root: Path, path: str, change) -> None:
    file = root / path
    document = json.loads(file.read_text())
    change(document)
    file.write_text(json.dumps(document))


def test_a_campaign_the_bundle_could_not_carry_is_named_and_its_laws_are_not_read(tmp_path):
    root = _bundle(tmp_path)
    assert len(L.rows(root)) == 12
    missing = [{"campaign_id": "4", "why": "report cycle incomplete"}]
    _edit(root, "study.json", lambda d: d.update(missing=missing))
    assert L.study(root)["missing"] == missing
    with pytest.raises(ValueError, match="could not carry"):
        L.rows(root)


def test_a_failed_section_is_not_an_empty_one(tmp_path):
    root = _bundle(tmp_path)
    _edit(root, "campaign_1/28-decision-engine.json",
          lambda d: d["body"].update(every_chain={"contract": "x", "error": "KeyError: 'rungs'"}))
    _edit(root, "campaign_2/28-decision-engine.json",
          lambda d: d["body"]["the_record"].update(compute_by_regime={"error": "query timed out"}))
    failed = {part["name"]: part["failed_sections"] for part in L.study(root)["parts"] if part["drawn"]}
    assert failed == {"the sparse region, drawn blind (1 of 2)": {"every_chain": "failed: KeyError: 'rungs'"},
                      "the sparse region, drawn blind (2 of 2)": {"compute_by_regime": "failed: query timed out"}}
    controls = next(part for part in L.study(root)["parts"] if not part["drawn"])
    assert controls["failed_sections"]["every_chain"] == "absent", "a section a campaign never had is absent"


def test_decided_is_what_the_reports_count():
    assert decided_law({"action": "stop", "rule": "empty"}) and decided_law({"action": "done", "rule": "ladder_complete"})
    assert decided_law({"action": "hold", "rule": "starts_alike"}), "a park ends the law"
    assert not decided_law({"action": "run_next", "rule": "base_block"}), "still in its base block"
    assert not decided_law({"action": "stop", "rule": "failed"}), "an operation failed it"


def test_a_law_an_operation_failed_is_not_decided(tmp_path):
    root = _bundle(tmp_path)

    def decided() -> int:
        return sum(law["decided"] for law in L.drawn_laws(L.study(root)["parts"]))
    before = decided()
    _edit(root, "campaign_1/28-decision-engine.json",
          lambda d: d["body"]["laws"][1].update(action="stop", rule="failed"))
    assert decided() == before - 1


def test_a_holder_absent_from_the_newer_file_is_not_read_there_not_lost():
    then = {"a" * 64: {"class": "holds", "at_n": 4096, "fates": {"cubic": "holds"}, "decision": ["stop", "x", 4096]}}
    found = HR.step(then, {})
    assert found["lost"] == [] and found["not_read"] == ["a" * 12]


def test_two_fleet_readings_of_different_campaigns_are_not_compared():
    first = {"campaigns": ["1", "2"], "missing": [], "built_utc": "2026-10-20T10:00:00Z"}
    second = {"campaigns": ["1"], "missing": ["2"], "built_utc": "2026-10-20T11:00:00Z"}
    with pytest.raises(ValueError, match="different campaigns"):
        F.between(first, second)
