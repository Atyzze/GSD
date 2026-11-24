from __future__ import annotations

from graph_scale_dynamics.reporting.chains_meeting_report import chains_meeting


def _check(sweeps, z, passed=None, rest=None):
    certificate = {"split": {"energy_per_node_z": z, "mean_degree_z": z / 2}}
    if rest is not None:
        certificate["at_rest"] = {"limit_late_descent_share": 0.01,
                                  "chains": {"empty": {"late_descent_share": rest[0]},
                                             "given": {"late_descent_share": rest[1]}}}
    return {"cumulative_sweeps": sweeps, "multiplier": sweeps // 100, "passed": z <= 3 if passed is None else passed,
            "certificate": certificate}


def _row(law, n, seed, checks, reading="agreeing", reason="completed", multiplier=8, audit=False):
    health = {"sampling_checkpoints": checks, "rung_terminal": {"reason": reason},
              "equilibration": {"sweeps_multiplier": multiplier}}
    if audit:
        health["sampler"] = {"sampler_audit": True}
    return {"candidate_id": law, "n": n, "seed": seed,
            "metrics": {"health": health, "meeting_reading": {"reading": reading}}}


def test_when_the_chains_met_per_rung_and_how_many_never_did():
    rows = [
        _row("a", 1024, 0, [_check(200, 9), _check(400, 2), _check(800, 1)]),
        _row("a", 1024, 1, [_check(200, 2), _check(400, 5), _check(800, 2), _check(1600, 1)]),
        _row("b", 1024, 0, [_check(200, 40), _check(400, 30)], reading="disagreeing_while_moving", reason="ceiling"),
        _row("b", 1024, 0, [_check(100, 50)], reading="disagreeing_while_moving", multiplier=1),
        _row("a", 4096, 0, [_check(400, 1)]),
        _row("c", 1024, 0, [_check(200, 1)], audit=True),
    ]
    section = chains_meeting(rows)
    first = section["rungs"][0]
    assert first["n"] == 1024 and first["seeds"] == 3 and first["laws"] == 2
    assert first["readings"] == {"agreeing": 2, "disagreeing_while_moving": 1}
    assert first["ends"] == {"completed": 2, "ceiling": 1}
    finite = first["finite"]
    assert (finite["seeds"], finite["met"], finite["never"]) == (3, 2, 1)
    assert finite["sweeps"]["median"] == 600 and finite["sweeps"]["max"] == 800
    assert finite["share_of_the_run"]["median"] == 0.5
    assert "zero_temperature" not in first
    assert section["rungs"][1]["n"] == 4096 and section["rungs"][1]["finite"]["sweeps"]["median"] == 400


def test_a_zero_temperature_seed_is_read_at_rest_not_by_its_given_chains_gap():
    rows = [_row("z", 4096, 0, [_check(300, 50, passed=False, rest=(0.2, 0.001)), _check(600, 80, passed=True, rest=(0.004, 0.0)),
                                _check(1200, 90, passed=True, rest=(0.002, 0.0))], reading="frozen")]
    rung = chains_meeting(rows)["rungs"][0]
    assert "finite" not in rung
    cold = rung["zero_temperature"]
    assert (cold["seeds"], cold["met"], cold["never"]) == (1, 1, 0)
    assert cold["sweeps"]["median"] == 600 and cold["share_of_the_run"]["median"] == 0.5


def test_no_checks_no_rungs_and_the_record_carries_the_section():
    assert chains_meeting([])["rungs"] == []
    assert chains_meeting([{"candidate_id": "x", "n": 64, "seed": 0, "metrics": {}}])["rungs"] == []
    from graph_scale_dynamics.research.record_report import build_record_sections
    sections = build_record_sections({}, [_row("a", 256, 0, [_check(100, 1)])])
    assert sections["chains_meeting"]["rungs"][0]["finite"]["met"] == 1
