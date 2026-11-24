from __future__ import annotations

import copy
import itertools
import json
import math
import random
from collections import Counter
from pathlib import Path

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.engine import engine
from graph_scale_dynamics.observability.meeting_reading import seed_meeting_reading
from graph_scale_dynamics.research.hamiltonian_preflight import equilibrium_identity
from graph_scale_dynamics.services.proposer import blind
from graph_scale_dynamics.services.worker.engine_registry import resolve_engine
from graph_scale_dynamics.scaleflow import engine_door

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.scientific]

REFERENCE_ID = "3ea8aa5f8329147f0dd4fd29bc9cc0eded012c316f4e369770e169798f43cfe5"


def _term(op, c0, scale="one", **params):
    return {"op": op, "params": params, "coeff": {"c0": c0, "scale": scale}}


def _law(terms, mix=(0.45, 0.45, 0.10), sweeps=30, **dynamics):
    return {"dsl_version": 1, "init": "empty", "terms": terms,
            "dynamics": {"kind": "equilibrium", "beta": 1.0,
                         "move_mix": {"add": mix[0], "delete": mix[1], "swap": mix[2]},
                         "sweeps": sweeps, **dynamics}}


def _reference():
    return json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text())


def test_a_law_at_the_default_dynamics_keeps_its_id():
    spec = _reference()
    assert dsl.fingerprint(spec) == REFERENCE_ID
    explicit = copy.deepcopy(spec)
    explicit["dynamics"].update(locality=0.0, local_move="toggle", zero_temperature=False)
    assert dsl.validate(explicit) == []
    assert dsl.fingerprint(explicit) == REFERENCE_ID
    assert set(dsl.normalize(explicit)["dynamics"]) == {"kind", "beta", "move_mix", "sweeps"}


def test_each_setting_is_part_of_the_law():
    base = _law([_term("edge_count", 0.5)])
    ids = {dsl.fingerprint(base)}
    for settings in ({"locality": 0.5}, {"zero_temperature": True}, {"locality": 0.99, "zero_temperature": True}):
        spec = _law([_term("edge_count", 0.5)], **settings)
        assert dsl.validate(spec) == []
        ids.add(dsl.fingerprint(spec))
    assert len(ids) == 4
    toggled = _law([_term("edge_count", 0.5)], locality=0.5, local_move="toggle")
    assert dsl.validate(toggled) == [] and dsl.fingerprint(toggled) == dsl.fingerprint(
        _law([_term("edge_count", 0.5)], locality=0.5))


@pytest.mark.parametrize("settings,problem", [
    ({"locality": 1.0}, "locality"), ({"locality": -0.1}, "locality"), ({"locality": True}, "locality"),
    ({"locality": 0.9999999999999}, "locality"),
    ({"local_move": "rewire", "locality": 0.5}, "local_move"),
    ({"local_move": "add_only", "locality": 0.5}, "must be one of toggle"),
    ({"local_move": "add_only"}, "must be one of toggle"),
    ({"local_move": ["toggle"], "locality": 0.5}, "local_move"),
    ({"zero_temperature": 1}, "zero_temperature"),
])
def test_a_setting_outside_its_range_is_refused(settings, problem):
    problems = dsl.validate(_law([_term("edge_count", 0.5)], **settings))
    assert any(problem in p for p in problems), problems


def test_the_regime_is_derived_never_chosen():
    assert dsl.dynamics_regime(_reference()) == "equilibrium"
    assert dsl.dynamics_regime(_law([], locality=0.5)) == "equilibrium"
    assert dsl.dynamics_regime(_law([], locality=0.5, zero_temperature=True)) == "zero_temperature"
    assert dsl.dynamics_regime(_law([], zero_temperature=True)) == "zero_temperature"
    assert dsl.DYNAMICS_REGIMES == ("equilibrium", "zero_temperature")


def test_the_proposer_keeps_two_laws_that_differ_only_in_dynamics():
    terms = [_term("edge_count", 0.5), _term("degree_square_sum", 0.1)]
    physical = {equilibrium_identity(_law(terms))[0], equilibrium_identity(_law(terms, locality=0.5))[0],
                equilibrium_identity(_law(terms, zero_temperature=True))[0]}
    assert len(physical) == 3
    hot, cold = _law(terms, zero_temperature=True), _law(terms, zero_temperature=True)
    cold["dynamics"]["beta"] = 7.0
    assert equilibrium_identity(hot)[0] == equilibrium_identity(cold)[0]
    plain = _law(terms)
    assert equilibrium_identity(plain)[0] == equilibrium_identity(dict(plain, dynamics=dict(
        plain["dynamics"], locality=0.0, zero_temperature=False)))[0]


def test_a_checkpoint_does_not_continue_under_other_dynamics():
    spec = _law([_term("edge_count", 0.3), _term("triangle_count", -0.2)], sweeps=6)
    cp = engine_door.run_simulation(spec, 48, 1)["sampling_checkpoint"]
    with pytest.raises(ValueError, match="fingerprint"):
        engine_door.run_simulation(_law(spec["terms"], sweeps=6, locality=0.5), 48, 1, target_sweeps=12,
                              resume_checkpoint=cp)


def test_a_law_with_its_own_locality_refuses_a_sampler_audit():
    with pytest.raises(ValueError, match="locality"):
        engine_door.run_simulation(_law([_term("edge_count", 0.5)], locality=0.5), 32, 1, proposal_locality=0.3)


def _exact_edge_count_marginal(n: int, c_edge: float, c_triangle: float) -> dict[int, float]:
    pairs = list(itertools.combinations(range(n), 2))
    weights: Counter = Counter()
    for mask in range(1 << len(pairs)):
        edges = {pairs[i] for i in range(len(pairs)) if mask >> i & 1}
        triangles = sum(1 for a, b, c in itertools.combinations(range(n), 3)
                        if (a, b) in edges and (a, c) in edges and (b, c) in edges)
        weights[len(edges)] += math.exp(-(c_edge * len(edges) + c_triangle * triangles))
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}


def test_the_local_toggle_samples_the_boltzmann_measure_and_not_the_one_at_twice_its_energy():
    _, run_rs, _ = resolve_engine({"engine": "rust"})
    exact = _exact_edge_count_marginal(5, 0.3, -0.8)
    draws = 2000
    distance = {}
    for beta in (1.0, 2.0):
        spec = _law([_term("edge_count", 0.3), _term("triangle_count", -0.8)], sweeps=40, locality=0.7)
        spec["dynamics"]["beta"] = beta
        seen = Counter(CL.record(run_rs(spec, 5, seed, record_points=2), CL.FROM_EMPTY)["final"]["edge_count"]
                       for seed in range(draws))
        distance[beta] = 0.5 * sum(abs(seen[k] / draws - exact.get(k, 0.0)) for k in set(seen) | set(exact))
    assert distance[1.0] < 0.045, distance
    assert distance[2.0] > 0.25, distance


@pytest.mark.parametrize("engine_name", ["python", "rust"])
def test_a_law_that_names_the_move_taken_out_is_refused_by_the_engine(engine_name):
    _, run, _ = resolve_engine({"engine": engine_name})
    driven = _law([_term("edge_count", 0.3), _term("triangle_count", -0.8)], locality=0.7)
    driven["dynamics"]["local_move"] = "add_only"
    with pytest.raises(ValueError, match="must be one of toggle"):
        run(driven, 16, 1, record_points=2)


def test_zero_temperature_never_raises_the_energy_and_draws_nothing_to_decide():
    spec = _law([_term("edge_count", -1.0), _term("degree_square_sum", 0.13)], mix=(0.5, 0.5, 0.0),
                sweeps=60, zero_temperature=True, locality=0.9)
    env = engine_door.run_simulation(spec, 64, 3)
    energies = [row["energy"] for row in CL.trajectory(env)]
    assert all(b <= a + 1e-9 for a, b in zip(energies, energies[1:], strict=False))
    assert env["proposal_model"]["acceptance_rule"] == "zero_temperature_accept_if_energy_does_not_rise"
    assert env["proposal_model"]["dynamics_regime"] == "zero_temperature"


def test_a_zero_temperature_law_comes_to_rest_where_its_start_led_it():
    _, run_rs, _ = resolve_engine({"engine": "rust"})
    terms = [_term("edge_count", 0.5), _term("triangle_count", -2.0)]
    for seed in (1, 2):
        env = run_rs(_law(terms, mix=(0.5, 0.5, 0.0), sweeps=40, locality=0.5, zero_temperature=True), 64, seed)
        reading = seed_meeting_reading(env)
        assert reading["reading"] == "frozen", reading
        assert reading["frozen"] == ["empty"]
        assert CL.record(env, CL.FROM_EMPTY)["final"]["edge_count"] == 0
        assert CL.block(env, CL.GIVEN)["trajectory"][-1]["mean_degree"] > 20
        hot = run_rs(_law(terms, mix=(0.5, 0.5, 0.0), sweeps=40, locality=0.5), 64, seed)
        assert seed_meeting_reading(hot)["reading"] != "frozen"


DYNAMIC_GRID = {"localities": {"min": 0.0, "max": 0.99}, "local_moves": ["toggle"],
                "zero_temperature": [False, True]}


def test_a_grid_without_dynamics_draws_no_extra_numbers():
    rng = random.Random(4)
    before = rng.getstate()
    assert blind.draw_dynamics(rng, dict(blind.DEFAULT_GRID)) == {}
    assert rng.getstate() == before


def test_a_grid_with_dynamics_draws_every_regime_and_only_valid_laws():
    assert blind.validate_grid(dict(blind.DEFAULT_GRID, **DYNAMIC_GRID)) == []
    rng = random.Random(3)
    laws = [blind.blind_law(rng, sorted(dsl.OPERATORS), DYNAMIC_GRID, complexity_budget=6) for _ in range(300)]
    assert all(dsl.validate(dsl.normalize(law)) == [] for law in laws)
    regimes = Counter(dsl.dynamics_regime(law) for law in laws)
    assert set(regimes) == {"equilibrium", "zero_temperature"}, regimes
    assert blind.is_continuous(DYNAMIC_GRID)


@pytest.mark.parametrize("grid,problem", [
    ({"localities": {"min": 0.2, "max": 1.0}}, "localities"),
    ({"localities": [0.5, 1.2]}, "localities"),
    ({"localities": {"min": 0.0, "max": 0.9, "spacing": "log"}}, "localities"),
    ({"local_moves": ["toggle", "rewire"]}, "local_moves"),
    ({"local_moves": ["toggle", "add_only"]}, "local_moves"),
    ({"local_moves": []}, "local_moves"),
    ({"zero_temperature": [0, 1]}, "zero_temperature"),
])
def test_a_dynamics_grid_outside_its_range_is_refused(grid, problem):
    problems = blind.validate_grid(dict(blind.DEFAULT_GRID, **grid))
    assert any(problem in p for p in problems), problems


def test_a_clone_names_what_it_changed_about_the_dynamics():
    from graph_scale_dynamics.operations.campaign_control import grid_diff
    diff = grid_diff({}, DYNAMIC_GRID)
    assert "localities none to 0..0.99" in diff["summary"]
    assert "zero_temperature none to false/true" in diff["summary"]


def test_a_swap_share_is_drawn_per_law_and_the_rest_split_evenly():
    grid = {"swap_shares": {"min": 0.0, "max": 0.99}}
    assert blind.validate_grid(dict(blind.DEFAULT_GRID, **grid)) == []
    rng = random.Random(8)
    laws = [dsl.normalize(blind.blind_law(rng, sorted(dsl.OPERATORS), grid, complexity_budget=6))
            for _ in range(200)]
    assert all(dsl.validate(law) == [] for law in laws)
    swaps = [law["dynamics"]["move_mix"]["swap"] for law in laws]
    assert min(swaps) < 0.1 and max(swaps) > 0.85
    assert all(law["dynamics"]["move_mix"]["add"] == law["dynamics"]["move_mix"]["delete"] for law in laws)
    pinned = blind.blind_law(random.Random(1), ["edge_count", "degree_square_sum"], {"swap_shares": [0]})
    assert pinned["dynamics"]["move_mix"] == {"add": 0.5, "delete": 0.5, "swap": 0.0}


@pytest.mark.parametrize("entry", [[1.0], [-0.1], {"min": 0.5, "max": 1.0}, []])
def test_a_swap_share_outside_0_to_1_is_refused(entry):
    problems = blind.validate_grid(dict(blind.DEFAULT_GRID, swap_shares=entry))
    assert any("swap_shares" in p for p in problems), problems


def test_the_swap_share_is_part_of_what_the_proposer_keeps_apart():
    terms = [_term("edge_count", -1.0), _term("degree_square_sum", 0.1)]
    carried = equilibrium_identity(_law(terms, mix=(0.425, 0.425, 0.15)))[0]
    plain = equilibrium_identity(_law(terms, mix=(0.45, 0.45, 0.10)))[0]
    none = equilibrium_identity(_law(terms, mix=(0.5, 0.5, 0.0)))[0]
    assert len({carried, plain, none}) == 3
    assert "dynamics" not in json.dumps(equilibrium_identity(_law(terms, mix=(0.425, 0.425, 0.15)))[2])


def test_with_only_edge_and_degree_terms_zero_temperature_rests_without_swaps_and_not_with_them():
    _, run_rs, _ = resolve_engine({"engine": "rust"})
    terms = [_term("edge_count", -1.0), _term("degree_square_sum", 0.13)]
    still = run_rs(_law(terms, mix=(0.5, 0.5, 0.0), sweeps=400, locality=0.9, zero_temperature=True), 64, 1)
    moving = run_rs(_law(terms, mix=(0.45, 0.45, 0.10), sweeps=400, locality=0.9, zero_temperature=True), 64, 1)
    rest = seed_meeting_reading(still)["activity_per_node"]
    busy = seed_meeting_reading(moving)["activity_per_node"]
    assert rest["empty"] < 0.05, rest
    assert busy["empty"] > 0.5, busy


def _shipped_grid() -> dict:
    spec = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
    return spec["search_policy"]["grid"], spec


def test_the_default_campaign_draws_every_axis_uniformly_from_its_whole_range():
    grid, spec = _shipped_grid()
    for key in ("magnitudes", "betas", "power_exponents", "anchor_k", "localities", "swap_shares"):
        assert blind.interval_of(grid[key]) is not None, key
    assert grid["scales"] == ["one", "power", "log_N", "inv_log_N"]
    assert grid["local_moves"] == ["toggle"] and grid["zero_temperature"] == [False, True]
    assert grid["signs"] == [-1, 1]
    assert blind.validate_grid(dict(blind.DEFAULT_GRID, **grid)) == []
    assert blind.is_continuous(grid)
    rng = random.Random(5)
    laws = [blind.blind_law(rng, spec["operator_whitelist"], grid, complexity_budget=spec["complexity_budget"])
            for _ in range(400)]
    records = [dsl.dynamics_record(dsl.normalize(law)) for law in laws]
    assert {r["regime"] for r in records} == {"equilibrium", "zero_temperature"}
    localities = [r["locality"] for r in records]
    assert sum(1 for x in localities if x == 0.0) <= 2
    assert min(localities) < 0.05 and max(localities) > 0.94
    assert sum(1 for r in records if r["zero_temperature"]) in range(160, 241)


def test_every_law_stores_each_axis_a_report_will_split_by():
    default = dsl.dynamics_record(dsl.normalize(_reference()))
    assert default == {"regime": "equilibrium", "locality": 0.0, "local_move": "toggle",
                       "zero_temperature": False, "beta": 1.0, "swap_share": 0.0,
                       "move_mix": {"add": 0.5, "delete": 0.5, "swap": 0.0}}
    law = dsl.normalize(_law([_term("edge_count", 0.5)], mix=(0.5, 0.5, 0.0), locality=0.3,
                             local_move="toggle", zero_temperature=True))
    record = dsl.dynamics_record(law)
    assert (record["regime"], record["locality"], record["local_move"], record["zero_temperature"],
            record["swap_share"], record["beta"]) == ("zero_temperature", 0.3, "toggle", True, 0.0, 1.0)
