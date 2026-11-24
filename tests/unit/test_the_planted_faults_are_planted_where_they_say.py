from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import planted_faults as P  # noqa: E402

FREEZE = set(json.loads((ROOT / "tests" / "fixtures" / "science_freeze.json").read_text(encoding="utf-8"))["files"])
NUMBERS = {n["id"] for n in json.loads((ROOT / "tests" / "fixtures" / "numbers_and_checks.json").read_text(
    encoding="utf-8"))["numbers"]}


def test_each_fault_is_once_in_a_frozen_file_and_changes_it():
    faults = P.faults()
    assert len({f["id"] for f in faults}) == len(faults) >= 30
    for fault in faults:
        assert fault["file"] in FREEZE, (fault["id"], "a fault is planted in the code a number passes through")
        text = (ROOT / fault["file"]).read_text(encoding="utf-8")
        assert text.count(fault["find"]) == 1, (fault["id"], text.count(fault["find"]))
        assert fault["replace"] != fault["find"], fault["id"]
        assert fault["numbers"] and set(fault["numbers"]) <= NUMBERS, (fault["id"], fault["numbers"])
        assert fault["fault"].strip(), fault["id"]


def test_every_fault_has_tests_that_read_its_module_and_never_the_test_of_the_faults_themselves():
    for fault in P.faults():
        chosen = P.tests_for(fault)
        assert chosen and not set(chosen) & set(P.ABOUT_THE_FAULTS), fault["id"]


def test_every_failure_is_read_from_pytest_s_summary():
    out = ("..F\nFAILED tests/unit/test_a.py::test_one[x-1] - assert 1 == 2\n"
           "ERROR tests/unit/test_b.py::test_two - RuntimeError\n1 failed, 1 error\n")
    assert P.failures(out) == ["tests/unit/test_a.py::test_one[x-1]", "tests/unit/test_b.py::test_two"]


def test_a_module_is_named_by_its_path_or_by_its_package():
    module = "graph_scale_dynamics.measurements.fits"
    assert P.names_the_module("from graph_scale_dynamics.measurements.fits import line", module)
    assert P.names_the_module("from graph_scale_dynamics.measurements import fits as F", module)
    assert P.names_the_module("from graph_scale_dynamics.measurements import (\n    estimators,\n    fits,\n)", module)
    assert not P.names_the_module("from graph_scale_dynamics.measurements import fitness", module)
    assert not P.names_the_module("from graph_scale_dynamics.observability import fits", module)


def _tree(root: Path) -> None:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "mod.py").write_text("SCALE = 2\nUNUSED = 7\n\n\ndef twice(x):\n    return SCALE * x\n",
                                         encoding="utf-8")
    (root / "tests" / "unit").mkdir(parents=True)
    (root / "tests" / "scientific").mkdir(parents=True)
    (root / "tests" / "unit" / "test_mod.py").write_text(
        "from pkg import mod\n\n\ndef test_twice():\n    assert mod.twice(3) == 6\n", encoding="utf-8")
    digest = hashlib.sha256((root / "pkg" / "mod.py").read_bytes()).hexdigest()
    (root / "tests" / "unit" / "test_mod_bytes.py").write_text(
        "import hashlib\nfrom pathlib import Path\n\nfrom pkg import mod\n\n\ndef test_the_bytes():\n"
        f"    assert hashlib.sha256(Path(mod.__file__).read_bytes()).hexdigest() == {digest!r}\n", encoding="utf-8")


def test_a_fault_a_test_fails_on_is_caught_one_none_fails_on_is_let_by_and_the_tree_is_left_alone(tmp_path):
    root = tmp_path / "root"
    _tree(root)
    before = (root / "pkg" / "mod.py").read_text(encoding="utf-8")
    chosen = [{"id": "scale", "file": "pkg/mod.py", "find": "SCALE = 2\n", "replace": "SCALE = 3\n", "numbers": ["x"]},
              {"id": "unused", "file": "pkg/mod.py", "find": "UNUSED = 7\n", "replace": "UNUSED = 8\n",
               "numbers": ["x"]}]
    lines: list[str] = []
    found = P.run(chosen, root=root, where=tmp_path / "scratch" / "tree", log=lines.append)
    outcomes = {row["id"]: row["outcome"] for row in found["faults"]}
    assert outcomes == {"scale": "caught", "unused": "let by"}, "a test that fails on any edit catches nothing"
    assert found["faults"][0]["failed"].endswith("test_twice"), found["faults"][0]
    assert all(row["set_aside_shown"] == ["tests/unit/test_mod_bytes.py::test_the_bytes"] for row in found["faults"])
    assert found["counts"] == {"caught": 1, "let by": 1}
    assert (root / "pkg" / "mod.py").read_text(encoding="utf-8") == before
    assert not (tmp_path / "scratch" / "tree").exists()
    assert "| unused | x | let by |" in P.render(found)
