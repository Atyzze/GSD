from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
CANDIDATE = json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text())
from graph_scale_dynamics.dsl import dsl  # noqa: E402

LAW = dsl.fingerprint(CANDIDATE)
OTHER = dict(CANDIDATE, terms=[dict(CANDIDATE["terms"][0], coeff={"c0": 0.5, "scale": "log_N"})])
OTHER_LAW = dsl.fingerprint(OTHER)


def _summary(mean_degree: float, d_s: float) -> dict:
    return {"mean_degree": {"mean": mean_degree, "se": 0.01}, "d_s": {"mean": d_s, "se": 0.05},
            "connected_fraction": {"mean": 0.87}, "census": {"spectral_gap": {"mean": 0.002, "seeds": 3}}}


@pytest.fixture
def campaign(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.domain.model import utc_now
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign(SPEC, search_seed=1)["campaign_id"])
        repo.insert_candidate(LAW, campaign_id, CANDIDATE, "equilibrium", 1, "BASE_BLOCK_RUNNING")
        repo.insert_candidate(OTHER_LAW, campaign_id, OTHER, "equilibrium", 2, "BASE_BLOCK_RUNNING")
        rows = [(LAW, 16384, _summary(2.02, 1.48)), (LAW, 65536, _summary(2.319, 1.731)),
                (OTHER_LAW, 65536, _summary(3.0, 2.05))]
        for law, n, summary in rows:
            repo.conn.execute("INSERT INTO rung_summaries(campaign_id,candidate_id,n,analysis_version,summary_json,"
                              "created_utc) VALUES(?,?,?,?,?,?)",
                              (campaign_id, law, n, "analysis-3.0.0", json.dumps(summary), utc_now()))
    return isolated_postgres_schema.dsn, campaign_id


def test_an_anchor_is_entered_by_the_operator_alone_with_its_spec_and_numbers(campaign):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.research import anchors
    dsn, campaign_id = campaign
    with Repo(dsn) as repo:
        assert not hasattr(anchors, "scan_campaign") and not hasattr(anchors, "AUTO_RULE"), (
            "the anchors' automatic rule was the tree line, which left at 790")
        anchor = anchors.make_anchor(candidate_id=LAW, campaign_id=campaign_id,
                                     spec=anchors.law_spec(repo.conn, campaign_id, LAW),
                                     readings=anchors.law_readings(repo.conn, campaign_id, LAW),
                                     reason={"rule": "operator", "note": "by hand"})
        anchors.put(repo, anchor)
        kept = anchors.get(repo, LAW)
        assert kept["spec"]["dynamics"]["beta"] == CANDIDATE["dynamics"]["beta"] and kept["spec_complete"]
        assert [r["n"] for r in kept["readings"]] == [16384, 65536] and "residual" not in kept["readings"][1]
        assert kept["readings"][1]["spectral_gap"] == 0.002
        assert anchors.get(repo, OTHER_LAW) is None
        assert [a["candidate_id"] for a in anchors.listing(repo)] == [LAW]


def test_the_import_tool_reads_another_database_the_same_way(campaign):
    sys.path.insert(0, str(ROOT))
    from tools import import_anchors
    from graph_scale_dynamics.db.repo import connect
    dsn, _campaign_id = campaign
    conn = connect(dsn)
    try:
        found = import_anchors.gather(conn, [{"candidate_prefix": OTHER_LAW[:10], "note": "by hand"}],
                                      {"folder": "/old"})
    finally:
        conn.close()
    by_law = {a["candidate_id"]: a for a in found}
    assert set(by_law) == {OTHER_LAW}, "only the operator's picks: no rule enters a law"
    assert by_law[OTHER_LAW]["reason"]["rule"] == "operator" and by_law[OTHER_LAW]["origin"] == {"folder": "/old"}


def test_a_reset_carries_the_old_folders_own_anchors_as_they_stand(campaign):
    sys.path.insert(0, str(ROOT))
    from tools import import_anchors
    from graph_scale_dynamics.db.repo import Repo, connect
    from graph_scale_dynamics.research import anchors
    dsn, campaign_id = campaign
    with Repo(dsn) as repo:
        anchors.put(repo, anchors.make_anchor(candidate_id=LAW, campaign_id=campaign_id, spec=None, readings=[],
                                              reason={"rule": "operator", "note": "by hand"}))
        anchors.put(repo, dict(anchors.get(repo, LAW), status="marker", note="kept across the reset"))
        assert repo.conn.execute("SELECT status FROM anchors WHERE candidate_id=?", (LAW,)).fetchone()["status"] \
            == "marker", "the status is a column beside the document"
        assert repo.conn.execute("SELECT count(*) AS c FROM control WHERE key LIKE 'anchor:%'").fetchone()["c"] == 0
        legacy = anchors.make_anchor(candidate_id="legacy0000", campaign_id="gone", spec=None, readings=[],
                                     reason={"rule": "operator", "note": "from 528"}, status="probe_around")
        repo.set_flag(anchors.KEY_PREFIX + "legacy0000", json.dumps(legacy))
    conn = connect(dsn)
    try:
        found = {a["candidate_id"]: a for a in import_anchors.gather(conn, [], {"folder": "/old"})}
    finally:
        conn.close()
    assert (found[LAW]["status"], found[LAW]["note"]) == ("marker", "kept across the reset")
    assert found[LAW]["origin"] == {"folder": "/old"}
    assert found["legacy0000"]["status"] == "probe_around"
