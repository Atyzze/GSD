from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.research import perturb as P

ROOT = Path(__file__).resolve().parents[2]
READINGS = ROOT / "graph_scale_dynamics" / "resources" / "readings"
FINITE = {"dsl_version": 1, "init": "empty",
          "terms": [{"op": "degree_cube_sum", "params": {}, "coeff": {"c0": 0.0820979, "scale": "one"}},
                    {"op": "square_edge_overlap", "params": {}, "coeff": {"c0": -0.106043, "scale": "one"}},
                    {"op": "triangle_edge_overlap", "params": {}, "coeff": {"c0": -0.0177926, "scale": "one"}}],
          "dynamics": {"kind": "equilibrium", "beta": 5.65062, "sweeps": 30, "locality": 0.344949,
                       "move_mix": {"add": 0.1497335, "delete": 0.1497335, "swap": 0.700533}}}


def _json(name: str) -> dict:
    return json.loads((READINGS / name).read_text(encoding="utf-8"))


def _variants(spec=FINITE, **kw):
    return P.variants(spec, dsl.fingerprint(spec), salt="study test", complexity_budget=7, whitelist=None, **kw)


def test_every_real_parameter_moves_by_half_its_radius_to_its_radius_and_the_law_is_new():
    found = _variants()
    assert len(found) == len(P.RADII) * P.PER_RADIUS
    ids = {v["candidate_id"] for v in found}
    assert len(ids) == len(found) and dsl.fingerprint(FINITE) not in ids
    for v in found:
        assert [c["parameter"] for c in v["changes"]] == ["term 1 c0", "term 2 c0", "term 3 c0", "beta", "locality",
                                                          "swap"]
        for change in v["changes"]:
            size = abs(change["relative"])
            slack = 1e-11 / abs(change["from"])
            assert v["radius"] / 2 - slack <= size <= v["radius"] + slack, (v["radius"], change)
        mix = v["spec"]["dynamics"]["move_mix"]
        assert abs(mix["add"] + mix["delete"] + mix["swap"] - 1.0) < 1e-9 and 0 < mix["swap"] < 1
        assert P.problem_of(v["spec"], complexity_budget=7, whitelist=None) is None
    assert found == _variants(), "the variants are a function of the law and the study's salt"
    assert found != P.variants(FINITE, dsl.fingerprint(FINITE), salt="another study", complexity_budget=7,
                               whitelist=None)


def test_a_zero_temperature_law_keeps_its_beta_which_its_dynamics_never_read():
    cold = json.loads(json.dumps(FINITE))
    cold["dynamics"]["zero_temperature"] = True
    for v in _variants(cold, radii=(1e-3,), per_radius=3):
        assert v["spec"]["dynamics"]["beta"] == cold["dynamics"]["beta"]
        assert "beta" not in [c["parameter"] for c in v["changes"]]


def test_the_stream_radius_changes_the_law_s_random_numbers_and_nothing_a_chain_can_feel():
    for v in _variants(radii=(1e-9,), per_radius=4):
        assert v["candidate_id"] != dsl.fingerprint(FINITE)
        assert all(abs(c["relative"]) <= 1e-9 + 1e-11 / abs(c["from"]) for c in v["changes"])


def test_every_holder_is_the_law_it_names_and_is_settled_by_the_score_in_force():
    from graph_scale_dynamics.observability import law_score as L
    source = _json("study_175_holders.json")
    assert source["study"] == "175" and source["from"]["study"] == "174" and source["score"] == L.CONTRACT
    assert source["score_in_force"] == "gsd-law-score-6", "the score in force when 847 chose them"
    labels = [h["label"] for h in source["holders"]]
    assert labels == [f"H{i:02d}" for i in range(1, len(labels) + 1)] and len(labels) >= 10
    for holder in source["holders"]:
        assert dsl.fingerprint(holder["spec"]) == holder["candidate_id"], holder["label"]
        own = holder["read_in_174"]
        assert own["score"] > 0 and own["by"] != "frozen" and any(p >= 2 for p in own["items"].values())
        assert own["chain"] and own["to_n"] >= 16384 and own["values"]


def _design():
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations.campaign_control import shipped_spec
    design = SD.design_for(ROOT, "175")
    survey = SD.campaign_spec(design, SD.without_terms(design, shipped_spec(), log=lambda line: None),
                              design["campaigns"][0], 0)
    return SD, design, survey


def test_the_design_names_its_laws_and_runs_them_on_174_s_rules_with_no_judgment_stopping_a_variant():
    from graph_scale_dynamics.decisions.engine import Policy
    SD, design, survey = _design()
    old = _json("study_174_design.json")
    for key in ("contract", "axes", "ladder", "starts", "limits", "starts_reading", "finds", "terms_left_out"):
        assert design[key] == old[key], key
    laws = SD.perturb_laws(design, survey, ROOT)
    assert len(laws) == design["perturb"]["laws"] == design["law_budget"]
    assert SD.laws_sha256(laws) == design["perturb"]["laws_sha256"]
    holders = _json("study_175_holders.json")["holders"]
    assert len(laws) == len(holders) * (1 + len(design["perturb"]["radii"]) * design["perturb"]["per_radius"])
    assert [law["candidate_id"] for law in laws if not law["radius"]] == [h["candidate_id"] for h in holders]
    assert survey["search_policy"]["kind"] == "hand" and survey["study_design"]["kind"] == SD.PERTURB
    policy = Policy.from_spec(survey)
    from graph_scale_dynamics.decisions import gates as G
    for n in (256, 1024, 4096, 16384, 65536):
        assert policy.live_share("starts_alike", n) == policy.live_share("nothing_read", n) == G.RECORD_ONLY, n
        assert {gate for gate in G.LET_THROUGH_GATES if policy.live_share(gate, n) < 1.0} <= {
            "empty", "too_dense", "disconnected"}, n
    text = json.dumps(design, ensure_ascii=False)
    assert "—" not in text and "–" not in text


def test_the_criterion_was_committed_on_the_design_and_holders_it_names():
    criterion = _json("study_175_criterion.json")
    for key, name in (("design_sha256", "study_175_design.json"), ("holders_sha256", "study_175_holders.json")):
        assert criterion[key] == hashlib.sha256((READINGS / name).read_bytes()).hexdigest(), key
    assert "first start" in criterion["committed_before"]
    assert criterion["verdict"]["alike_at_least"] <= _json("study_175_design.json")["perturb"]["per_radius"]
    assert set(criterion["predictions"]) == {"P1", "P2", "P3"}


def test_a_verdict_reads_the_stream_first_then_each_radius_in_turn():
    import importlib.util
    spec = importlib.util.spec_from_file_location("perturb_reading", ROOT / "tools" / "perturb_reading.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    rule = {"alike_at_least": 3}
    assert R.verdict({1e-9: 2, 1e-3: 4, 1e-2: 4, 1e-1: 4}, rule) == ("stream", None)
    assert R.verdict({1e-9: 4, 1e-3: 2, 1e-2: 4, 1e-1: 4}, rule) == ("point", None)
    assert R.verdict({1e-9: 3, 1e-3: 3, 1e-2: 1, 1e-1: 4}, rule) == ("region", 1e-3)
    assert R.verdict({1e-9: 4, 1e-3: 4, 1e-2: 4, 1e-1: 3}, rule) == ("region", 1e-1)
    held = {"d": 3.0, "mean_degree": 8.0}
    assert R.alike({"d": 3.25, "mean_degree": 8.5}, held, 0.1)
    assert not R.alike({"d": 3.35, "mean_degree": 8.0}, held, 0.1)
    assert not R.alike({"d": 3.0, "mean_degree": 9.0}, held, 0.1)
    assert not R.alike(None, held, 0.1)


@pytest.fixture
def a_side_bundle(tmp_path):
    SD, design, survey = _design()
    laws = SD.perturb_laws(design, survey, ROOT)
    holder = _json("study_175_holders.json")["holders"][0]
    own = holder["read_in_174"]
    columns = own["value_columns"]
    chain, n = own["chain"], int(own["to_n"])
    top = next(row for row in own["values"] if int(row[0]) == n)
    entries = {holder["candidate_id"]: {"values": {chain: own["values"]}, "top_n": n}}
    for law in laws:
        if law["of"] != holder["candidate_id"] or not law["radius"]:
            continue
        far = law["radius"] >= 1e-2
        row = list(top)
        if far:
            row = [value * 1.5 if isinstance(value, float) and index else value for index, value in enumerate(row)]
        entries[law["candidate_id"]] = {"values": {chain: [row]}, "top_n": n}
    folder = tmp_path / "study_175_x" / "campaign_1_reports_x"
    folder.mkdir(parents=True)
    (folder / "28-decision-engine.json").write_text(json.dumps({"campaign_id": "1", "body": {
        "every_chain": {"value_columns": columns, "laws": entries}, "laws": []}}), encoding="utf-8")
    return folder.parent, holder


def test_the_reading_finds_a_region_to_a_thousandth_and_the_run_again_replays(a_side_bundle):
    import importlib.util
    spec = importlib.util.spec_from_file_location("perturb_reading", ROOT / "tools" / "perturb_reading.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    root, holder = a_side_bundle
    found = R.read(root)
    assert found["holders"] == 1 and found["replayed"] == 1
    row = found["rows"][0]
    assert row["holder"] == holder["label"] and row["verdict"] == "region" and row["region_to"] == 1e-3
    assert row["alike"] == {"1e-09": 4, "0.001": 4, "0.01": 0, "0.1": 0}
    assert "region to 0.001 1" in R.render(found).replace(",", "")
