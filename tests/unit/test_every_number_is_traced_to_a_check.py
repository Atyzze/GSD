from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
MAP = json.loads((FIXTURES / "numbers_and_checks.json").read_text(encoding="utf-8"))
FREEZE = set(json.loads((FIXTURES / "science_freeze.json").read_text(encoding="utf-8"))["files"])
FAULTS = json.loads((FIXTURES / "planted_faults.json").read_text(encoding="utf-8"))["faults"]
MEASURED = "measured"


def test_every_number_names_checks_of_the_three_kinds_or_says_it_is_measured():
    ids = [n["id"] for n in MAP["numbers"]]
    assert len(ids) == len(set(ids)) >= 15
    for number in MAP["numbers"]:
        kinds = {check["kind"] for check in number["checks"]}
        assert number["checks"] and kinds <= set(MAP["kinds"]), number["id"]
        assert kinds == {MEASURED} or MEASURED not in kinds, number["id"]
        if kinds != {MEASURED}:
            assert number["code"], (number["id"], "a computed number names the code it passes through")


def test_the_code_a_number_passes_through_is_in_the_science_freeze():
    for number in MAP["numbers"]:
        assert set(number["code"]) <= FREEZE, (number["id"], sorted(set(number["code"]) - FREEZE))


def test_every_check_named_is_a_test_or_a_tool_that_exists():
    for number in MAP["numbers"]:
        for check in number["checks"]:
            path, _, name = check["test"].partition("::")
            assert (ROOT / path).is_file(), (number["id"], path)
            if name:
                text = (ROOT / path).read_text(encoding="utf-8")
                assert re.search(rf"^def {re.escape(name)}\(", text, re.M), (number["id"], check["test"])


def test_every_computed_number_has_a_fault_planted_in_its_code():
    planted = {n for fault in FAULTS for n in fault["numbers"]}
    computed = {n["id"] for n in MAP["numbers"] if {c["kind"] for c in n["checks"]} != {MEASURED}}
    assert computed <= planted, sorted(computed - planted)
    assert planted <= {n["id"] for n in MAP["numbers"]}
