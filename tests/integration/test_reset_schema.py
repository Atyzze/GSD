from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "tests" / "fixtures" / "campaign_5rung_sparse_survey.json").read_text(encoding="utf-8"))
ANALYSIS_VERSION = str(SPEC["analysis_version"])


def _law(coefficient: float) -> dict:
    return {"dsl_version": 1, "init": "empty",
            "terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": coefficient, "scale": "one"}}],
            "dynamics": {"kind": "equilibrium", "beta": 1.0,
                         "move_mix": {"add": 0.5, "delete": 0.5}, "sweeps": 30}}


def test_probe_timing_is_the_four_split_columns_and_nothing_else(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, _probe_seconds_columns, init_db

    assert _probe_seconds_columns({"probe_seconds": {"d_s": 1.5, "d_V": 0.5, "d_B": 2.0, "d_w": 1.0}}) \
        == (1.5, 0.5, 2.0, 1.0)
    assert _probe_seconds_columns({"probe_seconds": {"d_s": 1.5}}) == (1.5, None, None, None)
    assert _probe_seconds_columns({"probe_seconds": {"d_B_d_w": 3.0}}) == (None, None, None, None)
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        columns = {row["column_name"] for row in repo.conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='measurements' "
            "AND table_schema=current_schema()")}
        assert {"probe_seconds_d_s", "probe_seconds_d_v", "probe_seconds_d_b", "probe_seconds_d_w"} <= columns
        assert "probe_seconds_geometry" not in columns
        candidate_columns = {row["column_name"] for row in repo.conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='campaign_candidates' "
            "AND table_schema=current_schema()")}
        assert "unfiltered" in candidate_columns
