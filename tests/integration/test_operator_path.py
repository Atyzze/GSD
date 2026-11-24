from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from tests.integration.slice_driver import rr

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _campaign_id(started: subprocess.CompletedProcess[str]) -> str:
    match = re.search(r"^Campaign (\S+) created", started.stdout, re.MULTILINE)
    assert match, started.stdout[-2000:] + started.stderr[-2000:]
    return match.group(1)


def test_operator_path_start_use_export_replay(isolated_postgres_schema):
    var = ROOT / f".pytest_operator_var_{uuid.uuid4().hex[:8]}"
    database = f"folder-schema:{isolated_postgres_schema.schema}"
    try:
        assert rr("init", var=var, database=database).returncode == 0

        spec_dir = var / "specs"
        spec_dir.mkdir(parents=True)
        spec = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
        spec["engine"]["policy"]["audit_fraction"] = 0.25
        spec_path = spec_dir / "custom.json"
        spec_path.write_text(json.dumps(spec))

        started = rr("campaign", "start", "--spec", str(spec_path), "--allow-unvalidated-analyzer",
                     "--reason", "operator path test", var=var, database=database)
        assert started.returncode == 0, started.stdout[-2000:] + started.stderr[-2000:]
        campaign = _campaign_id(started)

        listed = rr("campaign", "list", var=var, database=database)
        assert listed.returncode == 0 and campaign in listed.stdout

        used = rr("campaign", "use", campaign, var=var, database=database)
        assert used.returncode == 0 and f"home campaign set to {campaign}" in used.stdout, used.stdout

        closed = rr("campaign", "close", campaign, var=var, database=database)
        assert closed.returncode == 0, closed.stdout + closed.stderr
        explicit = rr("run", "--campaign", campaign, "--workers", "1", var=var, database=database)
        assert explicit.returncode != 0 and "refusing to run closed campaign" in explicit.stdout
        refused = rr("run", "--workers", "1", var=var, database=database)
        assert refused.returncode == 2, refused.stdout[-1500:] + refused.stderr[-1500:]
        assert "refusing to create a new default campaign" in refused.stdout, refused.stdout[-1500:]
        assert "campaign reopen" in refused.stdout
        reopened = rr("campaign", "reopen", campaign, var=var, database=database)
        assert reopened.returncode == 0, reopened.stdout + reopened.stderr

    finally:
        shutil.rmtree(var, ignore_errors=True)
