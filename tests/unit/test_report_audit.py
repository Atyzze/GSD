from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import report_audit  # noqa: E402

UNREAD: set[str] = set()


def test_every_report_builds_from_the_snapshot_fixture_and_says_what_it_reads():
    result = report_audit.audit()
    failing = {r["code"]: r["reads"]["error"] for r in result["reports"] if r["reads"]["error"]}
    assert not failing, failing
    assert all(r["reads"]["parts"].get("primary") for r in result["reports"])


def test_every_report_has_a_reader():
    unread = set(report_audit.audit()["unread"])
    assert not unread - UNREAD, f"a report no code and no page reads: {sorted(unread - UNREAD)}"
    assert not UNREAD - unread, f"read now, so no longer listed: {sorted(UNREAD - unread)}"


def test_the_readers_are_found_where_they_open_a_report():
    readers = report_audit.openers()
    assert {"graph_scale_dynamics/reporting/study_reading.py", "tools/read_bundle.py",
            "tools/law_rows.py"} <= {x["file"] for x in readers["28"]}
    assert "graph_scale_dynamics/reporting/study_reading.py" in {x["file"] for x in readers["05"]}


def _real_job_spec(n: int) -> dict:
    import json
    from graph_scale_dynamics.dsl import dsl
    from graph_scale_dynamics.scheduling.job_creation import enqueue_simulation_rung
    spec = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
    law = json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text())
    created = []

    class Capture:
        def insert_job(self, **job):
            created.append(job)
            return True

    class Log:
        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    enqueue_simulation_rung(Capture(), Log(), {"campaign_id": "1", "spec": spec},
                            {"candidate_id": dsl.fingerprint(law), "spec": law}, n, [0], "decision_engine",
                            execution_overrides={"proposal_locality": 0.25})
    return created[0]["spec"]


def _kept(path: tuple, shape) -> bool:
    node = shape
    for part in path:
        if node is None:
            return True
        if part not in node:
            return False
        node = node[part] if isinstance(node, dict) else None
    return True


def test_what_the_reports_read_of_a_job_s_spec_is_what_the_snapshot_keeps():
    import copy
    from graph_scale_dynamics.research.snapshot_rows import JOB_SPEC_READ, job_spec_read
    spec = _real_job_spec(1024)
    read = set().union(*report_audit.paths_read("jobs", "spec", lambda row: copy.deepcopy(spec)).values())
    assert ("execution", "sweeps_multiplier") in read, sorted(read)
    assert ("execution", "one_shot", "work_budget") in read, sorted(read)
    assert all(_kept(path, JOB_SPEC_READ) for path in read), sorted(path for path in read
                                                                  if not _kept(path, JOB_SPEC_READ))
    kept = job_spec_read(copy.deepcopy(spec))
    assert kept == {"execution": {"sweeps_multiplier": spec["execution"]["sweeps_multiplier"],
                                  "one_shot": {"work_budget": spec["execution"]["one_shot"]
                                               ["work_budget"]}},
                    "candidate_spec": {"dynamics": {"sweeps": spec["candidate_spec"]["dynamics"]["sweeps"]}}}


def test_what_the_reports_read_of_a_measurement_s_metrics_is_what_the_snapshot_keeps():
    import copy
    import json
    from itertools import count
    from graph_scale_dynamics.research.snapshot_rows import UNREAD_METRICS_SECTIONS
    documents = json.loads((ROOT / "tests/fixtures/metrics_documents.json").read_text())["documents"]
    assert all(set(UNREAD_METRICS_SECTIONS) <= set(document) for document in documents)
    turn = count()
    read = set().union(*report_audit.paths_read(
        "measurements", "metrics", lambda row: copy.deepcopy(documents[next(turn) % len(documents)])).values())
    assert {("health",), ("census",)} <= read and not {path[0] for path in read} & set(UNREAD_METRICS_SECTIONS)
