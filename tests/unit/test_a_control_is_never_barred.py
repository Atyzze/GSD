from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.decisions import depth as D
from graph_scale_dynamics.decisions.engine import RUN_NEXT, STOP, Policy, Rung, decide, policy_fingerprint
from graph_scale_dynamics.operations import standing_controls as SC

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())


def _rung(n, d_s=2.0, *, small_world=0.67):
    return Rung(n=n, mean_degree=4.0, connected_fraction=1.0, probes={"d_s": (d_s, 0.05)}, seeds_measured=3,
                measured_se={"d_s": 0.02}, small_world_fraction=small_world, valid_fractions={"d_s": 1.0, "d_V": 1.0})


RUNGS = [_rung(64), _rung(256), _rung(1024), _rung(4096, 2.10), _rung(16384, 2.04), _rung(65536, 2.01)]


def _control_policy() -> Policy:
    criterion = SC.load_criterion()
    spec = SC.exempt_from_the_bar(SC.campaign_spec(criterion))
    return Policy.from_spec(spec)


def test_a_survey_law_is_barred_and_a_control_law_is_not():
    survey = Policy.from_spec(SPEC)
    barred = decide("law", RUNGS, survey)
    assert (barred.action, barred.rule) == (STOP, D.NOT_PROMISING)
    control = _control_policy()
    assert control.promising_bar is False and control.depth_rules == survey.depth_rules
    exempt = D.bar("law", barred.__class__(law="law", action=RUN_NEXT, rule="d_s_settled", reason="settled",
                                           at_n=65536, next_n=262144, priority=1), RUNGS, control)
    assert (exempt.action, exempt.rule, exempt.next_n) == (RUN_NEXT, "d_s_settled", 262144)
    assert control.salt_share("no_finite_dimension", 65536) > 0.0, "nor the bar's other half, the salt's zero"
    assert survey.salt_share("no_finite_dimension", 65536) == 0.0


def test_a_campaign_that_declares_nothing_keeps_the_bar_and_its_fingerprint():
    before = SC.campaign_spec(SC.load_criterion())
    assert "promising_bar" not in before["engine"]["policy"]
    policy = Policy.from_spec(before)
    assert policy.promising_bar is True
    assert policy_fingerprint(policy) == policy_fingerprint(Policy.from_spec(json.loads(json.dumps(before))))
    exempt = _control_policy()
    assert policy_fingerprint(exempt) != policy_fingerprint(policy), "an exempt campaign says so in its fingerprint"


def test_every_control_campaign_made_from_637_is_exempt(monkeypatch):
    from graph_scale_dynamics.operations import campaign_control as control
    made = []

    class Repo:
        def all_campaigns(self):
            return [{"campaign_id": "1", "spec": {"description": "base 4 quadrant"}}]

        def candidates(self, _cid):
            return []

        def insert_candidate(self, *args):
            pass

    monkeypatch.setattr(control, "create_campaign", lambda _repo, spec, **_: made.append(spec) or {"campaign_id": "9"})
    monkeypatch.setattr(SC, "a_study_s_folder", lambda _repo: True)
    result = SC.ensure(Repo(), say=lambda *_: None)
    assert result["created"] == "9" and made[0]["engine"]["policy"]["promising_bar"] is False
