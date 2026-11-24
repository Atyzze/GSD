from __future__ import annotations

from collections import Counter

from graph_scale_dynamics.research import probes_baseline as B


def test_the_set_is_the_lattice_starts_and_320_graphs_drawn_by_seed():
    graphs = B.graphs(top=256)
    names = [graph["name"] for graph in graphs]
    assert len(names) == len(set(names)) and len(graphs) > B.DRAWN
    drawn = graphs[-B.DRAWN:]
    assert all(graph["kind"] == "lattice start" and graph["n"] <= 256 for graph in graphs[:-B.DRAWN])
    assert Counter(graph["has"] for graph in drawn) == {B.NONE: 184, B.A_DIMENSION: 136}
    assert min(graph["n"] for graph in drawn) == 9 and max(graph["n"] for graph in drawn) == 3025
    assert B.drawn(11) == B.drawn(11) and B.drawn(11)["edges"] != B.drawn(19)["edges"]
    assert B.drawn(4)["kind"].startswith("ring with") and B.drawn(6)["kind"].startswith("square lattice with")


def _document(readings: dict) -> dict:
    graphs = {}
    for name, (has, d_s, d_v) in readings.items():
        result = {"component": 100}
        for probe, key, value in (("d_s", "d_s", d_s), ("d_V", "d_V_window", d_v)):
            result[probe] = ({"valid": True, key: repr(value)} if isinstance(value, float)
                             else {"valid": False, "refusal": value})
        for probe in ("d_B", "d_w"):
            result[probe] = {"valid": False, "refusal": "WINDOW_TOO_SHORT"}
        graphs[name] = {"kind": "a kind", "has": has, "result": result}
    return {"contract": B.CONTRACT, "graphs": graphs}


def test_the_comparison_names_what_moved_what_was_lost_and_what_was_gained():
    before = _document({"plane_s1": (B.A_DIMENSION, 1.44, 2.1), "tree_s2": (B.NONE, 1.9, "EXPONENTIAL_GROWTH"),
                        "line_s3": (B.A_DIMENSION, 1.0, 1.0), "small_s4": (B.A_DIMENSION, 3.2, "NO_SCALING_WINDOW")})
    after = _document({"plane_s1": (B.A_DIMENSION, 1.95, 2.1), "tree_s2": (B.NONE, "EXPONENTIAL_GROWTH", 2.4),
                       "line_s3": (B.A_DIMENSION, 1.0, 1.0), "small_s4": (B.A_DIMENSION, "NO_SCALING_WINDOW", "x")})
    found = B.compare(before, after)
    assert found["d_s"]["read_in_both"] == 2 and found["d_s"]["same_to_the_last_digit"] == 1
    assert found["d_s"]["moved"] == [("plane_s1", 1.44, 1.95)]
    assert found["d_s"]["lost"] == {"none: a kind: EXPONENTIAL_GROWTH": [(100, 1.9)],
                                    "a dimension: a kind: NO_SCALING_WINDOW": [(100, 3.2)]}
    assert found["d_V"]["gained"] == {"none: a kind": [(100, 2.4)]} and found["d_V"]["lost"] == {}
    assert found["d_s"]["read_now"] == {B.A_DIMENSION: 2, B.NONE: 0}
    said = B.render(found)
    assert "d_s: read in both 2, the same to the last digit 1" in said and "moved plane: 1.4400 to 1.9500" in said
    assert "lost 1 (none: a kind: EXPONENTIAL_GROWTH): 1.9 at 100" in said


def test_a_reading_is_written_to_the_last_digit():
    assert B.plain({"a": 0.1 + 0.2, "probe_seconds": 3, "b": [1, float("inf")]}) == {
        "a": "0.30000000000000004", "b": [1, "inf"]}
