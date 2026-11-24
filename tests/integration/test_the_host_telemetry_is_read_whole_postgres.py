from __future__ import annotations

import pytest

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.domain.model import content_hash

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _sample(repo: Repo, campaign: str, utc: str) -> None:
    repo.record_resource_telemetry({
        "campaign_id": campaign, "telemetry_contract": "resource-telemetry-2", "build_number": 659,
        "runtime_fingerprint": "r", "environment_fingerprint": "e", "sampled_utc": utc, "phase": "runtime",
        "interval_seconds": 4.0, "cpu_percent": 50.0, "memory_used_bytes": 1, "memory_total_bytes": 2,
        "active_simulations": 3, "active_analyses": 1, "quality": "clean", "source": {}, "active_work": []})


def test_a_campaign_reads_the_samples_filed_under_the_home_that_followed_it(isolated_postgres_schema):
    from graph_scale_dynamics.observability.evidence_sources import performance_payload
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    spec = {"mode": "continuous", "ladder": [64], "analysis_version": "telemetry-v1"}
    for campaign in ("1", "5"):
        repo.insert_campaign(campaign, spec, content_hash(spec))
    try:
        _sample(repo, "1", "2026-10-23T15:44:00Z")
        _sample(repo, "5", "2026-10-27T16:00:00Z")
        found = performance_payload(repo, "1")
        assert "error" not in found, found.get("error")
        assert [row["utc"] for row in found["occupancy_series"]] == ["2026-10-23T15:44:00Z", "2026-10-27T16:00:00Z"]
    finally:
        repo.close()
