from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.engine import engine as E
from graph_scale_dynamics.measurements import random_starts
from graph_scale_dynamics.measurements.calibration import control_family_edges
from graph_scale_dynamics.scaleflow import equilibration as eq
from graph_scale_dynamics.scaleflow.one_shot import analyze_one_shot_envelope, run_one_shot
from graph_scale_dynamics.scheduling.job_creation import (one_shot_policy, resolve_given_start, given_starts)
from graph_scale_dynamics.scaleflow import engine_door

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
LAW = json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text())
LAW_ID = "c" * 64
STARTS = [{"name": "random", "family": "random_at_drawn_degree"},
          {"name": "honeycomb", "family": "periodic_honeycomb_lattice"},
          {"name": "cubic", "family": "periodic_cubic_quotient"},
          {"name": "tesseract", "family": "periodic_tesseract_quotient"}]


def _campaign(starts=None, **sampling):
    spec = copy.deepcopy(CAMPAIGN)
    spec["sampling_contract"] = dict(spec.get("sampling_contract") or {}, **sampling)
    for key in ("given_start", "given_start_by_law", "given_start_rule"):
        if key not in sampling:
            spec["sampling_contract"].pop(key, None)
    if starts is not None:
        spec["sampling_contract"]["given_starts"] = starts
    return spec


def _term(op, c0, scale="one", **params):
    return {"op": op, "params": params, "coeff": {"c0": c0, "scale": scale}}


def _law(terms, sweeps=6, **dynamics):
    return {"dsl_version": 1, "init": "empty", "terms": terms,
            "dynamics": {"kind": "equilibrium", "beta": 1.0, "move_mix": {"add": 0.45, "delete": 0.45, "swap": 0.1},
                         "sweeps": sweeps, **dynamics}}


SPARSE = _law([_term("edge_count", 0.3), _term("degree_anchor", 0.3, k=4)])


def _declared(n, seed, families, *, edges=True):
    out = [{"name": name, "family": family, **({"edges": control_family_edges(family, n, seed=seed)} if edges else {})}
           for name, family in families]
    return out


def test_a_campaign_s_given_chains_are_resolved_for_each_law_in_its_order():
    spec = _campaign(STARTS)
    starts = given_starts(spec, 256, LAW_ID, LAW)
    assert [start["name"] for start in starts] == ["random", "honeycomb", "cubic", "tesseract"]
    degree = random_starts.drawn_degree(LAW_ID, "random", 16.0)
    assert starts[0] == {"name": "random", "family": random_starts.family(degree), "n": 256}
    assert starts[1:] == [{"name": "honeycomb", "family": "periodic_honeycomb_lattice", "n": 256},
                          {"name": "cubic", "family": "periodic_cubic_quotient", "n": 256},
                          {"name": "tesseract", "family": "periodic_tesseract_quotient", "n": 256}]
    assert resolve_given_start(spec, 256, LAW_ID, LAW) == starts[0], "the first given chain is the law's given chain"
    assert given_starts(spec, 64, LAW_ID)[0] == dict(starts[0], n=64), "the same degree at every N"
    policy = one_shot_policy(spec, 256, LAW_ID, LAW)
    assert policy["given_start"] == starts[0] and policy["more_given"] == starts[1:]
    assert "given_capped_alone" not in policy, "since 781 every chain ends alone at the cap, so no job says so"


def test_a_campaign_that_lists_no_given_chains_makes_the_policy_it_always_made():
    policy = one_shot_policy(_campaign(), 256, LAW_ID, LAW)
    assert "more_given" not in policy and "given_capped_alone" not in policy
    assert given_starts(_campaign(), 256, LAW_ID) is None
    one = one_shot_policy(_campaign([STARTS[1]]), 256, LAW_ID, LAW)
    assert one["more_given"] == [] and one["given_start"]["family"] == "periodic_honeycomb_lattice", \
        "one given chain listed: the law's given chain from that start, under the same rule at the cap"


@pytest.mark.parametrize("starts, sampling, why", [
    ([], {}, "one start or more"),
    ([STARTS[1], dict(STARTS[2], name="honeycomb")], {}, "both named"),
    ([dict(STARTS[1], name="given")], {}, "lower case"),
    ([dict(STARTS[1], name="Honeycomb")], {}, "lower case"),
    ([dict(STARTS[1], name="a:b")], {}, "lower case"),
    ([dict(STARTS[1], family="periodic_square_lattice_typo")], {}, "cannot be built"),
    ([dict(STARTS[1], kernel="teleport")], {}, "kernel"),
    (STARTS, {"given_start": {"family": "periodic_square_lattice"}}, "one way"),
])
def test_a_list_of_starts_that_cannot_be_run_is_refused_at_creation(starts, sampling, why):
    with pytest.raises(ValueError, match=why):
        given_starts(_campaign(starts, **sampling), 256, LAW_ID, LAW)


def test_a_start_must_be_its_lattice_at_exactly_the_rung_s_n():
    with pytest.raises(ValueError, match="near-miss"):
        given_starts(_campaign(STARTS), 1000, LAW_ID, LAW)


def test_a_drawn_degree_needs_the_law_s_id():
    with pytest.raises(ValueError, match="law's id"):
        given_starts(_campaign(STARTS), 256)


LATTICES = [("honeycomb", "periodic_honeycomb_lattice"), ("cubic", "periodic_cubic_quotient"),
            ("tesseract", "periodic_tesseract_quotient")]


def _first(n, seed, degree=5.0, *, edges=True):
    family = random_starts.family(degree)
    return {"family": family, **({"edges": control_family_edges(family, n, seed=seed)} if edges else {})}


def test_given_chains_past_the_first_move_neither_the_chain_from_empty_nor_the_first_given_chain():
    alone = engine_door.run_simulation(SPARSE, 64, 2, target_sweeps=6, given_start=_first(64, 2))
    beside = engine_door.run_simulation(SPARSE, 64, 2, target_sweeps=6, given_start=_first(64, 2),
                              more_given=_declared(64, 2, LATTICES))
    names = ["empty", "given", *(name for name, _family in LATTICES)]
    assert [row["start"] for row in beside["chains"]] == names and [row["start"] for row in alone["chains"]] == names[:2]
    assert beside["termination"] == alone["termination"]
    for name in names[:2]:
        assert {**CL.record(beside, name), "seconds": 0} == {**CL.record(alone, name), "seconds": 0}, name
        assert CL.block(beside, name) == CL.block(alone, name), name
    assert beside["trajectory_diagnostics"] == alone["trajectory_diagnostics"]
    assert len({row["stream"] for row in beside["chains"]}) == len(names), "a stream each"


def test_each_given_starts_from_its_lattice_and_is_summarised_as_the_first():
    envelope = engine_door.run_simulation(SPARSE, 64, 2, target_sweeps=6, given_start=_first(64, 2),
                                more_given=_declared(64, 2, LATTICES))
    for name, family in LATTICES:
        given = CL.record(envelope, name)
        assert given["init"] == f"family_{family}" and set(given) == set(CL.record(envelope, CL.GIVEN))
        block = CL.block(envelope, name)
        assert block["init"] == f"family_{family}" and block["final_structure"] == given["final_structure"]
        assert abs(block["trajectory"][0]["edges"] - len(control_family_edges(family, 64))) <= 1, \
            "it began at its lattice"


def test_a_given_chain_that_names_the_local_walk_moves_by_it():
    walking = [dict(start, kernel="local_walk") for start in _declared(64, 2, LATTICES[:1])]
    envelope = engine_door.run_simulation(SPARSE, 64, 2, target_sweeps=4, given_start=_first(64, 2), more_given=walking)
    assert CL.record(envelope, "honeycomb")["kernel"] == "local_walk"
    assert CL.block(envelope, "honeycomb")["kernel"] == "local_walk"


def test_the_engine_refuses_given_chains_it_cannot_tell_apart_or_start():
    with pytest.raises(ValueError, match="name of its own"):
        engine_door.run_simulation(SPARSE, 64, 2, target_sweeps=2, given_start=_first(64, 2),
                         more_given=_declared(64, 2, LATTICES[:1]) * 2)
    with pytest.raises(ValueError, match="carries no edges"):
        engine_door.run_simulation(SPARSE, 64, 2, target_sweeps=2, given_start=_first(64, 2),
                         more_given=_declared(64, 2, LATTICES[:1], edges=False))


DENSE = _law([_term("edge_count", -0.5), _term("triangle_count", -0.2)])


def test_every_chain_at_the_cap_ends_alone_and_the_chunk_ends_when_both_twins_have():
    first = _first(64, 3, degree=5.0)
    more = _declared(64, 3, [("dense", random_starts.family(7.9)), ("tesseract", "periodic_tesseract_quotient")])
    chunk = engine_door.run_simulation(SPARSE, 64, 3, target_sweeps=4, given_start=first, more_given=more,
                                       mean_degree_cap=6.0)
    assert chunk["termination"]["reason"] == "completed", "a lattice or a further chain at the cap ends no chunk"
    assert {name: CL.block(chunk, name)["ended"]["reason"] for name in ("dense", "tesseract")} == {
        "dense": "mean_degree_cap", "tesseract": "mean_degree_cap"}
    assert not CL.block(chunk, CL.FROM_EMPTY).get("ended") and not CL.block(chunk, CL.GIVEN).get("ended")
    checkpoint = json.loads(json.dumps(chunk["sampling_checkpoint"], default=list))
    going = [{"name": start["name"], "family": start["family"]} for start in more]
    later = engine_door.run_simulation(SPARSE, 64, 3, target_sweeps=8, resume_checkpoint=checkpoint,
                                       given_start={"family": first["family"]}, more_given=going, mean_degree_cap=6.0)
    assert later["sampling_checkpoint"]["chains"][2:] == checkpoint["chains"][2:], "carried as it stood"
    assert {name: CL.timing(later)["chain_seconds"][name] for name in ("dense", "tesseract")} == {
        "dense": 0.0, "tesseract": 0.0}
    both = engine_door.run_simulation(DENSE, 64, 3, target_sweeps=12, given_start=_first(64, 3, degree=7.5),
                                      more_given=more, mean_degree_cap=8.0)
    assert [CL.block(both, name)["ended"]["reason"] for name in CL.twin_names(both)] == ["mean_degree_cap"] * 2
    assert both["termination"]["reason"] == "mean_degree_cap" and both["termination"]["chain"] == CL.GIVEN, (
        "the rung's cap is the second twin's to cross; the chain from empty's alone ends nothing")
    assert all(CL.record(both, name)["skipped"] for name in ("dense", "tesseract")), "the rest is carried"


def test_the_twin_starts_are_the_chain_from_empty_and_the_random_start_s():
    from graph_scale_dynamics.measurements import starts as S
    assert [start.name for start in S.the_twin_starts()] == ["empty", "random"]
    random_first = engine_door.run_simulation(SPARSE, 64, 2, target_sweeps=2, given_start=_first(64, 2),
                                              more_given=_declared(64, 2, LATTICES[:1]))
    assert CL.twin_names(random_first) == ["empty", "given"]
    undeclared = engine_door.run_simulation(SPARSE, 64, 2, target_sweeps=2)
    assert CL.twin_names(undeclared) == ["empty", "given"], "a first given chain from no declared start is random"
    lattice_first = engine_door.run_simulation(SPARSE, 64, 2, target_sweeps=2,
                                               given_start=_declared(64, 2, LATTICES[1:2])[0])
    assert CL.twin_names(lattice_first) == ["empty"], "a lattice is no twin start, first or not"


POLICY = one_shot_policy(_campaign())


def _health(excluded=None, more=None):
    more, excluded = dict(more or {}), dict(excluded or {})
    decide = [name for name in ("empty", "given", *more) if name not in excluded]
    own = {name: {"effective_samples": 50.0, "stationarity": {"normalized_drift": 0.01}} for name in decide}
    base = {"chains": ["empty", "given"], "split": {"energy_per_node_z": 0.5, "mean_degree_z": 0.4},
            "structural_split": {"connected_fraction": 0.0}, "structural_noise": None}
    meet = ["empty", "given"] if "empty" in decide and "given" in decide else []
    pairs = {"empty|given": base} if meet else {}
    cert = {"decide": decide, "meet": meet, "twin_chains": ["empty", "given"], "chains": own, "pairs": pairs,
            "left_out": excluded, "effective_samples": 50.0,
            "split": base["split"], "structural_split": base["structural_split"], "structural_noise": None}
    still = {"connected_fraction": {"drifting": False}, "component_count_per_node": {"drifting": False}}
    return {"numerics_ok": True, "regime": None, "equilibration": cert,
            "stationarity": {"normalized_drift": 0.01}, "structural_trend": {"chains": {"empty": still}}}


def test_only_the_twin_starts_meet_and_every_chain_that_ran_decides_by_its_own_count():
    envelope = engine_door.run_simulation(SPARSE, 64, 2, target_sweeps=6, given_start=_first(64, 2),
                                          more_given=_declared(64, 2, LATTICES))
    cert = eq.inline_health(envelope, POLICY)["equilibration"]
    assert cert["decide"] == ["empty", "given", "honeycomb", "cubic", "tesseract"] and cert["left_out"] == {}
    assert cert["meet"] == ["empty", "given"] and set(cert["pairs"]) == {"empty|given"}, "no lattice chain meets"
    assert set(cert["chains"]) == set(cert["decide"])
    health = _health(excluded={}, more={"cubic": {}})
    health["equilibration"]["chains"]["cubic"] = {"effective_samples": 2.0, "stationarity": {"normalized_drift": 9.0}}
    passed, failures = eq.certificate_pass(POLICY, health)
    assert not passed and [f["detail"] for f in failures] == [
        "the cubic chain's effective samples 2 < 8",
        "persistent late energy drift in the cubic chain: 9 of its own errors"], (
        "a lattice chain's own certificate holds the chunk back")
    health = _health(excluded={}, more={"cubic": {}})
    health["equilibration"]["pairs"]["empty|given"]["split"] = {"energy_per_node_z": 9.0}
    passed, failures = eq.certificate_pass(POLICY, health)
    assert not passed and failures == [{"code": eq.CERT_SPLIT_DISAGREED,
                                        "detail": "the chain from empty and the given chain disagree"}]


@pytest.mark.parametrize("ended, going_on", [("given", "the chain from empty"), ("empty", "the given chain")])
def test_at_a_finite_temperature_either_twin_alone_at_the_cap_is_a_disagreement(ended, going_on):
    health = _health(excluded={ended: eq.ENDED_AT_CAP}, more={})
    health["equilibration"]["split"] = {"energy_per_node_z": 1e9}
    assert not health["equilibration"]["pairs"]
    passed, failures = eq.certificate_pass(POLICY, health)
    words = "the chain from empty" if ended == "empty" else "the given chain"
    assert [f["detail"] for f in failures] == [f"{words} ended at the mean-degree cap and {going_on} did not"], (
        "the twins are equal at the cap: either one alone is the twins apart, its split not read")
    assert eq.terminal_at_ceiling(health, failures) == eq.METASTABLE_OR_NONMIXING


def test_a_lattice_chain_at_the_cap_holds_nothing_back():
    assert eq.certificate_pass(POLICY, _health(excluded={"honeycomb": eq.ENDED_AT_CAP}, more={})) == (True, [])


ZERO_T = _law([_term("edge_count", -0.5), _term("degree_anchor", 0.3, k=3)], sweeps=12, zero_temperature=True)


def test_at_zero_temperature_every_chain_must_rest_and_where_the_twins_rest_is_read():
    envelope = engine_door.run_simulation(ZERO_T, 64, 4, target_sweeps=24, given_start=_first(64, 4),
                                          more_given=_declared(64, 4, LATTICES))
    rest = eq.rest_reading(envelope)
    assert sorted(rest["chains"]) == ["cubic", "empty", "given", "honeycomb", "tesseract"]
    health = eq.inline_health(envelope, POLICY)
    assert health["equilibration"]["decide"] == ["empty", "given", "honeycomb", "cubic", "tesseract"]
    assert set(health["equilibration"]["pairs"]) == {"empty|given"} and health["equilibration"]["left_out"] == {}
    passed, failures = eq.certificate_pass(POLICY, health)
    assert passed == all(row["at_rest"] for row in rest["chains"].values()), failures
    if all(rest["chains"][name]["at_rest"] for name in ("empty", "given")):
        assert set(rest["pairs"]) == {"empty|given"}, "only the twins' minima are read against each other"
    ended = copy.deepcopy(envelope)
    CL.block(ended, "cubic")["ended"] = {"reason": "mean_degree_cap"}
    rest = eq.rest_reading(ended)
    assert "cubic" not in rest["chains"] and rest["left_out"] == {"cubic": eq.ENDED_AT_CAP}
    empty_at_cap = copy.deepcopy(envelope)
    CL.block(empty_at_cap, "empty")["ended"] = {"reason": "mean_degree_cap"}
    health = eq.inline_health(empty_at_cap, POLICY)
    assert "empty" not in health["equilibration"]["decide"] and not eq.twins_apart_at_the_cap({})
    assert all(f["code"] in (eq.CERT_NOT_AT_REST, eq.CERT_REST_MISSING) for f in eq.certificate_pass(POLICY, health)[1]), (
        "at zero temperature a twin at the cap is no disagreement: where each rests is the finding")


def _policy(**overrides):
    policy = one_shot_policy(_campaign(STARTS), 64, LAW_ID, SPARSE)
    return dict(policy, **{"work_budget": 10 ** 15, "max_sweeps_multiplier": 2, **overrides})


def test_a_run_from_a_list_of_starts_records_every_given_chain_and_reads_every_one():
    envelope = run_one_shot(SPARSE, 64, 1, one_shot=_policy(), record_points=40)
    terminal = envelope["rung_terminal"]
    names = ["empty", "given", "honeycomb", "cubic", "tesseract"]
    assert [given["name"] for given in terminal["given_chains"]] == ["random", "honeycomb", "cubic", "tesseract"]
    assert list(terminal["timing"]["chain_seconds"]) == names, "every chain's time by its name"
    certificate = envelope["sampling_checkpoints"][-1]["certificate"]
    assert certificate["decide"] == names and certificate["left_out"] == {} and certificate["meet"] == names[:2]
    assert set(certificate["chains"]) == set(certificate["decide"]), "every chain counts its own samples"
    assert certificate["asked"]["effective_samples"] == _policy()["min_effective_samples"]
    metrics, curves = analyze_one_shot_envelope(envelope, seed=1)
    assert list(metrics["census"]) == names and list(metrics["curvature"]) == names
    assert list(metrics["move_accounting"]) == names and list(metrics["descent"]["chains"]) == names
    assert list(metrics["chain_probes"]) == names[1:], "every chain but the chain from empty, read at the top"
    for name in names[1:]:
        read = metrics["chain_probes"][name]
        assert {"d_s_shape", "d_s_whole_range", "log_diameter", "half_volume_radius"} <= set(read), name
        assert read["log_diameter_flag"] == read["log_diameter"]["flag"], name
    assert "d_s_shape" in metrics and "d_s_whole_range" in metrics, "and the chain from empty's, as before"
    _every_chain_s_curves_are_kept_and_read_again(metrics, curves)


def _every_chain_s_curves_are_kept_and_read_again(metrics: dict, curves: dict) -> None:
    from graph_scale_dynamics.measurements import estimators
    kept = curves["chains"]
    assert set(kept) == {CL.GIVEN, "honeycomb", "cubic", "tesseract"}
    assert [c["move"] for c in curves["configurations"]] == ["final"], "the chain from empty is read at its end too"
    for name, chain in kept.items():
        read = metrics["chain_probes"][name]
        assert {"return_probability", "volume_growth"} <= set(chain), name
        stored = json.loads(json.dumps(chain))
        again = {"d_s": estimators.fit_ds(stored["return_probability"], read["component"]),
                 "d_V": estimators.fit_dh(stored["volume_growth"], read["component"])}
        for probe, key in (("d_s", "d_s"), ("d_V", "d_V_window")):
            assert bool(again[probe].get("valid")) == read[probe]["valid"], (name, probe)
            if read[probe]["valid"]:
                assert again[probe][key] == pytest.approx(read[probe]["value"], abs=1e-9), (name, probe)


def test_a_given_chain_at_the_cap_does_not_end_the_run_and_is_not_read():
    policy = _policy(mean_degree_cap=6.0)
    policy["given_start"] = {"name": "random", "family": random_starts.family(6.4), "n": 64}
    envelope = run_one_shot(SPARSE, 64, 1, one_shot=policy, record_points=40)
    terminal = envelope["rung_terminal"]
    assert terminal["reason"] != "mean_degree_cap" and terminal["given_chains"][0]["ended_at_cap"]
    ended = {given["name"] for given in terminal["given_chains"] if given["ended_at_cap"]}
    assert {"random", "tesseract"} <= ended, "the 4D lattice starts at 8 links a node, over the cap of 6"
    assert "honeycomb" not in ended, "the honeycomb's 3 a node did not reach the cap under this law"
    metrics, _ = analyze_one_shot_envelope(envelope, seed=1)
    assert "given" not in metrics["chain_probes"]
    assert metrics["ended_at_cap"] == sorted(name.replace("random", "given") for name in ended)
    assert set(metrics["chain_probes"]) == {"honeycomb", "cubic", "tesseract"} - ended


def test_with_or_without_a_list_a_twin_alone_at_the_cap_ends_alone_and_the_twins_are_apart():
    policy = dict(one_shot_policy(_campaign()), work_budget=10 ** 15, max_sweeps_multiplier=2,
                  mean_degree_cap=6.0, given_start={"family": random_starts.family(6.4), "n": 64})
    envelope = run_one_shot(SPARSE, 64, 1, one_shot=policy, record_points=40)
    terminal = envelope["rung_terminal"]
    assert terminal["reason"] != "mean_degree_cap" and CL.block(envelope, CL.GIVEN)["ended"], (
        "the random start's chain alone at the cap ends alone, as the chain from empty's would")
    assert "the given chain ended at the mean-degree cap and the chain from empty did not" in [
        f["detail"] for f in terminal["failures"]]
    metrics, _ = analyze_one_shot_envelope(envelope, seed=1)
    assert metrics["ended_at_cap"] == ["given"] and "limit_refusal" not in metrics
    assert metrics["d_s"].get("refusal") != eq.MEAN_DEGREE_CAP_TERMINAL, "the chain from empty is read"


def test_the_chain_from_empty_alone_at_the_cap_is_not_read_and_the_others_are():
    envelope = run_one_shot(SPARSE, 64, 1, one_shot=_policy(), record_points=40)
    CL.block(envelope, CL.FROM_EMPTY)["ended"] = {"reason": "mean_degree_cap", "at_move": 10, "at_sweep": 0}
    metrics, _ = analyze_one_shot_envelope(envelope, seed=1)
    assert metrics["ended_at_cap"] == ["empty"] and "limit_refusal" not in metrics
    assert {metrics[p]["refusal"] for p in ("d_s", "d_V", "d_B", "d_w")} == {eq.MEAN_DEGREE_CAP_TERMINAL}
    assert set(metrics["chain_probes"]) == {"given", "honeycomb", "cubic", "tesseract"}
    assert metrics["curvature"]["empty"]["measured"] is False


def test_the_budget_counts_the_work_of_every_chain_of_the_seed():
    envelope = run_one_shot(SPARSE, 64, 1, one_shot=_policy(), record_points=40,
                            simulate=engine_door.run_simulation)
    accounting = CL.move_accounting(envelope)
    assert len(accounting) == len(CL.ran_names(envelope)) > 2, "every chain from every start is counted"
    weights = _policy()["work_unit"]["weights"]
    assert envelope["rung_terminal"]["work"]["units"] == sum(
        weights[name] * block["parts"][name] for block in accounting.values() for name in weights)
