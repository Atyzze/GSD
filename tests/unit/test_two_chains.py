from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.engine import engine
from graph_scale_dynamics.observability.chains_course import (
    COURSE_POINTS, STRUCTURE_POINTS, kept_indexes, seed_chains_course)
from graph_scale_dynamics.observability.space_score import space_score
from graph_scale_dynamics.observability.two_chains import met_from, seed_stop, stopping_numbers, two_chains
from graph_scale_dynamics.scaleflow import engine_door

ROOT = Path(__file__).resolve().parents[2]
N = 64
LAW = {"dsl_version": 1, "init": "empty",
       "dynamics": {"kind": "equilibrium", "beta": 1.0, "sweeps": 400,
                    "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15}},
       "terms": [{"op": "degree_anchor", "params": {"k": 4}, "coeff": {"c0": 1.0, "scale": "one"}}]}


def test_a_real_run_keeps_a_thinned_course_of_both_chains():
    envelope = engine_door.run_simulation(LAW, N, 11, record_points=80)
    course = seed_chains_course(envelope)
    assert course["contract"] == "chains-course-1" and course["n"] == N
    for chain, trajectory in (("empty", CL.trajectory(envelope)),
                              ("given", CL.block(envelope, CL.GIVEN)["trajectory"])):
        kept = course[chain]
        assert kept["points"] == len(trajectory)
        assert 2 <= len(kept["course"]) <= COURSE_POINTS
        first, last = kept["course"][0], kept["course"][-1]
        assert first[0] == trajectory[0]["move"] / N and last[0] == pytest.approx(trajectory[-1]["move"] / N, rel=1e-4)
        assert last[1] == pytest.approx(trajectory[-1]["energy"] / N, rel=1e-5)
        assert last[2] == pytest.approx(trajectory[-1]["mean_degree"], rel=1e-4)
        assert 1 <= len(kept["structure"]) <= STRUCTURE_POINTS, "triangles ride on every twentieth point"
    assert course["given"]["start"] == "erdos_renyi_mean_degree_8"
    assert len(json.dumps(course, separators=(",", ":"))) < 4096


def test_thinning_keeps_both_ends_the_first_descent_and_the_late_approach():
    sweeps, start = [], 0.0
    for chunk in range(7):
        length = 16.0 * 2 ** chunk
        sweeps += [start + length * (i + 1) / 240 for i in range(240)]
        start += length
    sweeps = [0.0] + sweeps
    kept = kept_indexes(sweeps, COURSE_POINTS)
    assert kept[0] == 0 and kept[-1] == len(sweeps) - 1 and len(kept) <= COURSE_POINTS
    assert kept == sorted(set(kept))
    early = [i for i in kept if sweeps[i] <= 0.01 * sweeps[-1]]
    late = [i for i in kept if sweeps[i] >= 0.75 * sweeps[-1]]
    assert len(early) >= 5 and len(late) >= 4, (len(early), len(late))
    assert kept_indexes([3.0, 1.0, 2.0], 2) == [0, 2], "a course that does not rise is thinned by index"


def test_a_skipped_given_chain_has_no_course():
    envelope = engine_door.run_simulation(LAW, N, 3, record_points=40)
    CL.record(envelope, CL.GIVEN).update(skipped=True)
    assert seed_chains_course(envelope)["given"] is None


def test_a_course_that_cannot_be_read_is_recorded_and_never_raised():
    course = seed_chains_course({"n": N, "trajectory": [{"move": 0, "energy": "not a number"}], "sampling_checkpoint": 7})
    assert course["contract"] == "chains-course-1" and course["error"].startswith("AttributeError")
    row = _seed(256, 0)
    row["metrics"]["chains_course"] = course
    out = two_chains([row], policy={})
    assert out["rungs"][0]["per_seed"][0]["course"] is None and out["rungs"][0]["courses"] == 0


def _probe(value=None, *, key=None, withheld=None, refusal=None):
    block = {"valid": value is not None, "refusal": None if value is not None else refusal}
    if value is not None:
        block[key] = value
    if withheld is not None:
        block["would_have_reported"] = withheld
    return block


def _checks(zs, rest=None, *, passes=None):
    rows = []
    for i, z in enumerate(zs):
        cert = {"split": {"energy_per_node_z": z, "mean_degree_z": z / 2}, "effective_samples": 9.0 + i,
                "stationarity_drift": 0.1}
        if rest is not None:
            cert["at_rest"] = {"limit_late_descent_share": 0.01,
                               "chains": {"empty": {"late_descent_share": rest[i][0]},
                                          "given": {"late_descent_share": rest[i][1]}}}
        passed = passes[i] if passes else z <= 3
        rows.append({"multiplier": 2 ** (i + 1), "cumulative_sweeps": 100 * (2 ** (i + 2) - 2), "passed": passed,
                     "failures": [] if passed else [{"code": "STARTS_DISAGREED",
                                                     "detail": "the chain from empty and the given chain disagree"}],
                     "certificate": cert, "mean_degree": 4.0, "wall_seconds_so_far": 10.0 * (i + 1),
                     "termination": "completed", "given_termination": None})
    return rows


def _seed(n, seed, *, given_d_s=None, energies=(-1.0, -0.8), reason="ceiling", zs=(5.0, 4.0), reading="frozen",
          course=True, multiplier=64):
    metrics = {
        "census": {"empty": {"edges": 2 * n, "cliques": {"triangles": n // 8}, "squares": n,
                               "largest_component": {"size": n}},
                   "given": {"edges": 3 * n, "cliques": {"triangles": n // 2}, "squares": 2 * n,
                               "largest_component": {"size": n - 1}}},
        "descent": {"chains": {"empty": {"final_energy": energies[0] * n},
                               "given": {"final_energy": energies[1] * n}}},
        "curvature": {"empty": {"measured": True, "mean": -0.5}, "given": {"measured": True, "mean": 0.0}},
        "half_volume_radius": 6.0 + seed,
        "d_s": _probe(1.7 + 0.01 * seed, key="d_s"),
        "d_V": _probe(withheld=3.0, refusal="EXPONENTIAL_GROWTH"),
        "d_B": _probe(refusal="NOT_POWER_LAW"),
        "d_w": _probe(withheld=1.73, refusal="EXPONENTIAL_GROWTH"),
        "health": {"mean_degree": 4.0, "equilibration": {"sweeps_multiplier": multiplier},
                   "sampling_checkpoints": _checks(list(zs)),
                   "rung_terminal": {"reason": reason, "classification": "METASTABLE_OR_NONMIXING", "chunks": len(zs),
                                     "final_multiplier": multiplier, "wall_seconds": 20.0,
                                     "work": {"units": 100, "budget": 1000},
                                     "failures": [{"code": "STARTS_DISAGREED", "detail": "apart"}]}},
        "meeting_reading": {"reading": reading, "observables": {"energy_per_node": {
            "early_gap": -0.3, "late_gap": -0.2, "late_noise": 0.01, "agree": False, "closing": False}}},
    }
    if given_d_s is not None:
        metrics.setdefault("chain_probes", {})["given"] = {"half_volume_radius": 4.0, "d_s": {"valid": True, "value": given_d_s},
                                  "d_V": {"valid": False, "value": None, "refusal": "EXPONENTIAL_GROWTH"},
                                  "d_B": {"valid": True, "value": 2.0}, "d_w": {"valid": False, "value": None,
                                                                               "refusal": "WALK_SATURATED"}}
    if course:
        metrics["chains_course"] = {
            "contract": "chains-course-1", "n": n,
            "empty": {"points": 400, "course": [[0.0, 1.0, 0.0], [10.0, -0.5, 3.5], [600.0, energies[0], 4.0]],
                        "structure": [[0.0, 0.0, 0.01], [600.0, 0.12, 1.0]]},
            "given": {"points": 140, "course": [[0.0, 0.2, 4.0], [10.0, -0.6, 5.0], [600.0, energies[1], 6.0]],
                     "structure": [[0.0, 0.0, 1.0], [600.0, 0.5, 0.98]],
                     "start": "family_random_geometric_2d_degree_4", "kernel": "local_walk"}}
    return {"n": n, "seed": seed, "metrics": metrics}


def _rows():
    rows = [_seed(256, s, given_d_s=1.1) for s in range(3)]
    rows += [_seed(1024, s, given_d_s=1.2, reason="completed", zs=(5.0, 2.0, 1.0), reading="agreeing",
                   energies=(-1.0, -1.0)) for s in range(3)]
    return rows


def test_both_chains_are_read_alike_per_rung():
    out = two_chains(_rows(), given_start="a shape", policy={})
    assert out["contract"] == "two-chains-1" and [r["n"] for r in out["rungs"]] == [256, 1024]
    rung = out["rungs"][0]
    assert rung["seeds"] == 3
    assert rung["empty"]["mean_degree"]["mean"] == 4.0 and rung["given"]["mean_degree"]["mean"] == 6.0
    assert rung["empty"]["energy_per_node"]["mean"] == -1.0 and rung["given"]["energy_per_node"]["mean"] == -0.8
    assert rung["given"]["triangles_per_node"]["mean"] == 0.5 and rung["empty"]["kappa"]["mean"] == -0.5
    assert rung["empty"]["reach"]["mean"] == 7.0 and rung["empty"]["reach"]["se"] is not None
    assert rung["given"]["reach"]["mean"] == 4.0
    d_s = rung["empty"]["d_s"]
    assert d_s["seeds"] == 3 and d_s["mean"] == pytest.approx(1.71) and "withheld" not in d_s
    d_w = rung["empty"]["d_w"]
    assert d_w["mean"] is None and d_w["withheld"]["mean"] == 1.73 and d_w["withheld"]["reasons"] == {"EXPONENTIAL_GROWTH": 3}
    assert rung["empty"]["d_B"]["refused"] == {"NOT_POWER_LAW": 3} and "withheld" not in rung["empty"]["d_B"]
    assert rung["given"]["d_s"]["mean"] == 1.1 and rung["given"]["d_w"]["refused"] == {"WALK_SATURATED": 3}
    assert out["given_probes_read"] is True
    assert rung["reading"]["reading"] == "frozen" and rung["reading"]["counts"]["frozen"] == 3
    assert rung["lower_energy"] == {"empty": 3} and out["rungs"][1]["lower_energy"] == {"level": 3}
    assert rung["ends"] == {"ceiling": 3} and out["rungs"][1]["ends"] == {"completed": 3}
    seed = rung["per_seed"][0]
    assert seed["course"]["given"]["start"] == "family_random_geometric_2d_degree_4"
    assert [c["sweeps"] for c in seed["checks"]] == [200.0, 600.0]
    assert seed["checks"][0]["z"] == {"energy_per_node": 5.0, "mean_degree": 2.5}
    assert seed["checks"][0]["failures"][0]["code"] == "STARTS_DISAGREED"
    assert seed["met_from"] == {"gap": None, "rest": None}
    assert out["rungs"][1]["per_seed"][0]["met_from"]["gap"] == 600.0, "met at the second check and stayed met"
    assert out["zero_temperature"] is False and out["rule"]["split_z"] == 3.0


def test_a_random_start_given_chain_is_compared_not_read():
    out = two_chains([_seed(256, s) for s in range(2)], policy={})
    assert out["given_probes_read"] is False
    given = out["rungs"][0]["given"]
    assert given["d_s"]["read"] is False and given["d_s"]["mean"] is None and "refused" not in given["d_s"]
    assert given["mean_degree"]["mean"] == 6.0, "the census still reads the given chain"


def test_when_the_check_stayed_met():
    checks = [{"sweeps": 100.0, "z": {"a": 5.0}}, {"sweeps": 300.0, "z": {"a": 2.0}}, {"sweeps": 700.0, "z": {"a": 1.0}}]
    assert met_from(checks, 3.0) == {"gap": 300.0, "rest": None}
    assert met_from(checks + [{"sweeps": 1500.0, "z": {"a": 4.0}}], 3.0)["gap"] is None, "met, then lost"
    rest = [{"sweeps": 100.0, "z": {}, "rest": {"empty": 0.2, "given": 0.001}, "rest_limit": 0.01},
            {"sweeps": 300.0, "z": {}, "rest": {"empty": 0.004, "given": 0.0}, "rest_limit": 0.01}]
    assert met_from(rest, 3.0) == {"gap": None, "rest": 300.0}


def test_how_each_run_stopped_is_carried():
    def stop(terminal):
        return seed_stop({"health": {"rung_terminal": terminal}})
    spent = stop({"reason": "budget", "work": {"units": 990, "budget": 1000}})
    assert (spent["reason"], spent["work_units"], spent["work_budget"]) == ("budget", 990, 1000)
    capped = stop({"reason": "mean_degree_cap", "mean_degree_cap": 8.0, "mean_degree_cap_chain": "given"})
    assert capped["cap_chain"] == "given" and capped["mean_degree_cap"] == 8.0
    rested = stop({"reason": "completed", "classification": "AT_REST",
                   "at_rest": {"pairs": {"empty|given": {"reading": "different_minima"},
                                         "empty|cubic": {"reading": "same_minimum"}}}})
    assert rested["given_rest"] == "different_minima"
    assert stop({})["reason"] is None


def test_a_zero_temperature_law_is_read_by_rest():
    row = _seed(256, 0, reason="completed")
    row["metrics"]["health"]["sampling_checkpoints"] = _checks([40.0, 30.0], rest=[(0.2, 0.0), (0.005, 0.0)],
                                                               passes=[False, True])
    out = two_chains([row], policy={})
    assert out["zero_temperature"] is True
    seed = out["rungs"][0]["per_seed"][0]
    assert seed["checks"][1]["rest"] == {"empty": 0.005, "given": 0.0}
    assert seed["met_from"] == {"gap": None, "rest": 600.0}


def test_the_longest_run_per_seed_counts_and_the_sampler_audit_does_not():
    short, long = _seed(256, 0, multiplier=4, energies=(5.0, 5.0)), _seed(256, 0)
    audit = _seed(256, 1, energies=(9.0, 9.0))
    audit["metrics"]["health"]["sampler"] = {"sampler_audit": True}
    rung = two_chains([short, long, audit], policy={})["rungs"][0]
    assert rung["seeds"] == 1 and rung["empty"]["energy_per_node"]["mean"] == -1.0


def test_the_stopping_numbers_are_the_ones_the_jobs_carry():
    from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
    for spec in ({}, {"policy": {"min_effective_samples": 10, "equilibration_split_z": 2.5,
                                 "stationarity_drift_max": 0.4, "max_sweeps_multiplier": 32},
                      "sampling_contract": {"required_consecutive_passes": 3}},
                 {"policy": {"max_sweeps_multiplier": 32}, "sampling_contract": {"max_sweeps_multiplier": 16}}):
        jobs = one_shot_policy(spec, 64)
        assert stopping_numbers(spec) == {key: jobs[key] for key in stopping_numbers(spec)}


class _Repo:
    def __init__(self, rows):
        self.rows = rows

    def measurements(self, candidate_id, analysis_version, campaign_id):
        return self.rows

    def candidate(self, candidate_id, campaign_id):
        return {"candidate_id": candidate_id}

    def engine_decisions(self, campaign_id, candidate_id):
        return []

    def campaign(self, campaign_id):
        return {"spec": {"policy": {"equilibration_split_z": 2.0}}}


def test_the_structure_route_serves_both_chains():
    from graph_scale_dynamics.services.api import readings_route
    payload = readings_route.structure(_Repo(_rows()), "1", "law")
    chains = payload["chains"]
    assert chains["contract"] == "two-chains-1" and chains["rule"]["split_z"] == 2.0
    assert chains["given_start"] == payload["given_start"]
    assert [r["n"] for r in chains["rungs"]] == [256, 1024]
    score = payload["space_score"]
    assert score["contract"] == "gsd-space-score-2" and score["judged"] == [1024]
    assert score["facts"]["given_start"] == payload["given_start"] and "feels_n" not in score["facts"]
    json.dumps(payload, allow_nan=False)


node = shutil.which("node")


@pytest.mark.skipif(node is None, reason="node is not installed")
def test_the_page_draws_what_the_reader_writes(tmp_path):
    chains = two_chains(_rows(), given_start="the declared answer, family_random_geometric_2d_degree_4", policy={})
    payload = {"chains": chains, "space_score": space_score(chains)}
    path = tmp_path / "chains.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run([node, str(ROOT / "tests/ui/candidate_smoke.js"), str(ROOT / "graph_scale_dynamics/resources/ui")],
                            capture_output=True, text=True, timeout=180,
                            env={**os.environ, "GSD_TWO_CHAINS_PAYLOAD": str(path)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "two chains drawn from the reader's payload" in result.stdout
