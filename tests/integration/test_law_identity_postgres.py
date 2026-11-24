from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")
ROOT = Path(__file__).resolve().parents[2]


def _laws():
    from graph_scale_dynamics.dsl import dsl
    law = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "readings" / "controls_criterion_2.json").read_text())["laws"][0]["spec"]
    rewritten = copy.deepcopy(law)
    rewritten["terms"][0] = {"op": "degree_square_sum", "params": {}, "coeff": {"c0": 5.0, "scale": "one"}}
    rewritten["terms"].append({"op": "edge_count", "params": {}, "coeff": {"c0": -80.0, "scale": "one"}})
    cooled = copy.deepcopy(law)
    cooled["dynamics"]["cooling"] = {"from_beta": 0.5, "over_sweeps": 600}
    return {name: (dsl.fingerprint(spec), spec) for name, spec in
            (("law", law), ("rewritten", rewritten), ("cooled", cooled))}


def test_the_same_law_and_the_same_function_are_found_across_campaigns(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.research import law_identity as LI

    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        one = str(repo.create_campaign({"name": "one"}, search_seed=1)["campaign_id"])
        two = str(repo.create_campaign({"name": "two"}, search_seed=2)["campaign_id"])
        laws = _laws()
        placed = (("law", one), ("law", two), ("rewritten", two), ("cooled", one))
        for name, campaign in placed:
            law_hash, spec = laws[name]
            repo.insert_candidate(law_hash, campaign, spec, "equilibrium", 3, "EXTENDING")
        law_hash, spec = laws["law"]
        assert laws["rewritten"][0] != law_hash, "two spellings, two law hashes"
        shared = LI.shared_laws(repo)
        assert shared == {law_hash: [one, two]}
        row = LI.node_identity(law_hash, spec, shared, one)
        assert row["also_in"] == [two] and row["function_hash"] == LI.function_hash(laws["rewritten"][0],
                                                                                       laws["rewritten"][1])
        assert LI.function_hash(laws["cooled"][0], laws["cooled"][1]) != row["function_hash"], "cooling is a law"
        identity = LI.identity_for(repo, one, law_hash, spec)
        assert identity["law_hash"] == law_hash and identity["same_law_in"] == [two]
        assert [(t["campaign_id"], t["candidate_id"]) for t in identity["same_function"]] == [
            (two, laws["rewritten"][0])]
        assert identity["same_function_count"] == 1
        alone = LI.identity_for(repo, one, laws["cooled"][0], laws["cooled"][1])
        assert alone["same_law_in"] == [] and alone["same_function"] == []
    finally:
        repo.close()
