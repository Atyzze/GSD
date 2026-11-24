from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import deep_reading as D  # noqa: E402
import history_reading as H  # noqa: E402

SPEC = {"beta": 1.0, "local_move": "toggle", "locality": 0.3, "regime": "zero_temperature", "swap_share": 0.5, "sweeps": 30,
        "terms": [["triangle_count", None, 1.0, "one", None]], "zero_temperature": True}


def row(n: int, *, degree: float, giant: float = 1.0, probes: int = 2, reach: float = 9.0) -> list:
    reads = [3.0] * probes + [None] * (4 - probes)
    return [n, *reads, reach, degree, giant, 0.0, 0.0, -0.5]


def chained(cls: str, fates: dict, values: dict, *, at_n: int = 16_384, groups=None, top: int | None = None) -> dict:
    groups = groups or [["empty"], ["given"], ["honeycomb"], ["cubic"], ["tesseract"]]
    return {"top_n": top or at_n, "values": values,
            "starts_reading": {"class": cls, "at_n": at_n, "trend": "steady", "by_n": {str(at_n): [cls, groups]},
                            "fates": {k: [v, 0.5] for k, v in fates.items()}}}


def five(n: int, **degrees) -> dict:
    base = {"empty": 4.0, "given": 4.0, "honeycomb": 3.0, "cubic": 6.0, "tesseract": 8.0}
    base.update(degrees)
    return {name: [row(1024, degree=d), row(n, degree=d)] for name, d in base.items()}


def test_each_law_is_put_in_the_first_kind_that_fits_it():
    lost = {"honeycomb": "melted", "cubic": "dense", "tesseract": "fell_apart"}
    moved = {"honeycomb": "melted", "cubic": "partly", "tesseract": "changed"}
    frozen = {"honeycomb": "melted", "cubic": "unmoved", "tesseract": "partly"}
    empty = H.law_entry("a", chained("remembers", moved, five(16_384, empty=0.0)), ("PARKED", "x"), SPEC)
    still = H.law_entry("b", chained("remembers", frozen, five(16_384)), ("PARKED", "x"), SPEC)
    gone = H.law_entry("c", chained("remembers", lost, five(16_384)), ("PARKED", "x"), SPEC)
    rest = H.law_entry("d", chained("remembers", moved, five(16_384)), ("PARKED", "x"), SPEC)
    assert [e["kind"] for e in (empty, still, gone, rest)] == list(H.KINDS)


def test_an_unmoved_lattice_is_not_counted_as_a_start_read():
    fates = {"honeycomb": "melted", "cubic": "unmoved", "tesseract": "changed"}
    entry = H.law_entry("a", chained("remembers", fates, five(16_384)), ("PARKED", "x"), SPEC)
    assert entry["lattices_readable"] == ["honeycomb", "tesseract"] and entry["random_readable"]
    values = five(16_384)
    values["honeycomb"][-1] = row(16_384, degree=3.0, probes=0)
    values["tesseract"][-1] = row(16_384, degree=8.0, giant=0.5)
    values["given"][-1] = row(16_384, degree=4.0, probes=1)
    entry = H.law_entry("a", chained("remembers", fates, values), ("PARKED", "x"), SPEC)
    assert entry["lattices_readable"] == [] and not entry["random_readable"]


def test_a_law_not_read_by_its_starts_is_left_out():
    assert H.law_entry("a", chained("not_read", {}, five(1024)), ("STOPPED", "empty"), SPEC) is None
    assert H.law_entry("a", {"values": {}}, ("STOPPED", "empty"), SPEC) is None


def test_the_groups_are_written_without_breaking_a_table():
    text = H.pattern([["empty", "honeycomb"], ["given"], ["cubic", "tesseract"]])
    assert text == "empty+honeycomb / random / cubic+tesseract"
    assert "|" not in text


def test_the_summary_counts_and_picks_the_candidates():
    moved = {"honeycomb": "melted", "cubic": "partly", "tesseract": "changed"}
    entries = [H.law_entry(str(i), chained("remembers", moved, five(n), at_n=n), ("PARKED", "starts_apart_twice"),
                           SPEC) for i, n in enumerate((4096, 16_384, 65_536))]
    entries.append(H.law_entry("f", chained("forgets", moved, five(4096), at_n=4096), ("STOPPED", "empty"), SPEC))
    entries.append(H.law_entry("h", chained("holds", {"cubic": "holds"}, five(4096), at_n=4096),
                               ("EXTENDING", "starts_apart"), SPEC))
    result = H.summarize(entries)
    assert result["laws"] == 5 and result["remembers"] == 3 and result["apart"] == 4
    assert result["classes"] == {"remembers": 3, "forgets": 1, "holds": 1}
    assert [c["law"] for c in result["candidates"]] == ["2", "1"]
    assert result["apart_by_class"]["holds"] == {"still running: starts_apart": 1}
    assert result["by_temperature"]["zero"] == {"laws": 5, "remembers": 3, "share": 0.6}
    text = H.render(dict(result, contract=H.CONTRACT, bundle="b", rules={"empty_degree": 0.5,
                                                                         "candidate_from_n": 16_384}))
    tables, run = [], []
    for line in text.splitlines() + [""]:
        if line.startswith("|"):
            run.append(line.count("|"))
        elif run:
            tables.append(run)
            run = []
    assert tables and all(len(set(widths)) == 1 for widths in tables)
    kept = result["kept_reach"]
    assert kept["laws"] == 4 and kept["by_what_moved"] == {"tesseract, structure": 4}


def test_the_deep_reading_keeps_the_deep_laws_and_reads_their_largest_size():
    record = {"campaign": "1", "spec": SPEC, "top_n": 65_536}
    shallow = chained("remembers", {}, five(16_384), top=16_384)
    assert D.deep_entry("a", shallow, ("PARKED", "x"), dict(record, top_n=16_384)) is None
    values = five(65_536)
    values["empty"] = [row(1024, degree=4.0), row(65_536, degree=16.0, probes=0)]
    deep = D.deep_entry("b", chained("remembers", {"cubic": "melted"}, values, at_n=65_536), ("STOPPED", "too_dense"),
                        record)
    assert deep["top_n"] == 65_536 and deep["chains"]["empty"]["mean_degree"] == 16.0
    assert not deep["chains"]["empty"]["readable"] and deep["chains"]["random"]["readable"]
    held = D.deep_entry("c", chained("holds", {"cubic": "holds"}, five(65_536), at_n=65_536), ("HELD", "x"), record)
    result = D.summarize([deep, held])
    assert result["deep"] == 2 and result["holding_nothing"] == 1 and result["laws"][0]["law"] == "b"
    assert result["holding_nothing_with_a_readable_chain"] == 1
    assert "### `b`" in D.render(dict(result, contract=D.CONTRACT, bundle="x", rules={"deep_from": 65_536}))
