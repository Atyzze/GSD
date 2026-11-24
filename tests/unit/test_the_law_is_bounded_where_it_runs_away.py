from __future__ import annotations

import ast
import itertools
import json
import math
import random
from pathlib import Path

import pytest

from graph_scale_dynamics.dsl.dsl import OPERATORS
from graph_scale_dynamics.engine.engine import configuration_energy
from graph_scale_dynamics.research import runaway_energy as R
from graph_scale_dynamics.services.proposer import blind

ANCHORED = [op for op in OPERATORS if "k" in OPERATORS[op]["params"]]
ROOT = Path(__file__).resolve().parents[2]


def _term(op: str, params: dict | None = None, c0: float = 1.0, scale: str = "one") -> dict:
    return {"op": op, "params": dict(params or {}), "coeff": {"c0": c0, "scale": scale}}


def _law(*terms) -> dict:
    return {"dsl_version": 1, "init": "empty", "terms": [_term(*term) for term in terms],
            "dynamics": {"kind": "equilibrium", "beta": 1.0,
                         "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15}, "sweeps": 30}}


def _cases():
    for op in OPERATORS:
        for k in ((1, 2, 3, 5) if op in ANCHORED else (None,)):
            yield op, ({"k": k} if k is not None else {})


def _relative(law, n, edges) -> float:
    return configuration_energy(law, n, edges) - configuration_energy(law, n, [])


@pytest.mark.parametrize("op,params", list(_cases()), ids=[f"{op}{params}" for op, params in _cases()])
def test_each_closed_form_is_the_engine_s_energy_on_a_built_star_and_clique(op, params):
    law = _law((op, params))
    for d in range(1, 9):
        assert _relative(law, d + 3, [(0, i) for i in range(1, d + 1)]) == R.star_energy(op, params, d), (op, d)
    for m in range(2, 9):
        edges = list(itertools.combinations(range(m), 2))
        assert _relative(law, m + 2, edges) == R.clique_energy(op, params, m), (op, m)
        assert _relative(law, m + 2, edges[::-1]) == R.clique_energy(op, params, m), (op, m, "reversed")


def _girth_six(d: int) -> tuple[int, list[tuple[int, int]]]:
    if d == 2:
        return 8, [(i, (i + 1) % 8) for i in range(8)]
    q = d - 1
    points = sorted({tuple(x * pow(next(v for v in p if v), -1, q) % q for x in p)
                     for p in itertools.product(range(q), repeat=3) if any(p)})
    edges = [(i, len(points) + j) for i, a in enumerate(points) for j, b in enumerate(points)
             if sum(x * y for x, y in zip(a, b, strict=True)) % q == 0]
    return 2 * len(points), edges


@pytest.mark.parametrize("op,params", list(_cases()), ids=[f"{op}{params}" for op, params in _cases()])
def test_each_closed_form_is_the_engine_s_energy_on_a_built_regular_graph(op, params):
    law = _law((op, params))
    for d in (2, 3, 4, 6):
        n, edges = _girth_six(d)
        degrees = [0] * n
        for u, v in edges:
            degrees[u] += 1
            degrees[v] += 1
        assert set(degrees) == {d}
        assert _relative(law, n, edges) == n * R.regular_energy(op, params, d), (op, d)


@pytest.mark.parametrize("op,params", list(_cases()), ids=[f"{op}{params}" for op, params in _cases()])
def test_each_polynomial_reproduces_its_closed_form_past_k(op, params):
    k = int(params.get("k", 0))
    for shape in R.SHAPES:
        coefficients = R.polynomial(shape, op, params)
        for size in range(k + 2, k + 30):
            assert sum(c * size ** p for p, c in enumerate(coefficients)) == R.energy(shape, op, params, size)


def test_the_leading_powers_are_the_review_s():
    lead = {(shape, op): max((p for p, c in enumerate(R.polynomial(shape, op, {"k": 4})) if c and p), default=0)
            for shape in R.SHAPES for op in OPERATORS}
    assert lead[(R.STAR, "degree_neighbor_gradient")] == 3 and lead[(R.STAR, "degree_fourth_sum")] == 4
    assert lead[(R.CLIQUE, "square_edge_overlap")] == 6 and lead[(R.CLIQUE, "degree_fourth_sum")] == 5
    assert R.polynomial(R.CLIQUE, "square_edge_overlap")[6] == pytest.approx(0.25)
    assert lead[(R.STAR, "degree_anchor_abs")] == 0, "an absolute anchor does not stop a star: its energy stays put"
    assert lead[(R.STAR, "ollivier_curvature")] == 0, "a star's edges close no cycle: curvature 0"
    assert lead[(R.CLIQUE, "ollivier_curvature")] == 4
    assert R.polynomial(R.REGULAR, "ollivier_curvature")[3] == -1, "-2 d (d - 2) an edge, d / 2 edges a node"
    for op in OPERATORS:
        if op != "ollivier_curvature":
            assert lead[(R.REGULAR, op)] <= max(lead[(R.STAR, op)], lead[(R.CLIQUE, op)]), op


def _runs_away(*terms, ladder=R.DEFAULT_LADDER):
    found = R.runaway([_term(*term) for term in terms], ladder)
    return None if found is None else (found["shape"], found["power"])


def test_it_reads_what_the_629_rule_does_not():
    quartic = ("degree_fourth_sum", {}, 0.5)
    square = ("degree_square_sum", {}, 1.0)
    assert _runs_away(square, ("degree_cube_sum", {}, -0.2)) == (R.STAR, 3)
    assert _runs_away(square, ("degree_neighbor_gradient", {}, -0.1)) == (R.STAR, 3)
    assert _runs_away(("degree_cube_sum", {}, 0.05), ("degree_neighbor_gradient", {}, -0.1)) == (R.STAR, 3)
    assert _runs_away(quartic, ("degree_neighbor_gradient", {}, -0.1)) is None
    assert _runs_away(quartic, ("square_edge_overlap", {}, -0.05)) == (R.CLIQUE, 6)
    assert _runs_away(("degree_fourth_sum", {}, 2.0, "log_N"), ("square_edge_overlap", {}, -0.05, "inv_N")) == \
        (R.CLIQUE, 6)
    assert _runs_away(("degree_square_sum", {}, 1.0), ("square_count", {}, -0.5)) == (R.CLIQUE, 4)
    assert _runs_away(("degree_square_sum", {}, -1.0), ("degree_cube_sum", {}, 0.1)) is None
    assert _runs_away(("degree_square_sum", {}, -1.0, "log_N"), ("degree_fourth_sum", {}, 0.1, "inv_N")) is None


def test_a_positive_curvature_runs_away_on_a_regular_graph():
    curvature = ("ollivier_curvature", {}, 0.113)
    assert _runs_away(("degree_square_sum", {}, 1.5, "inv_log_N"), curvature) == (R.REGULAR, 3)
    assert _runs_away(("degree_fourth_sum", {}, 0.05), curvature) is None
    assert _runs_away(("degree_cube_sum", {}, 0.5), curvature) is None, "a larger cube holds it"
    assert _runs_away(("degree_anchor", {"k": 4}, 0.5), ("ollivier_curvature", {}, -0.25)) == (R.CLIQUE, 4)


def test_it_is_read_at_every_rung_because_a_multiplier_moves_the_leader():
    terms = [_term("degree_cube_sum", {}, 50.0, "inv_log_N"), _term("degree_neighbor_gradient", {}, -5.0)]
    assert R.runaway(terms, [64]) is None, "at 64 the cube holds: 50 / ln 64 = 12 > 5"
    found = R.runaway(terms)
    assert found is not None and found["shape"] == R.STAR and found["power"] == 3
    assert found["n"] == next(n for n in R.DEFAULT_LADDER if 50.0 / math.log(n) < 5.0) == 65536


def test_an_energy_that_stays_put_is_not_falling():
    assert R.leading([_term("degree_anchor_abs", {"k": 9}, 3.0)], 4096, R.STAR) == (0, 0.0)
    assert _runs_away(("degree_anchor_abs", {"k": 4}, 1.0, "log_N"), ("edge_count", {}, -0.5)) == (R.STAR, 1)


def test_terms_that_cancel_exactly_are_read_as_cancelled():
    terms = [_term("degree_square_sum", {}, 0.3), _term("wedge_count", {}, -0.6)]
    power, value = R.leading(terms, 1024, R.STAR)
    assert power == 1 and value > 0


def test_the_631_sampler_refuses_exactly_what_629_refused():
    survey = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json")
                        .read_text(encoding="utf-8"))
    grid = dict(blind.DEFAULT_GRID, **survey["search_policy"]["grid"])
    rng = random.Random(631)
    differs = 0
    for _ in range(6000):
        terms = [blind._draw_term(rng, rng.choice(survey["operator_whitelist"]), grid)
                 for _ in range(rng.choice([1, 2, 3, 4]))]
        law = {"terms": terms, "dynamics": {"beta": 1.0}}
        old = blind.validity_problem(law, complexity_budget=7)
        assert blind.validity_problem(law, complexity_budget=7, sampler=blind.SAMPLER_631) == old, terms
        if old is None or old == "unbounded_below":
            differs += (old == "unbounded_below") == (R.runaway(terms) is None)
    assert differs > 100


def test_nothing_in_the_sampler_reads_the_runaway():
    for name in ("blind.py", "main.py"):
        tree = ast.parse((ROOT / "graph_scale_dynamics" / "services" / "proposer" / name).read_text(encoding="utf-8"))
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        names = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                 for alias in node.names}
        assert "graph_scale_dynamics.research.runaway_energy" not in modules and "runaway" not in names, name


def test_a_reading_costs_closed_forms_not_graph_builds(monkeypatch):
    import graph_scale_dynamics.engine.engine as engine
    monkeypatch.setattr(engine, "GraphState", None)
    monkeypatch.setattr(engine, "configuration_energy", None)
    terms = [_term(op, {"k": 4} if op in ANCHORED else {}, 0.5, "log_N") for op in OPERATORS]
    assert R.runaway(terms) is None
