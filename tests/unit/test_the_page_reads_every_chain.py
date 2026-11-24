from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from graph_scale_dynamics.observability import space_score as SS
from graph_scale_dynamics.observability import two_chains as TC
from graph_scale_dynamics.observability.chain_mixing import rung_mixing, seed_chain_moments
from graph_scale_dynamics.observability.chains_course import seed_chains_course
from graph_scale_dynamics.observability.meeting_reading import seed_more_meeting_readings, seed_meeting_reading

GIVEN = ["square", "cubic", "tesseract"]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def five_chains():
    from graph_scale_dynamics.dsl.dsl import fingerprint
    from graph_scale_dynamics.scaleflow.one_shot import analyze_one_shot_envelope, run_one_shot
    from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import study_design as SD
    from tests.unit.test_a_designed_study_runs_its_starts import LAW, ROOT
    from tests.support import designs
    design = designs.of_four_starts()
    design.pop("starts_reading")
    spec = SD.campaign_spec(design, control.shipped_spec(), design["campaigns"][0], 0)
    policy = dict(one_shot_policy(spec, 64, fingerprint(LAW), LAW), max_sweeps_multiplier=2)
    rows = []
    for seed in range(3):
        envelope = run_one_shot(LAW, 64, seed, one_shot=policy, record_points=40)
        metrics, _ = analyze_one_shot_envelope(envelope, seed=seed)
        metrics["chain_mixing"] = seed_chain_moments(envelope)
        metrics["meeting_reading"] = seed_meeting_reading(envelope, metrics.get("census"))
        metrics["more_meeting_readings"] = seed_more_meeting_readings(envelope, metrics.get("census"))
        metrics["chains_course"] = seed_chains_course(envelope)
        rows.append({"n": 64, "seed": seed, "metrics": json.loads(json.dumps(metrics, default=str))})
    return spec, rows


def test_the_analysis_keeps_every_given_chain_s_meeting_and_moments(five_chains):
    _, rows = five_chains
    for row in rows:
        metrics = row["metrics"]
        assert set(metrics["more_meeting_readings"]) == set(GIVEN)
        for reading in metrics["more_meeting_readings"].values():
            assert reading["contract"] == "meeting-reading-2" and reading["reading"]
        assert set(GIVEN) < set(metrics["chain_mixing"]), "every chain's moments under its own name"
    mixing = rung_mixing([row["metrics"] for row in rows])
    every = mixing["every_chain"]
    assert every["given_chains"] == sorted(GIVEN) and set(every["meeting_readings"]) == set(GIVEN)
    for observable in ("energy_per_node", "mean_degree"):
        assert every["observables"][observable]["half_chains"] == 5 * 3 * 2, "every chain of every seed, halved"
    assert set(every["chain_seconds"]) == set(GIVEN) and all(v > 0 for v in every["chain_seconds"].values())


def test_a_run_with_one_given_chain_records_what_it_always_did():
    envelope = {"n": 8, "trajectory": [], "sampling_checkpoint": {"given": {"trajectory": []}}}
    assert seed_more_meeting_readings(envelope) is None
    assert "more_given" not in seed_chain_moments(envelope)
    assert "every_chain" not in rung_mixing([{"chain_mixing": seed_chain_moments(envelope)}])


def test_the_page_reads_every_chain_by_its_start_s_name(five_chains):
    spec, rows = five_chains
    starts = [dict(s) for s in spec["sampling_contract"]["given_starts"]]
    chains = TC.two_chains(rows, given_start="the random start", starts=starts)
    assert [c["name"] for c in chains["every_chain"]] == ["empty", "random", *GIVEN]
    assert [c["key"] for c in chains["every_chain"]] == ["empty", "given", *GIVEN]
    assert chains["every_chain"][3]["start"] == "periodic_cubic_quotient"
    rung = chains["rungs"][0]
    assert set(rung["more_given"]) == set(GIVEN) and set(rung["more_readings"]) == set(GIVEN)
    for name in GIVEN:
        block = rung["more_given"][name]
        assert block["mean_degree"]["seeds"] == 3 and block["energy_per_node"]["seeds"] == 3
        assert block["kappa"]["seeds"] == 3 and block["d_s"]["read"]
        assert chains["more_probes_read"][name]
    for seed in rung["per_seed"]:
        assert set(seed["more_meetings"]) == set(GIVEN)
        assert all(m["lower_energy"] in ("empty", "level", name) for name, m in seed["more_meetings"].items())
        names = ["empty", "given", *GIVEN]
        assert not any(check.get("more_z") for check in seed["checks"]), "no pair but the twin starts is compared"
        assert all(set(check["chains"]) == set(names) for check in seed["checks"]), "every chain's own count"
    assert rung["given"]["d_s"]["read"] and rung["given"]["mean_degree"]["seeds"] == 3


def test_the_score_reads_each_given_chain_and_asks_every_given_chain_to_meet_the_chain_from_empty(five_chains):
    spec, rows = five_chains
    chains = TC.two_chains(rows, starts=spec["sampling_contract"]["given_starts"])
    score = SS.space_score(chains)
    assert set(score["chains"]) == {"empty", "given", *GIVEN} and set(score["more_gaps"]) == set(GIVEN)


def _rung(n, from_empty, given, more=None):
    def side(d):
        return {key: {"mean": d, "se": 0.01} for key in ("d_s", "d_V", "d_B")} | {
            "d_w": {"mean": 2.0}, "mean_degree": {"mean": 6.0}, "giant_fraction": {"mean": 1.0},
            "reach": {"mean": (n ** (1 / 3)) if d == 3.0 else n ** 0.1}}
    rung = {"n": n, "seeds": 3, "ends": {"completed": 3}, "empty": side(from_empty), "given": side(given)}
    if more:
        rung["more_given"] = {name: side(d) for name, d in more.items()}
    return rung


def test_a_lattice_chain_that_is_a_space_passes_stage_two_and_one_apart_stops_the_meeting():
    rungs = [_rung(n, 1.3, 1.3, {"cubic": 3.0}) for n in (1024, 4096, 16384)]
    chains = {"rungs": rungs, "every_chain": [{"key": "empty"}, {"key": "given"}, {"key": "cubic"}]}
    score = SS.space_score(chains)
    assert score["spaces"] == ["cubic"] and score["stages"][1]["passed"]
    assert not score["stages"][3]["passed"], "the cubic chain is far from the chain from empty"
    one = SS.space_score({"rungs": [_rung(n, 1.3, 1.3) for n in (1024, 4096, 16384)]})
    assert "more_gaps" not in one and one["spaces"] == [] and set(one["chains"]) == {"empty", "given"}


def test_a_name_the_payload_uses_is_never_a_given_chain_s():
    assert TC.more_given_names([{"name": "random"}, {"name": "given"}, {"name": "cubic"}], []) == ["cubic"]
    assert TC.more_given_names(None, [{"census": {"more_given": {"b": {}, "a": {}}}}]) == ["a", "b"]


def test_the_route_names_every_start_and_the_first_by_the_law_s_own_degree(five_chains):
    from graph_scale_dynamics.services.api import readings_route
    from tests.unit.test_a_designed_study_runs_its_starts import LAW
    spec, rows = five_chains

    class Repo:
        def measurements(self, law, version, campaign_id):
            return rows

        def candidate(self, candidate_id, campaign_id):
            return {"spec": LAW}

        def campaign(self, campaign_id):
            return {"spec": spec}

        def engine_decisions(self, campaign_id, law):
            return []

    payload = readings_route.structure(Repo(), "1", "law")
    assert payload["given_start"].startswith("the random start, random_mean_degree_")
    every = payload["chains"]["every_chain"]
    assert [c["name"] for c in every] == ["empty", "random", *GIVEN]
    assert every[1]["start"].startswith("random_mean_degree_"), "the random start at the law's own degree"
    assert set(payload["space_score"]["more_gaps"]) == set(GIVEN)
    five = payload["starts_reading"]
    assert [c["name"] for c in five["chains"]] == ["empty", "random", *GIVEN]
    assert [c["lattice"] for c in five["chains"]] == [None, None, 2, 3, 4]
    assert five["class"] == "not_read" and five["rungs"] == []
    json.dumps(payload, allow_nan=False)


node = shutil.which("node")


@pytest.mark.skipif(node is None, reason="node is not installed")
def test_the_page_draws_every_chain_the_reader_writes(five_chains, tmp_path):
    spec, rows = five_chains
    chains = TC.two_chains(rows, given_start="the random start", starts=spec["sampling_contract"]["given_starts"])
    path = tmp_path / "chains.json"
    from graph_scale_dynamics.observability.starts_reading import law_reading
    path.write_text(json.dumps({"chains": chains, "space_score": SS.space_score(chains),
                                "starts_reading": law_reading(chains, spec["sampling_contract"]["given_starts"])}),
                    encoding="utf-8")
    result = subprocess.run([node, str(ROOT / "tests/ui/candidate_smoke.js"), str(ROOT / "graph_scale_dynamics/resources/ui")],
                            capture_output=True, text=True, timeout=180,
                            env={**os.environ, "GSD_TWO_CHAINS_PAYLOAD": str(path)})
    assert result.returncode == 0 and "two chains drawn from the reader's payload" in result.stdout, result.stdout


def test_report_28_counts_every_given_chain_s_meeting_and_the_given_chains_at_the_cap(five_chains):
    from graph_scale_dynamics.reporting.chains_meeting_report import chains_meeting
    _, rows = five_chains
    measurements = [dict(row, candidate_id="law") for row in rows]
    rung = chains_meeting(measurements)["rungs"][0]
    assert set(rung["more_readings"]) == set(GIVEN)
    assert all(sum(counts.values()) == 3 for counts in rung["more_readings"].values())
    one = [dict(row, candidate_id="law", metrics={k: v for k, v in row["metrics"].items()
                                                   if k not in ("more_meeting_readings", "given_ended_at_cap")})
           for row in rows]
    assert "more_readings" not in chains_meeting(one)["rungs"][0], "a law with one given chain is counted as it was"
