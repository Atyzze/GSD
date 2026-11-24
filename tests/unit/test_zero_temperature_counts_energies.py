from __future__ import annotations

import json
import random
from pathlib import Path

from graph_scale_dynamics.research import law_identity as LI
from graph_scale_dynamics.research.hamiltonian_preflight import (
    PREFLIGHT_VERSION, ZERO_TEMPERATURE_FOLDED, equilibrium_identity,
)
from graph_scale_dynamics.services.proposer import blind

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json")
                    .read_text(encoding="utf-8"))
HAND = dict(SURVEY, search_policy={"contract": "gsd-hand-1", "kind": "hand"})


def _law(terms, *, zero=True, beta=3.0):
    return {"dsl_version": 1, "init": "empty",
            "terms": [{"op": op, "params": params, "coeff": coeff} for op, params, coeff in terms],
            "dynamics": {"kind": "equilibrium", "beta": beta, "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15},
                         "sweeps": 30, **({"zero_temperature": True} if zero else {})}}


def _id(law, version=ZERO_TEMPERATURE_FOLDED) -> str:
    return equilibrium_identity(law, version=version)[0]


SQUARE = ("degree_square_sum", {}, {"c0": 0.4, "scale": "log_N"})
TRIANGLE = ("triangle_count", {}, {"c0": -0.2, "scale": "log_N"})


def test_a_common_factor_is_one_energy_at_zero_temperature():
    law = _law([SQUARE, TRIANGLE])
    doubled = _law([(op, p, dict(c, c0=c["c0"] * 2.5)) for op, p, c in (SQUARE, TRIANGLE)])
    assert _id(law) == _id(doubled)
    assert _id(law, PREFLIGHT_VERSION) != _id(doubled, PREFLIGHT_VERSION), "629's identity told them apart"


def test_a_multiplier_every_term_shares_is_one_energy_too():
    law = _law([SQUARE, TRIANGLE])
    flat = _law([(op, p, dict(c, scale="one")) for op, p, c in (SQUARE, TRIANGLE)])
    powered = _law([(op, p, dict(c, scale="power", p=-0.7)) for op, p, c in (SQUARE, TRIANGLE)])
    assert _id(law) == _id(flat) == _id(powered)
    mixed = _law([SQUARE, ("triangle_count", {}, {"c0": -0.2, "scale": "one"})])
    assert _id(mixed) != _id(law), "terms on two multipliers keep their ratio's N, so they are kept apart"


def test_an_anchor_reduced_onto_its_scale_shares_it():
    anchor = _law([("degree_anchor", {"k": 4}, {"c0": 0.3, "scale": "inv_sqrt_N"})])
    same = _law([("degree_anchor", {"k": 4}, {"c0": 7.0, "scale": "one"})])
    assert _id(anchor) == _id(same)
    other_k = _law([("degree_anchor", {"k": 5}, {"c0": 7.0, "scale": "one"})])
    assert _id(other_k) != _id(same)


def test_the_sign_is_not_folded():
    law = _law([SQUARE, TRIANGLE])
    flipped = _law([(op, p, dict(c, c0=-c["c0"])) for op, p, c in (SQUARE, TRIANGLE)])
    assert _id(law) != _id(flipped)


def test_a_finite_temperature_law_reads_the_same_under_both_versions():
    law = _law([SQUARE, TRIANGLE], zero=False)
    assert _id(law) == _id(law, PREFLIGHT_VERSION) == equilibrium_identity(law)[0]
    assert _id(law) != _id(_law([(op, p, dict(c, c0=c["c0"] * 2)) for op, p, c in (SQUARE, TRIANGLE)], zero=False))


def test_a_zero_temperature_law_keeps_its_identity():
    law = _law([SQUARE, TRIANGLE])
    assert equilibrium_identity(law)[0] == _id(law, PREFLIGHT_VERSION)
    assert equilibrium_identity(law)[0] == "ece05352f445c74d51de0373"


def test_a_campaign_s_function_hash_is_read_as_its_proposer_reads_it():
    class Repo:
        def __init__(self, specs):
            self.specs = specs

        def campaign(self, campaign_id):
            return {"spec": self.specs[campaign_id]} if campaign_id in self.specs else None

    LI._CAMPAIGN_VERSION.clear()
    repo = Repo({"old": HAND, "new": SURVEY})
    assert LI.campaign_version(repo, "old") == PREFLIGHT_VERSION
    assert LI.campaign_version(repo, "new") == ZERO_TEMPERATURE_FOLDED
    law = _law([SQUARE, TRIANGLE])
    assert LI.function_hash("x" * 64, law) == equilibrium_identity(law)[0], "the default is 629's"
    assert LI.function_hash("x" * 64, law, ZERO_TEMPERATURE_FOLDED) == _id(law)
    assert LI.node_identity("x" * 64, law, {}, "new")["function_hash"] == _id(law)
    assert LI.node_identity("x" * 64, law, {}, "old")["function_hash"] == equilibrium_identity(law)[0]
    LI._CAMPAIGN_VERSION.clear()


def test_a_zero_temperature_law_runs_the_base_sweeps():
    grid = dict(SURVEY["search_policy"]["grid"], zero_temperature=[True], betas={"min": 50.0, "max": 100.0})
    rng = random.Random(3)
    laws = [blind.blind_law(rng, SURVEY["operator_whitelist"], grid, complexity_budget=7) for _ in range(60)]
    assert {law["dynamics"]["sweeps"] for law in laws} == {grid["base_sweeps"]}
    hot = dict(grid, zero_temperature=[False])
    rng = random.Random(3)
    hot_laws = [blind.blind_law(rng, SURVEY["operator_whitelist"], hot, complexity_budget=7) for _ in range(60)]
    assert max(law["dynamics"]["sweeps"] for law in hot_laws) > grid["base_sweeps"], "finite temperature as before"
