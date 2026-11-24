from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from graph_scale_dynamics.observability import space_score as S

ROOT = Path(__file__).resolve().parents[2]


def _side(n, *, dims=(2.0, 2.0, 2.0), walk=2.0, reach=None, degree=4.0, triangles=0.0, squares=1.0, kappa=0.0,
          giant=1.0, energy=-1.0):
    values = {"d_s": dims[0], "d_V": dims[1], "d_B": dims[2], "d_w": walk,
              "reach": math.sqrt(n) / 2 if reach is None else reach, "mean_degree": degree,
              "triangles_per_node": triangles, "squares_per_node": squares, "kappa": kappa, "giant_fraction": giant,
              "energy_per_node": energy}
    return {key: {"mean": value} for key, value in values.items()}


def _rung(n, from_empty=None, given=None, ends=None):
    return {"n": n, "seeds": 3, "empty": from_empty or _side(n), "given": given or _side(n), "ends": ends or {"completed": 3}}


def _small_world(n, step):
    return _side(n, dims=(2.5, 2.6, 2.7), walk=None, reach=math.log2(n) / 1.3, kappa=-0.2 - 0.1 * step, squares=0.8 - 0.1 * step)


def test_a_lattice_is_a_space_and_a_small_world_is_not():
    rungs = [_rung(n, from_empty=_small_world(n, i)) for i, n in enumerate((1024, 4096, 16384))]
    score = S.space_score({"rungs": rungs})
    given, from_empty = score["chains"]["given"], score["chains"]["empty"]
    assert given["d"] == 2 and given["space"] and given["worst"] == 0.0
    assert from_empty["space"] is False and from_empty["d"] == 3, "2.6 is nearer 3; a space is judged against its own d"
    worst = max(from_empty["rungs"], key=lambda r: r["distance"])
    assert worst["worst"] in ("reach", "local") and worst["distance"] > 1
    assert score["spaces"] == ["given"] and score["judged"] == [1024, 4096, 16384]
    assert score["stage"] == 2, "a space from one start, the chain from empty no nearer it at 16,384 than at 1,024"
    assert [s["passed"] for s in score["stages"]] == [True, True, False, False]


def test_each_property_in_its_tolerance():
    before = _side(1024)
    after = _side(4096, dims=(2.1, 2.0, 1.9), walk=2.15, degree=4.0 * 1.02, triangles=0.02, kappa=0.02, giant=0.98,
                  reach=16 * 4 ** (1 / (2 - 0.15)))
    props = S.space_score({"rungs": [_rung(1024, given=before), _rung(4096, given=after)]})["chains"]["given"]["rungs"][1]["properties"]
    assert props["dimension"]["distance"] == 0.0 and props["dimension"]["target"] == 2
    assert props["agree"]["distance"] == pytest.approx(0.2 / 0.3, abs=1e-3), "each probe within 0.15 of one value"
    assert props["walk"]["distance"] == pytest.approx(1.0, abs=1e-3)
    assert 0.9 < props["reach"]["distance"] < 1.2
    assert props["local"]["distance"] == pytest.approx(1.0, abs=0.02) and props["local"]["from_n"] == 1024
    assert props["piece"]["distance"] == pytest.approx(1.0, abs=1e-3)


def test_sizes_below_1024_are_not_judged_but_every_run_counts():
    wild = _side(256, dims=(0.5, 5.0, 3.0), giant=0.3)
    score = S.space_score({"rungs": [_rung(256, given=wild), _rung(1024), _rung(4096)]})
    assert score["judged"] == [1024, 4096] and score["chains"]["given"]["space"] and score["stage"] == 4
    cut = S.space_score({"rungs": [_rung(256, ends={"completed": 2, "budget": 1}), _rung(1024), _rung(4096)]})
    assert cut["stage"] == 0 and cut["full"]["cut"] == [{"n": 256, "ends": {"budget": 1}}]
    capped = S.space_score({"rungs": [_rung(1024), _rung(4096, ends={"mean_degree_cap": 3})]})
    assert capped["stage"] == 0, "a run stopped at the mean-degree cap is not a full reading"
    ceiling = S.space_score({"rungs": [_rung(1024, ends={"ceiling": 3}), _rung(4096, ends={"ceiling": 2, "completed": 1})]})
    assert ceiling["full"]["passed"], "a run that spent its sweeps went to its own end"


def test_one_size_or_an_unread_dimension_is_no_space():
    assert S.space_score({"rungs": [_rung(1024)]})["chains"]["given"]["space"] is False
    unread = _side(4096)
    for probe in ("d_s", "d_V", "d_B"):
        unread[probe] = {"mean": None}
    score = S.space_score({"rungs": [_rung(1024), _rung(4096, given=unread)]})
    assert score["chains"]["given"]["space"] is False and score["chains"]["empty"]["space"] is True
    assert score["spaces"] == ["empty"], "either chain counts: the readings are equals"


def test_the_stages_need_the_one_before():
    met = S.space_score({"rungs": [_rung(1024), _rung(4096)]})
    assert met["stage"] == 4 and all(g["distance"] == 0.0 for g in met["gaps"])
    closing = S.space_score({"rungs": [_rung(1024, from_empty=_side(1024, energy=-0.8)),
                                       _rung(4096, from_empty=_side(4096, energy=-0.9))]})
    assert closing["stage"] == 3 and closing["gaps"][0]["worst"] == "energy_per_node"
    assert closing["gaps"][1]["distance"] < closing["gaps"][0]["distance"]
    parting = S.space_score({"rungs": [_rung(1024, from_empty=_side(1024, energy=-0.9)),
                                       _rung(4096, from_empty=_side(4096, energy=-0.8))]})
    assert parting["stage"] == 2
    far = _side(1024, dims=(1.0, 1.0, 1.0))
    assert S.space_score({"rungs": [_rung(1024, far, far), _rung(4096, _side(4096, dims=(1.0, 1.0, 1.0)),
                                                                     _side(4096, dims=(1.0, 1.0, 1.0)))]})["stage"] == 1


def test_how_much_a_law_feels_n():
    def term(op, c0, scale, p=None, k=None):
        return {"op": op, "params": {"k": k} if k else {},
                "coeff": {"c0": c0, "scale": scale} | ({"p": p} if scale == "power" else {})}
    anchor, reward = term("degree_anchor", 0.375, "one", k=4), term("square_count", -0.31, "inv_sqrt_N")
    assert S.feels_n([anchor], True)["band"] == "none"
    assert S.feels_n([term("degree_anchor", 0.5, "log_N", k=4), term("square_count", -1.0, "log_N")], True)["band"] == "none"
    moving = S.feels_n([anchor, reward], True)
    assert moving["band"] == "x30 to x1,000" and moving["factor"] == 32.0 and moving["knows_n"]
    assert S.feels_n([term("edge_count", 1.0, "log_N")], False)["band"] == "felt at a finite temperature"
    assert S.feels_n([anchor], False)["band"] == "none"
    score = S.space_score({"rungs": [_rung(1024), _rung(4096)]},
                          {"terms": [anchor, reward], "dynamics": {"zero_temperature": True, "beta": 1.0}})
    assert score["facts"]["feels_n"]["band"] == "x30 to x1,000" and score["facts"]["zero_temperature"] is True


def test_the_known_controls_read_as_they_are():
    ladders = {law["law"]: law for law in json.loads((ROOT / "tests" / "fixtures" / "space_score_ladders.json")
                                                     .read_text(encoding="utf-8"))["laws"]}
    for p in ("6f364db7b7", "a283415b10"):
        score = S.space_score(ladders[p]["chains"])
        assert score["stage"] == 2 and score["spaces"] == ["given"] and score["chains"]["given"]["d"] == 2, p
        assert score["chains"]["given"]["worst"] < 1.0, "the torus's four probes agree inside the margin at 4,096"
        assert score["chains"]["empty"]["d"] is None and score["chains"]["empty"]["worst"] > 5, (
            "the chain from empty: its reach barely grows")
        assert score["gaps"][-1]["worst"] == "reach"
    for n in ("e4ed71e5bc", "e06a125bf0"):
        score = S.space_score(ladders[n]["chains"])
        assert score["stage"] == 1 and score["spaces"] == [], n
        assert score["gaps"][0]["distance"] < 1, "the given chain melts toward what the chain from empty makes"
    c1 = S.space_score(ladders["c9b022c38d"]["chains"])
    assert c1["stage"] == 1 and c1["spaces"] == [] and c1["chains"]["given"]["d"] == 3, (
        "the cubic lattice reads three dimensions and does not settle by 4,096")


def test_the_score_is_plain_json_and_says_what_it_is():
    score = S.space_score({"rungs": [_rung(1024), _rung(4096)], "given_start": "the declared answer, family_torus"})
    assert score["contract"] == "gsd-space-score-2" and score["from_n"] == 1024 and score["of"] == 4
    assert score["margins"] == {"dimension": 0.15, "per_node": 0.02, "curvature": 0.02, "piece": 0.02}
    assert score["facts"]["given_start"] == "the declared answer, family_torus"
    json.dumps(score, allow_nan=False)
    empty = S.space_score({"rungs": []})
    assert empty["stage"] == 0 and empty["judged"] == [] and empty["gaps"] == []


def test_a_probe_most_seeds_did_not_read_is_neither_a_dimension_nor_a_difference():
    from_empty, given = _side(4096), _side(4096)
    from_empty["d_B"] = {"mean": 4.0, "seeds": 1, "of": 3}
    given["d_B"] = {"mean": 2.0, "seeds": 3, "of": 3}
    rung = _rung(4096, from_empty=from_empty, given=given)
    assert "d_B" not in S._gap(rung)["quantities"]
    assert S._probe(from_empty["d_B"]) is None and S._probe(given["d_B"]) == 2.0
    from_empty["d_B"]["seeds"] = 2
    assert S._gap(rung)["quantities"]["d_B"] > 1, "read by two of three, it is compared"
