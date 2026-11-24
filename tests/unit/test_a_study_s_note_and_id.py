from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.operations import study_record as R
from graph_scale_dynamics.operations import study as S
from graph_scale_dynamics.reporting.study_bundle import study_id as bundle_study_id

ROOT = Path(__file__).resolve().parents[2]


class _Repo:
    def __init__(self, specs):
        self.specs = specs

    def all_campaigns(self):
        return [{"campaign_id": str(i), "spec": spec} for i, spec in enumerate(self.specs, start=1)]


def test_the_folder_s_name_is_not_its_study(tmp_path):
    named_256 = tmp_path / "256" / "main" / "var"
    named_257 = tmp_path / "257" / "main" / "var"
    R.write(named_256, study=R.DEFAULT, kind=R.DEFAULT, chosen_by=R.BY_DEFAULT, log=lambda *_: None)
    R.write(named_257, study="256", kind=R.DESIGNED, chosen_by=R.BY_FLAG, log=lambda *_: None)
    assert R.study_id(named_256) == "default" and R.study_id(named_257) == "256"
    assert bundle_study_id(named_256 / "reports") == "default"
    assert bundle_study_id(named_257 / "reports") == "256", "its bundles are named for the study it started"
    assert R.study_id(tmp_path / "252 base 4 quadrant" / "main" / "var") == "default", "no record, no campaign"


def test_a_record_is_written_once_and_names_who_chose_it(tmp_path):
    var = tmp_path / "var"
    lines: list[str] = []
    first = R.write(var, study="256", kind=R.DESIGNED, chosen_by=R.BY_FLAG, source={"design": "x"}, log=lines.append)
    assert first["chosen_by"] == "--study" and first["contract"] == R.RECORD_CONTRACT
    again = R.write(var, study="999", kind=R.DEFAULT, chosen_by=R.BY_DEFAULT, log=lines.append)
    assert again["study"] == "256", "a folder is one study for its whole life"
    assert len(lines) == 1 and "study 256" in lines[0]
    assert R.write(None, study="256", kind=R.DESIGNED, chosen_by=R.BY_FLAG) is None
    for bad in ("", "../255", "a b", "x" * 80):
        with pytest.raises(ValueError):
            R.write(tmp_path / bad.replace("/", "_") / "v", study=bad, kind=R.DEFAULT, chosen_by=R.BY_DEFAULT)


def test_a_folder_started_before_633_is_read_from_its_campaigns(tmp_path):
    designed = {"study_design": {"study": "256", "campaign": 0}}
    controls = {"name": "campaign-standing-controls"}
    var = tmp_path / "var"
    repo = _Repo([designed, designed, controls])
    assert R.study_id(var, repo) == "256" and bundle_study_id(var / "reports", repo) == "256"
    lines: list[str] = []
    record = R.ensure(var, repo, log=lines.append)
    assert record["study"] == "256" and record["kind"] == R.DESIGNED and record["chosen_by"] == R.BY_CAMPAIGNS
    assert R.ensure(var, _Repo([]), log=lines.append)["study"] == "256" and len(lines) == 1
    quadrants = _Repo([{"description": "a quadrant"}] * 4)
    assert R.ensure(tmp_path / "q", quadrants, log=lambda *_: None)["study"] == R.DEFAULT
    assert R.ensure(tmp_path / "empty", _Repo([])) is None, "a folder not yet started is recorded at its start"
    with pytest.raises(ValueError, match="more than one study"):
        R.of_campaigns([{"study_design": {"study": "255"}}, {"study_design": {"study": "256"}}])


def test_the_first_start_keeps_the_study_s_note_in_its_record_once(tmp_path):
    lines = []
    tree = tmp_path / "anything" / "main"
    (tree / "graph_scale_dynamics" / "resources" / "readings").mkdir(parents=True)
    (tree / "graph_scale_dynamics" / "resources" / "readings" / "studies.json").write_text(json.dumps({"studies": [
        {"id": "254", "notes": "zero temperature, cap 8, from empty and from a shape"}]}))
    line = S.note_for(tree, "254")
    assert line == "zero temperature, cap 8, from empty and from a shape", "the register's line first"
    assert S.note_for(tree, R.DEFAULT, labels=["a"]) == "base 1 quadrant: a", "the default study is in no register"
    var = tree / "var"
    assert S.record_note(var, line, log=lines.append) is None, "no record, nothing to note"
    R.write(var, study="254", kind=R.DESIGNED, chosen_by=R.BY_FLAG, log=lines.append)
    assert S.record_note(var, line, log=lines.append)["note"] == line and R.note(var) == line
    assert S.record_note(var, "something else", log=lines.append)["note"] == line, "never over a note already there"
    assert not list(tmp_path.rglob("notes.txt")), "nothing written beside the tree"
    survey = S.note_for(tmp_path / "255" / "main", R.DEFAULT, labels=["zero temperature, mean degree to 16",
                                                                      "finite temperature, mean degree to 16"])
    assert survey == "base 2 quadrant: zero temperature, mean degree to 16; finite temperature, mean degree to 16"


def test_the_register_carries_a_line_for_every_study_the_tree_can_start():
    from graph_scale_dynamics.operations import study_design
    register = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "readings" / "studies.json").read_text(encoding="utf-8"))
    assert S.note_for(ROOT, None, labels=["x"]) != "", "a start with no id still gets a line"
    assert [s["id"] for s in register["studies"]] == study_design.designed_studies(ROOT), "one entry a design"
    for entry in register["studies"]:
        assert entry["notes"] and S.note_for(ROOT, entry["id"]) == entry["notes"], entry["id"]
