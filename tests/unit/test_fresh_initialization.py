from __future__ import annotations

import json
from importlib.resources import files as resource_files

import main


def test_all_packaged_campaigns_can_propose_overlap_aware_laws():
    configs = resource_files("graph_scale_dynamics.resources").joinpath("configs")
    names = sorted(item.name for item in configs.iterdir() if item.name.endswith(".json"))
    assert names == [
        "campaign_engine_survey.json",
        "candidate_sparse_anchor.json",
    ]
    discovery = json.loads(configs.joinpath("campaign_engine_survey.json").read_text(encoding="utf-8"))
    assert "triangle_edge_overlap" in discovery["operator_whitelist"]
    assert discovery["base_block"]["sizes"] == [64, 256, 1024, 4096]


def test_postgres_config_is_generated_not_shipped_as_deployment_recipe():
    from tools.postgres_instance import POSTGRES_BACKEND, POSTGRES_MANIFEST_DIGEST, render_env
    socket_dir = main.ROOT / "instance" / "postgres" / "socket"
    env = render_env(name="gsd-test", password="secret", socket_dir=socket_dir)
    assert "POSTGRES_DB=graph_scale_dynamics" in env
    assert f"POSTGRES_SOCKET={socket_dir.resolve()}" in env
    assert f"POSTGRES_BACKEND={POSTGRES_BACKEND}" in env
    assert f"POSTGRES_MANIFEST={POSTGRES_MANIFEST_DIGEST}" in env
    assert "DATABASE_URL=" not in env
    assert not (main.ROOT / "deploy").exists()
