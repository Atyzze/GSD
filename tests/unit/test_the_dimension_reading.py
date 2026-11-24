from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import dimension_reading as R  # noqa: E402
import history_reading as H  # noqa: E402

SIZES = (1024, 4096, 16384)
LEDGER = {"spec": {"terms": [["triangle_count", None, 1.0, "one", None]], "zero_temperature": True},
          "fate": ["starts_apart_twice", 16384]}


def cells(d, *, reach=lambda n, d: n ** (1 / d), degree=6.0, d_b=None):
    return [[n, d, d, d if d_b is None else d_b, 2.0, reach(n, d), degree, 1.0, 0.0, 0.0, -0.1] for n in SIZES]


def chained(values: dict, fates: dict | None = None) -> dict:
    marks = {k: [v, 0.5] for k, v in (fates or {}).items()}
    return {"top_n": 16384, "values": values, "starts_reading": {"class": "remembers", "at_n": 16384, "fates": marks}}


def flat(n, d):
    return 1.5 * math.log(n)


def entry(values, fates=None):
    return R.law_entry("law", chained(values, fates), list(H.COLUMNS), LEDGER, ("PARKED", "starts_apart_twice"),
                       "1", R.calibration())


def test_a_chain_from_empty_with_a_dimension_is_grown_and_one_without_is_not():
    found = entry({"empty": cells(2.0), "given": cells(4.0, reach=flat)})
    assert found["kinds"] == ["grown"]
    assert found["chains"]["empty"]["kind"] == "grown" and found["chains"]["given"]["kind"] is None


def test_a_lattice_start_is_changed_only_away_from_its_band_and_its_own_reading():
    found = entry({"honeycomb": cells(3.0), "cubic": cells(2.8), "tesseract": cells(3.5)},
                  {"honeycomb": "melted", "cubic": "partly", "tesseract": "holds"})
    kinds = {name: c["kind"] for name, c in found["chains"].items()}
    assert kinds == {"honeycomb": "changed", "cubic": "kept_d", "tesseract": "kept_d"}


def test_a_line_and_a_chain_beyond_the_checked_range_are_marked():
    found = entry({"empty": cells(1.0, degree=2.0), "given": cells(5.0)})
    assert found["chains"]["empty"]["line"] and not found["chains"]["empty"]["beyond_checked"]
    assert found["chains"]["given"]["beyond_checked"]


def test_the_summary_counts_the_kinds():
    entries = [entry({"empty": cells(2.0)}),
               entry({"honeycomb": cells(3.0)}, {"honeycomb": "melted"}),
               entry({"cubic": cells(2.8)}, {"cubic": "partly"}),
               entry({"given": cells(4.0, reach=flat)})]
    for i, e in enumerate(entries):
        e["law"] = str(i)
    result = R.summarize(entries, R.calibration())
    assert (result["grown"]["laws"], result["changed"]["laws"], result["kept_d_only"]["laws"]) == (1, 1, 1)
    assert result["kept_d_only"]["whose_lattice_does_not_hold"] == 1


def test_the_reading_renders_without_breaking_a_table():
    entries = [entry({"empty": cells(2.0)}), entry({"honeycomb": cells(3.0)}, {"honeycomb": "melted"})]
    entries[1]["law"] = "other"
    result = {"contract": R.CONTRACT, "bundle": "b", "test": "t", "calibration": R.calibration(),
              "line_below": R.LINE_BELOW, **R.summarize(entries, R.calibration())}
    text = R.render(result)
    assert "## Grown from empty or from the random graph" in text and "`law`" in text
    rows = [line for line in text.splitlines() if line.startswith("| empty |") or line.startswith("| honeycomb |")]
    assert rows and all(line.count("|") == 17 for line in rows)


def test_a_chain_whose_larger_sizes_are_dropped_is_named_with_its_top_and_why():
    rows = cells(2.0) + [[65536, 2.0, 2.0, 2.0, 2.0, 100.0, 6.0, 0.6, 0.0, 0.0, -0.1],
                         [262144, 2.0, 2.0, 2.0, 2.0, 100.0, 20.0, 1.0, 0.0, 0.0, -0.1]]
    unread = [[65536, None, None, None, None, None, None, None, None, None, None]]
    found = entry({"empty": rows, "given": cells(4.0, reach=flat) + unread, "cubic": cells(3.0)})
    from_empty = found["chains"]["empty"]
    assert from_empty["kind"] == "grown" and from_empty["sizes"] == list(SIZES) and from_empty["top_n"] == 262144
    assert [(d["n"], d["why"]) for d in from_empty["dropped_above"]] == [(65536, "in pieces"),
                                                                     (262144, "degree off the window")]
    assert "dropped_above" not in found["chains"]["cubic"], "judged at its top size"
    found["law"] = "a" * 64
    part = R.below_top([found])
    assert part["chains"] == 2 and part["by_kind"] == {"grown": 1, "not dimensional": 1}
    assert part["by_why_at_the_next_size"] == {"in pieces": 1, "not read": 1}
    assert len(part["entries"]) == 1 and part["entries"][0]["chain"] == "empty"
    assert part["entries"][0]["top_n"] == 262144
    assert part["not_dimensional"] == {
        "aaaaaaaaaaaa random": "campaign 1; judged on 1,024, 4,096, 16,384; top 65,536; 65,536 not read"}
    result = {"contract": R.CONTRACT, "bundle": "b", "test": "t", "calibration": R.calibration(),
              "line_below": R.LINE_BELOW, **R.summarize([found], R.calibration())}
    text = R.render(result)
    assert "2 chains (1 of them not dimensional) are judged below their top size" in text
    assert "## Chains judged below their top size" in text and "| `aaaaaaaaaaaa` | 1 | empty | grown |" in text
    assert "(not 65,536: in pieces, 262,144: degree off the window)" in text


def test_a_size_is_dropped_with_a_reason_exactly_when_the_test_cannot_use_it():
    from graph_scale_dynamics.research import dimension_test as T
    for degree in (None, 0.2, 0.5, 0.6, 6.0, 15.4, 15.5, 30.0):
        for piece in (None, 0.5, 0.949, 0.95, 1.0):
            cell = {"n": 4096, "mean_degree": degree, "giant_fraction": piece, "reach": 10.0}
            assert (R.why_dropped(cell) is None) == bool(T.usable([cell])), (degree, piece)
