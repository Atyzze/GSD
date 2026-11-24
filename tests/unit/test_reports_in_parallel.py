from __future__ import annotations

import datetime as dt
import enum
import json
import math
import random
import tracemalloc
from collections import OrderedDict
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from graph_scale_dynamics.reporting.snapshot_transport import in_transport_types, json_bytes, volume
from graph_scale_dynamics.research.strict_json import sanitize_json, sanitize_json_in_place
from graph_scale_dynamics.research.snapshot_rows import parsed_rows
from graph_scale_dynamics.services.reporter import study_run as S

GIB = 1024 ** 3


class Color(enum.IntEnum):
    RED = 3


class Word(str, enum.Enum):
    A = "alpha"


class MyList(list):
    pass


class MyStr(str):
    pass


CONSTANT = {"k": [1, 2, (3, 4)], "d": Decimal("1.5")}


def _leaf(r):
    return r.choice([
        None, True, False, 0, 7, -3, 10 ** 30, 1.5, -0.0, float("nan"), float("inf"), -float("inf"),
        "s", "", "\ud800", "é", Decimal("1.25"), Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"),
        np.float64(2.5), np.float64("nan"), np.int64(4), np.bool_(True), np.str_("np"), np.float32(0.5),
        Color.RED, Word.A, MyStr("my"), dt.datetime(2026, 9, 30, 1, 2, 3), dt.date(2026, 9, 30), dt.time(4, 5),
        Path("/x/y"), b"\x00\x01", memoryview(b"ab"), bytearray(b"z"), np.array([1.0, np.nan]), complex(1, 2),
    ])


def _tree(r, depth):
    if depth <= 0 or r.random() < 0.3:
        return _leaf(r)
    kind = r.random()
    if kind < 0.35:
        return {r.choice("abcdef") + str(r.randint(0, 3)): _tree(r, depth - 1) for _ in range(r.randint(0, 5))}
    if kind < 0.45:
        return {r.choice([1, "1", 2, True, None, 2.5, ("t", 1), MyStr("m"), "x"]): _tree(r, depth - 1)
                for _ in range(r.randint(1, 4))}
    if kind < 0.75:
        return [_tree(r, depth - 1) for _ in range(r.randint(0, 5))]
    if kind < 0.8:
        return tuple(_tree(r, depth - 1) for _ in range(r.randint(0, 3)))
    if kind < 0.85:
        return {r.choice([1, 2, "a", "b", 2.5, None, False, Color.RED, np.float64(1.0)]) for _ in range(r.randint(0, 4))}
    if kind < 0.9:
        return OrderedDict((str(i), _tree(r, depth - 1)) for i in range(r.randint(0, 3)))
    if kind < 0.95:
        return MyList(_tree(r, depth - 1) for _ in range(r.randint(0, 3)))
    return CONSTANT


def _snapshot(seed):
    r = random.Random(seed)
    shared = [Decimal("2.5"), {"z": float("nan")}, (1, 2)]
    return {"campaign_snapshots": [{"campaign_id": "1", "rows": _tree(r, 5)}], "first": shared, "again": shared,
            "constant": CONSTANT, "tail": [_tree(r, 3) for _ in range(3)]}


def _round_trip(snapshot):
    cleaned, sanitization = sanitize_json(snapshot)
    if isinstance(cleaned, dict):
        cleaned = dict(cleaned, _snapshot_json_sanitization=sanitization)
    return json.loads(json.dumps(cleaned, separators=(",", ":"), allow_nan=False)), sanitization


def _same(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return list(a) == list(b) and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, float):
        return (math.isnan(a) and math.isnan(b)) or (a == b and math.copysign(1, a) == math.copysign(1, b))
    return a == b


def test_the_snapshot_converted_in_place_is_the_round_trip_of_its_copy():
    compared = 0
    for seed in range(400):
        expected, expected_diagnostics = _round_trip(_snapshot(seed))
        given = _snapshot(seed)
        converted, diagnostics = sanitize_json_in_place(given)
        assert converted is given, "a plain dict is converted where it lies, not copied"
        converted["_snapshot_json_sanitization"] = json.loads(json.dumps(diagnostics))
        assert _same(converted, expected), seed
        assert diagnostics == expected_diagnostics, seed
        compared += 1
    assert compared == 400
    assert CONSTANT == {"k": [1, 2, (3, 4)], "d": Decimal("1.5")}, "a module's constant was changed"


def test_the_channel_gives_the_reports_what_the_round_trip_gave_them():
    for seed in range(60):
        expected, _ = _round_trip(_snapshot(seed))
        assert _same(in_transport_types(_snapshot(seed)), expected), seed
    assert _same(in_transport_types([Decimal("1"), (2,)]), _round_trip([Decimal("1"), (2,)])[0])
    assert _same(in_transport_types(Word.A), "alpha") and type(in_transport_types(np.float64(1.5))) is float


def test_only_what_nothing_else_holds_is_changed_where_it_lies():
    snapshot = {"rows": [{"metrics": {"d_s": 2.0, "bad": float("nan")}, "n": Decimal("64")} for _ in range(3)],
                "set": {3, 1, 2}}
    kept = snapshot["rows"][1]
    elsewhere = snapshot["rows"][2]["metrics"]
    where = (id(snapshot["rows"]), id(snapshot["rows"][0]), id(snapshot["rows"][0]["metrics"]), id(snapshot["rows"][2]))
    converted, diagnostics = sanitize_json_in_place(snapshot)
    rows = converted["rows"]
    assert converted is snapshot and (id(rows), id(rows[0]), id(rows[0]["metrics"]), id(rows[2])) == where
    assert rows[0]["metrics"]["bad"] is None and rows[0]["n"] == 64.0 and type(rows[0]["n"]) is float
    assert rows[1] is not kept and kept["n"] == Decimal("64") and math.isnan(kept["metrics"]["bad"])
    assert rows[1] == rows[0], "the copy is converted as the row in place is"
    assert rows[2]["metrics"] is not elsewhere and math.isnan(elsewhere["bad"]) and rows[2]["metrics"]["bad"] is None
    assert converted["set"] == [1, 2, 3]
    assert (diagnostics["nonfinite_values_replaced"], diagnostics["converted_values"]) == (3, 4), diagnostics


def test_a_dict_with_other_keys_is_copied_and_its_count_is_one_walks():
    expected, expected_diagnostics = _round_trip({"x": {"a": Decimal("1"), 2: "two", "b": float("inf")}})
    converted, diagnostics = sanitize_json_in_place({"x": {"a": Decimal("1"), 2: "two", "b": float("inf")}})
    converted["_snapshot_json_sanitization"] = json.loads(json.dumps(diagnostics))
    assert _same(converted, expected) and diagnostics == expected_diagnostics
    assert [e["path"] for e in diagnostics["examples"]] == ["$.x.b"]


def test_the_conversion_holds_no_second_tree():
    def build():
        return {"measurements": [{"candidate_id": f"c{i}", "n": 64, "metrics": {"d_s": {"d_s": i / 7, "w": [1, 2, 3]},
                                                                              "mean_degree": float(i % 9)}}
                                 for i in range(20000)]}
    tracemalloc.start()
    try:
        snapshot = build()
        old_size, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        _round_trip(snapshot)
        _, old_peak = tracemalloc.get_traced_memory()
        del snapshot
        snapshot = build()
        new_size, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        in_transport_types(snapshot)
        _, new_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert old_peak > 1.5 * old_size, (old_peak, old_size)
    assert new_peak < 1.05 * new_size, f"the conversion held {new_peak - new_size} bytes beside a {new_size}-byte snapshot"


def test_the_volume_is_the_texts_length_exactly_when_small_and_closely_when_estimated():
    small = {"campaign_snapshots": [{"campaign_id": "1", "snapshot_scope": "full_primary",
                                     "rows": [{"a": i, "b": "x" * (i % 5)} for i in range(50)],
                                     "table": {str(i): [i, i] for i in range(40)}}],
             "campaign_id": "1", "_snapshot_json_sanitization": {"examples": []}}
    text = len(json.dumps(small, separators=(",", ":")))
    measured = volume(small)
    assert (measured["json_bytes"], measured["estimated"]) == (text, False)
    assert [p["part"] for p in measured["parts"]] == ["rows", "table"] and measured["parts"][0]["rows"] == 50
    big = [{"i": i, "text": "y" * (i % 50)} for i in range(20000)]
    size, estimated = json_bytes(big)
    assert estimated and abs(size - len(json.dumps(big, separators=(",", ":")))) < 0.02 * size
    assert json_bytes([]) == (2, False) and json_bytes({}) == (2, False) and json_bytes("ab") == (4, False)


class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def fetchmany(self, size):
        out, self.rows = self.rows[:size], self.rows[size:]
        return out


class _Conn:
    def __init__(self, rows, stream):
        self.rows, self.asked = rows, []
        if stream:
            self.stream = lambda sql, args, size: (self.asked.append(size), iter(self.rows))[1]

    def execute(self, sql, args):
        return _Cursor(self.rows)


@pytest.mark.parametrize("stream", [True, False])
def test_rows_parsed_a_batch_at_a_time_are_the_rows_parsed_one_by_one(stream):
    texts = [json.dumps({"d_s": {"d_s": i / 3, "window": [i, i + 1]}, "mean_degree": i % 5, "nan": float("nan")})
             for i in range(2345)]
    rows = [{"candidate_id": f"c{i}", "metrics_json": texts[i], "n": 64} for i in range(2345)]
    conn = _Conn(rows, stream)
    got = parsed_rows(conn, "SELECT ...", (), "metrics_json", "metrics", batch=500)
    expected = [{"candidate_id": row["candidate_id"], "n": 64, "metrics": json.loads(row["metrics_json"])}
                for row in rows]
    assert json.dumps(got) == json.dumps(expected) and all(list(g) == list(e) for g, e in zip(got, expected, strict=True))
    assert conn.asked == ([500] if stream else [])
    first, second = got[0]["metrics"], got[1]["metrics"]
    assert next(iter(first)) is next(iter(second)), "one parse per batch shares the keys between its rows"


def test_a_text_that_is_not_one_json_value_fails_as_it_always_did():
    for bad in ("1,2", "", "{", None):
        rows = [{"metrics_json": "{}"}, {"metrics_json": bad}, {"metrics_json": "{}"}]
        with pytest.raises((TypeError, ValueError)):
            parsed_rows(_Conn(rows, True), "SELECT ...", (), "metrics_json", "metrics")


def _root(tmp_path, campaign, **files):
    folder = tmp_path / f"live_campaign_{campaign}"
    folder.mkdir(exist_ok=True)
    for name, body in files.items():
        (folder / name).write_text(json.dumps(body))


def test_a_measure_from_before_the_transport_is_not_charged(tmp_path):
    _root(tmp_path, "1", **{"manifest.json": {"cycle": {"snapshot_resident_bytes": 10 * GIB,
                                                        "snapshot_decompressed_bytes": 5 * GIB}},
                            S.COST_NAME: {"worker_peak_bytes": 17 * GIB, "child_private_peak_bytes": 4 * GIB}})
    assert S.campaign_cost(tmp_path, "1") == (int(1.25 * (10 * GIB + 5 * GIB)), "guessed")
    _root(tmp_path, "1", **{S.COST_NAME: {"worker_peak_bytes": 9 * GIB, "worker_resident_bytes": 7 * GIB,
                                          "child_private_peak_bytes": 3 * GIB, "transport": S.TRANSPORT}})
    assert S.campaign_cost(tmp_path, "1") == (int(1.25 * 10 * GIB), "measured"), "the peak, or what it held and a child"
    _root(tmp_path, "1", **{S.COST_NAME: {"worker_peak_bytes": 12 * GIB, "worker_resident_bytes": 7 * GIB,
                                          "child_private_peak_bytes": 3 * GIB, "transport": S.TRANSPORT}})
    assert S.campaign_cost(tmp_path, "1") == (int(1.25 * 12 * GIB), "measured")


def test_an_unmeasured_child_is_charged_a_share_of_the_snapshot_not_all_of_it(tmp_path):
    channel = S.LocalChannel("1", tmp_path / "live_campaign_1", db="folder", progress=tmp_path / "1.json",
                             request_id="r", workers=16, memory_budget=64 * GIB)
    workers, why = channel.pool_size("quiet", {"resident_bytes": 11 * GIB}, 25)
    assert "at 5.50 GiB each (guessed)" in why, why
