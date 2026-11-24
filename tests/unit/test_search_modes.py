from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _snapshot(n_laws=3):
    sizes = [64, 256, 1024]
    phenotypes = []
    for i in range(n_laws):
        per_n = {str(n): {"mean_degree": 3.0 + i * 0.1 + j * 0.01, "n": n}
                 for j, n in enumerate(sizes)}
        phenotypes.append({
            "candidate_id": f"law{i}",
            "phenotype": {
                "base_sizes": sizes, "per_n": per_n,
                "probe_vectors": {"d_s": [2.0, 2.01, 2.02], "d_V": [2.0, 2.0, 2.0],
                                  "d_B": [None, None, None], "d_w": [None, None, None]},
                "probe_finite_differences": {}, "probe_bucket_vectors": {},
                "half_volume_radius_vector": [1.0, 2.0, 3.0],
            },
        })
    return {"phenotypes": phenotypes, "base_sizes": sizes, "scored_laws": [],
            "calibration": None}


def test_the_trajectory_rows_carry_the_density_the_placement_needs():
    from graph_scale_dynamics.research.report_pipeline import _trajectory_rows

    rows = _trajectory_rows(_snapshot(2))
    assert len(rows) == 2
    for row in rows:
        assert row["mean_degree"], "no density series on the trajectory row"
        assert all(isinstance(v, (int, float)) for v in row["mean_degree"])


def test_report_04_and_report_27_read_the_same_rows():
    from graph_scale_dynamics.research import report_pipeline as pipeline

    snapshot = _snapshot(4)
    assert pipeline._report_d(snapshot)["trajectories"] == pipeline._trajectory_rows(snapshot)


def test_an_extend_only_campaign_is_never_a_proposal_target():
    from graph_scale_dynamics.services.proposer.main import proposal_targets

    actives = [{"campaign_id": "1", "spec": {"search": {"extend_only": True}}},
               {"campaign_id": "2", "spec": {}}]
    assert [c["campaign_id"] for c in proposal_targets(actives)] == ["2"]


def test_extend_only_is_the_only_switch_left():
    from graph_scale_dynamics.services.proposer.main import proposal_targets

    """498 retired `GSD_PROPOSE_ALL_ACTIVE`, so extend-only composes with nothing.

    Two switches applied in order was the design; the outer one was an
    environment variable that silenced a whole campaign, and the operator met
    that failure on their own fleet. One switch, per campaign, on the record.
    """
    actives = [{"campaign_id": "1", "spec": {"search": {"extend_only": True}}},
               {"campaign_id": "2", "spec": {}}]
    assert [c["campaign_id"] for c in proposal_targets(actives)] == ["2"]


@pytest.mark.parametrize("campaign,expected", [
    ({"campaign_id": "a", "extend_only": "1"}, True),
    ({"campaign_id": "a", "extend_only": "true"}, True),
    ({"campaign_id": "a", "extend_only": "0"}, False),
    ({"campaign_id": "a"}, False),
    ({"campaign_id": "a", "spec": '{"search":{"extend_only":true}}'}, True),
    ({"campaign_id": "a", "spec": "not json"}, False),
])
def test_extend_only_is_read_from_the_row_or_the_spec(campaign, expected):
    from graph_scale_dynamics.services.proposer.main import extend_only

    assert extend_only(campaign) is expected


def test_the_banner_says_which_campaigns_stopped_proposing():
    from graph_scale_dynamics.services.proposer.main import proposal_target_banner

    line = proposal_target_banner([{"campaign_id": "1",
                                    "spec": {"search": {"extend_only": True}}}])
    assert "extend-only" in line and "1" in line
    assert "continuations and deeper rungs continue" in line


def test_both_legs_of_the_given_chain_certificate_are_persisted():
    from graph_scale_dynamics.decisions.evidence import _rung_cell
    state = {"classification": "CONVERGED", "failures": [],
             "history": [{"health": {"equilibration": {"split": {"d_s_z": 3.4},
                                                       "structural_split": {"two_core_fraction": 0.21}}}}]}
    cell = _rung_cell({}, 1024, {}, state)
    assert cell["chains_split"] == {"d_s_z": 3.4}
    assert cell["structural_split"] == {"two_core_fraction": 0.21}, (
        "the structural leg of the certificate between the chains is still unrecorded")


def test_the_engine_is_declared_so_uv_sync_cannot_delete_it():
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "gsd-engine-rs" in config["project"]["dependencies"]
    assert config["tool"]["uv"]["sources"]["gsd-engine-rs"] == {"path": "engine_rs"}
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert "gsd-engine-rs" in lock
