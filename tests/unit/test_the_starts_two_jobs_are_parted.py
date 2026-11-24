from __future__ import annotations

import copy

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.engine import engine as E
from graph_scale_dynamics.scaleflow import equilibration as eq
from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
from tests.unit.test_a_law_runs_from_a_list_of_starts import (LAW_ID, POLICY, SPARSE, STARTS, ZERO_T, _campaign,
                                                               _declared, _first, _health)
from graph_scale_dynamics.scaleflow import engine_door

LATTICES = [(s["name"], s["family"]) for s in STARTS[1:]]
APART = {"split": {"energy_per_node_z": 9.0}, "structural_split": {"connected_fraction": 0.9}}
MEASURED = dict(POLICY, lattice_chains_meet=False)


def test_only_a_spec_that_parts_the_two_jobs_puts_it_on_the_job():
    meet = one_shot_policy(_campaign(STARTS), 64, LAW_ID, SPARSE)
    assert "lattice_chains_meet" not in meet, "a study that does not say carries the policy its jobs always carried"
    parted = one_shot_policy(_campaign(STARTS, lattice_chains_meet=False), 64, LAW_ID, SPARSE)
    assert parted["lattice_chains_meet"] is False and parted["more_given"] == meet["more_given"]
    assert "lattice_chains_meet" not in one_shot_policy(_campaign(None, lattice_chains_meet=False), 64, LAW_ID, SPARSE), (
        "a campaign with no list of starts has no lattice chains to part")


def test_a_lattice_chain_never_meets_and_its_own_certificate_decides_whatever_the_spec_says():
    for policy in (POLICY, MEASURED):
        passed, failures = eq.certificate_pass(policy, _health(excluded={}, more={"cubic": APART}))
        assert passed and failures == [], "a lattice chain apart from the twins holds nothing back: it need meet none"
        health = _health(excluded={}, more={"cubic": {}})
        health["equilibration"]["chains"]["cubic"] = {"effective_samples": 2.0, "stationarity": {"normalized_drift": 9.0}}
        assert {f["code"] for f in eq.certificate_pass(policy, health)[1]} == {eq.CERT_ESS_LOW, eq.CERT_DRIFT}, (
            "no chain is measured only since 781: every chain that ran decides by its own certificate")
    assert eq.certificate_pass(MEASURED, _health(excluded={"square": eq.ENDED_AT_CAP}, more={})) == (True, []), (
        "a lattice chain at the cap holds nothing against it")


def test_the_twin_starts_still_meet():
    health = _health(excluded={}, more={"cubic": {}})
    health["equilibration"]["pairs"]["empty|given"]["split"] = {"energy_per_node_z": 9.0}
    passed, failures = eq.certificate_pass(MEASURED, health)
    assert not passed and failures[0]["detail"] == "the chain from empty and the given chain disagree"


def test_a_run_s_lattice_chains_rest_and_trend_on_their_own_and_meet_no_other():
    envelope = engine_door.run_simulation(ZERO_T, 64, 4, target_sweeps=24, given_start=_first(64, 4),
                                          more_given=_declared(64, 4, LATTICES))
    lattices = {n for n, _f in LATTICES}
    for policy in (None, MEASURED):
        assert eq.left_out_chains(envelope) == {}
        rest = eq.rest_reading(envelope, policy)
        assert set(rest["chains"]) == {"empty", "given", *lattices} and "left_out" not in rest
        health = eq.inline_health(envelope, policy)
        cert = health["equilibration"]
        assert cert["decide"] == ["empty", "given", *(n for n, _f in LATTICES)] and cert["meet"] == ["empty", "given"]
        assert set(cert["pairs"]) == {"empty|given"} and set(cert["chains"]) == {"empty", "given", *lattices}
        assert cert["left_out"] == {} and cert["twin_chains"] == ["empty", "given"]
        trend = eq.structural_trend(envelope, policy)
        assert set(trend["chains"]) == {"empty", "given", *lattices}
        assert set(trend["pooled"]) == {"empty|given", *lattices}, "the twins pooled as they meet, each lattice alone"
    ended = copy.deepcopy(envelope)
    CL.block(ended, "cubic")["ended"] = {"reason": "mean_degree_cap"}
    assert eq.left_out_chains(ended)["cubic"] == eq.ENDED_AT_CAP


def test_the_rules_fingerprint_covers_a_new_study_s_deciding_spec_and_leaves_one_that_does_not_say_as_it_was():
    from graph_scale_dynamics.decisions.engine import Policy, first_multipliers_of, policy_fingerprint
    old = _campaign(STARTS)
    assert Policy.from_spec(old).spec_decides == ""
    plain = Policy(first_multipliers=first_multipliers_of(old))
    assert policy_fingerprint(Policy.from_spec(old)) == policy_fingerprint(plain), (
        "a campaign whose spec does not say what decides keeps the plain policy's fingerprint, its first multipliers "
        "being its own ladder's")
    new = _campaign(STARTS, hold_structure=True, lattice_chains_meet=False)
    print_one = policy_fingerprint(Policy.from_spec(new))
    assert print_one != policy_fingerprint(Policy.from_spec(old))
    stricter = copy.deepcopy(new)
    stricter["policy"] = dict(stricter.get("policy") or {}, min_effective_samples=16)
    assert policy_fingerprint(Policy.from_spec(stricter)) != print_one, "the certificate's settings decide"
    fewer = copy.deepcopy(new)
    fewer["sampling_contract"]["given_starts"] = STARTS[:2]
    assert policy_fingerprint(Policy.from_spec(fewer)) != print_one, "the starts decide"


def test_a_design_that_says_how_its_starts_are_read_puts_it_on_every_campaign_s_spec():
    import hashlib
    import json
    from pathlib import Path

    from graph_scale_dynamics.observability.starts_reading import hold_structure
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.scheduling.provenance import freeze_campaign_spec
    path = Path(__file__).resolve().parents[2] / "tests/fixtures/a_design_of_four_starts.json"
    raw = path.read_bytes()
    design = dict(json.loads(raw), sha256=hashlib.sha256(raw).hexdigest(), path=str(path.name))
    design.pop("starts_reading")
    shipped = freeze_campaign_spec(control.shipped_spec())
    unsaid = SD.campaign_spec(design, shipped, design["campaigns"][0], 0)
    assert not set(SD.STARTS_READING_KEYS) & set(unsaid["sampling_contract"]), "a design that does not say"
    assert not hold_structure(unsaid)
    parted = dict(design, starts_reading={"hold_structure": True, "lattice_chains_meet": False})
    spec = SD.campaign_spec(parted, shipped, parted["campaigns"][0], 0)
    assert spec["sampling_contract"]["hold_structure"] is True and spec["sampling_contract"]["lattice_chains_meet"] is False
    assert hold_structure(spec) and spec["sampling_contract"]["given_starts"] == unsaid["sampling_contract"]["given_starts"]
    policy = one_shot_policy(spec, 4096, LAW_ID, SPARSE)
    assert policy["lattice_chains_meet"] is False
