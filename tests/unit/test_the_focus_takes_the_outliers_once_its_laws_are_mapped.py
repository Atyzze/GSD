from __future__ import annotations

import json
import sqlite3

import pytest


def _metrics(d_w=None, d_V=None):
    from graph_scale_dynamics.scaleflow.one_shot import PROBE_VALUE
    out = {}
    for probe, value in (("d_w", d_w), ("d_V", d_V)):
        out[probe] = {"valid": value is not None, PROBE_VALUE[probe]: value}
    return out


def test_the_criterion_is_committed_and_a_reading_one_seed_shows_is_a_lucky_strike():
    from graph_scale_dynamics.operations import outliers as O
    rule = O.criterion()
    assert rule["lines"] == {"d_w": 3.5, "d_V": 3.0} and rule["repeated_by_seeds_at_least"] == 2
    rows = [{"n": 4096, "seed": seed, "metrics": _metrics(d_w=value)} for seed, value in ((0, 8.6), (1, 2.1), (2, 2.4))]
    lucky = O.judged(O.seed_readings(rows, None))
    assert lucky["lucky"] and lucky["seeds_over"] == [0] and lucky["probe"] == "d_w" and lucky["strength"] > 2
    rows = [{"n": 4096, "seed": seed, "metrics": _metrics(d_V=value)} for seed, value in ((0, 3.4), (1, 3.3), (2, 2.0))]
    region = O.judged(O.seed_readings(rows, None))
    assert not region["lucky"] and region["seeds_over"] == [0, 1] and region["probe"] == "d_V"
    assert O.judged(O.seed_readings([{"n": 512, "seed": 0, "metrics": _metrics(d_w=9.0)}], None)) is None, (
        "below from_n nothing is an outlier")


def test_the_strongest_outlier_comes_first_a_lucky_one_is_kept_and_one_inside_a_region_joins_it(monkeypatch):
    from graph_scale_dynamics.operations import focus as F
    from graph_scale_dynamics.operations import outliers as O
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE rung_summaries (campaign_id TEXT, candidate_id TEXT, n INTEGER, summary_json TEXT)")
    for law, d_w in (("weak", 3.9), ("strong", 6.0), ("lucky", 9.0), ("joins", 7.0), ("bulk", 2.0)):
        conn.execute("INSERT INTO rung_summaries VALUES ('7', ?, 4096, ?)", (law, json.dumps({"d_w": {"mean": d_w}})))
    repo = type("Repo", (), {"conn": conn})()
    seeds = {"weak": (3.9, 3.8, 2.0), "strong": (6.0, 5.5, 2.2), "lucky": (9.0, 2.0, 2.0), "joins": (7.0, 6.8, 6.5)}

    def rows_of(_repo, _campaign, law):
        return [{"n": 4096, "seed": i, "metrics": _metrics(d_w=v)} for i, v in enumerate(seeds[law])], None
    monkeypatch.setattr(F, "own_campaigns", lambda _repo, _study: ["7"])
    monkeypatch.setattr(F, "graph_number", lambda _repo, _campaign, law: 1)
    state = {"study": "176", "done": [], "skipped": {}}
    inside = lambda _repo, _state, entry: {"region": "GG#3"} if entry["candidate_id"] == "joins" else None
    label = lambda _repo, _campaign, law: f"S176C7-{law}"
    found = O.next_outlier(repo, state, rows_of=rows_of, inside=inside, label=label)
    assert found["candidate_id"] == "strong" and found["outlier"]["strength"] == pytest.approx(6.0 / 3.5, abs=1e-3)
    assert set(state["lucky"]) == {"lucky"} and state["inside"]["joins"]["region"] == "GG#3"
    assert "bulk" not in {e["candidate_id"] for e in O.outliers(repo, ["7"], rows_of=lambda *a: rows_of(*a)
                                                                if a[2] != "bulk" else ([], None))}
    state["done"].append({"law": "strong"})
    assert O.next_outlier(repo, state, rows_of=rows_of, inside=inside, label=label)["candidate_id"] == "weak"


def test_the_focus_asks_for_an_outlier_only_when_no_scoring_law_is_free(monkeypatch):
    from graph_scale_dynamics.operations import focus as F
    from graph_scale_dynamics.operations import outliers as O
    asked = []
    monkeypatch.setattr(O, "next_outlier", lambda *a, **k: asked.append(1) or {"candidate_id": "x", "campaign": "7"})
    state = {"study": "176", "done": [{"law": "a"}], "skipped": {}, "inside": {}}
    assert F._chosen(None, state, None, ranked=[{"candidate_id": "a", "campaign": "7", "score": 2}])["candidate_id"] == "x"
    assert asked == [1]
