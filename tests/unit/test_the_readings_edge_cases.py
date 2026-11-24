from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def test_a_control_s_lattice_chain_is_read_with_its_start(monkeypatch):
    from graph_scale_dynamics.observability import starts_reading as F
    from graph_scale_dynamics.observability import law_score
    asked = []
    real = F.law_reading
    monkeypatch.setattr(F, "law_reading", lambda chains, starts=None, refs=None, **kw: asked.append(starts) or real(
        chains, starts, refs, **kw))
    read_without = {"chains": [{"name": "empty", "start": None}, {"name": "given", "start": None}], "rungs": []}
    law_score.score({"rungs": []}, read_without, first_given="periodic_cubic_quotient", references={})
    assert asked and {"name": "given", "family": "periodic_cubic_quotient"} in asked[0]
    asked.clear()
    law_score.score({"rungs": []}, read_without, first_given="erdos_renyi_mean_degree", references={})
    assert not asked, "a random first given chain's reading is as it was"


def test_an_anchor_listing_that_failed_is_unavailable(monkeypatch):
    from graph_scale_dynamics.reporting import study_bundle
    from graph_scale_dynamics.research import anchors

    def broken(repo):
        raise RuntimeError("the anchors' table is gone")

    monkeypatch.setattr(anchors, "listing", broken)
    document = study_bundle.anchors_document(object())
    assert document["count"] is None and "gone" in document["unavailable"]


def test_the_landscape_carries_the_plateau_break_and_the_deepest_rung(monkeypatch):
    from graph_scale_dynamics.research import score_door
    from graph_scale_dynamics.services.api import landscape_worker as LW
    monkeypatch.setattr(score_door, "score_evidence", lambda **kw: {
        "blocks": {}, "buckets": {}, "valid_rungs": 5, "plateau_break": {"breaks": [{"n": 65536}]}})
    phenotype = {"contract": LW.BASE_BLOCK_CONTRACT, "base_sizes": [64, 256, 1024, 4096],
                 "per_n": {}, "extension_sizes": [16384, 65536]}
    out = LW._score_candidate({"rungs": []}, floors={}, phenotype=phenotype)
    assert out["plateau_break"] == {"breaks": [{"n": 65536}]}
    assert out["evidence"]["top_rung"] == 65536
    assert LW.stability_fields(dict(out, plateau_break=out["plateau_break"]))["stability_plateau_break"] == {"n": 65536}


def test_a_refused_bundle_is_not_said_to_be_corrupt(tmp_path):
    from graph_scale_dynamics.research.bundle_layout import extract
    inner = tmp_path / "bundle.tar"
    with tarfile.open(inner, "w") as tar:
        data = os.urandom(4 << 20)
        info = tarfile.TarInfo("part/report.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    subprocess.run(["zstd", "-q", "-f", str(inner), "-o", str(tmp_path / "bundle.tar.zst")], check=True)
    with pytest.raises(ValueError, match="refused"):
        extract(tmp_path / "bundle.tar.zst", tmp_path / "out", max_bytes=100)
    assert extract(tmp_path / "bundle.tar.zst", tmp_path / "again").joinpath("part/report.json").is_file()


def test_a_database_error_in_report_28_s_record_leaves_the_snapshot_usable(monkeypatch):
    from graph_scale_dynamics.research import record_report as R
    said = []
    conn = SimpleNamespace(in_transaction=True, execute=lambda sql, *a: said.append(sql))
    monkeypatch.setattr(R, "collect_record", lambda repo, campaign_id: (_ for _ in ()).throw(RuntimeError("aborted")))
    out = R.collect_record_safely(SimpleNamespace(conn=conn), "1")
    assert "aborted" in out["error"]
    assert said == ["SAVEPOINT gsd_record_report", "ROLLBACK TO SAVEPOINT gsd_record_report"]
    said.clear()
    assert R._section(conn, "gate", lambda: {"ok": 1}) == {"ok": 1}
    assert said == ["SAVEPOINT gsd_record_gate", "RELEASE SAVEPOINT gsd_record_gate"]


def test_a_law_that_sees_curvature_is_a_kind_of_its_own_in_the_readings():
    from graph_scale_dynamics.research import degree_prediction as D
    from graph_scale_dynamics.research import law_ledger as L
    law = {"terms": [{"op": "edge_count", "coefficient": 1.0}, {"op": "ollivier_curvature", "coefficient": -0.5}],
           "dynamics": {"kind": "metropolis", "beta": 1.0}}
    assert L.reading_kind(law) == L.KIND_CURVATURE
    assert D.law_kind(law) == D.KIND_CORRELATIONS, "the draw gate's kind is unchanged, as is the committed predictor"
    assert L.ledger_prediction(law, 4096, 16.0) == [None, "curvature / finite temperature"]


def test_a_control_is_judged_on_its_campaign_s_analysis_version():
    from graph_scale_dynamics.research import control_verdict as CV
    asked = []

    class Repo:
        def measurements(self, law, version, campaign_id):
            asked.append(version)
            return []

    CV.campaign_verdict(Repo(), {"campaign_id": "6", "spec": {"name": "campaign-standing-controls",
                                                              "analysis_version": "v-of-the-campaign"}})
    assert asked and set(asked) == {"v-of-the-campaign"}


def test_a_failed_seed_is_not_a_graph_grown():
    from graph_scale_dynamics.research.graph_trickle import graphs_per_law_rung
    seeds = {"columns": ["law", "n", "seed", "simulation_seconds", "final_edges", "final_mean_degree", "ended"],
             "laws": ["a"], "rows": [[0, 256, 0, 12.0, 400, 3.1, "completed"],
                                     [0, 256, 1, 30.0, None, None, "memory_hard_cap"],
                                     [0, 256, 2, 9.0, None, None, None]]}
    assert graphs_per_law_rung(seeds) == {("a", 256): 2}


def test_the_depth_claim_says_what_the_rule_set_holds():
    from graph_scale_dynamics.research import claim_ledger as C
    claim = next(c for c in C.tree_claims() if c.claim_id == "depth_is_bought_on_ds_alone")
    assert claim.statement.startswith("of the rules that settle a law, d_s alone does")
    assert "Other rules buy rungs too" in claim.check()["reading"]


def test_a_law_counts_at_256_only_once_decided_there():
    import sample_reading as R
    assert R.outcome_at_256({"fate": "base_block", "fate_n": 64}) is None
    assert R.outcome_at_256({"fate": "empty", "fate_n": 256}) == "empty"
    assert R.outcome_at_256({"fate": "d_s_settled", "fate_n": 1024}) == "past 256"
    import pattern_scan as P
    rows = [{"fate": "empty", "fate_n": 256}, {"fate": "base_block", "fate_n": 64}]
    flags, over = P.outcomes(rows)["empty at 256"]
    assert list(over) == [True, False]


def test_a_missing_control_has_not_passed(tmp_path, monkeypatch, capsys):
    import positive_control as P
    (tmp_path / "study.json").write_text(json.dumps({"campaigns": []}))
    args = type("A", (), {"criterion": None, "bundle": str(tmp_path), "json": False})()
    assert P.cmd_check(args) == 1
    assert "gsd-controls-criterion-3" in P.ONLY_IN_A_GROWTH_STUDY


def test_report_28_is_read_in_either_layout(tmp_path):
    import law_rows as L
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "28.json").write_text(json.dumps({"body": {"every_chain": {"laws": {"x": {}}}}}))
    assert L.body(tmp_path)["every_chain"]["laws"] == {"x": {}}
    assert L.body(tmp_path / "nowhere") == {}
