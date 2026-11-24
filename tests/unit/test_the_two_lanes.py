from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import test_suite as suite  # noqa: E402


def test_the_fast_lane_runs_what_touches_the_change_and_the_release_s_checks():
    chosen = suite.fast_selection(["graph_scale_dynamics/services/api/host.py"])
    assert "tests/unit/test_the_sample_cache_is_shared_safely.py" in chosen, "a test that imports the module"
    assert set(suite.FAST_ALWAYS) <= set(chosen), "the release's own checks, whatever changed"
    assert "tests/unit/test_the_readings_lows.py" not in chosen, "a test that touches nothing changed"
    assert "tests/unit/test_the_two_lanes.py" in suite.fast_selection(["tests/unit/test_the_two_lanes.py"])
    pages = suite.fast_selection(["graph_scale_dynamics/resources/ui/app.js"])
    assert "tests/unit/test_dashboard_smoke.py" in pages


def test_the_fast_lane_is_refused_where_the_science_or_the_database_moves():
    assert suite.fast_refusal(["graph_scale_dynamics/services/api/host.py", "docs/ROADMAP.md"]) is None
    for path in ("graph_scale_dynamics/decisions/engine.py", "graph_scale_dynamics/measurements/estimators.py",
                 "graph_scale_dynamics/resources/schema/schema.sql", "engine_rs/src/lib.rs"):
        assert suite.fast_refusal([path]), path


def test_the_schema_the_fast_lane_refuses_is_the_one_the_database_is_made_from():
    from graph_scale_dynamics.db.repo import SCHEMA_FILE
    schema = Path(SCHEMA_FILE).resolve().relative_to(suite.ROOT.resolve()).as_posix()
    assert suite.fast_refusal([schema]), schema
    for refused in suite.FAST_REFUSED:
        assert (suite.ROOT / refused).exists(), refused


def test_a_change_to_a_mixin_of_the_repository_selects_the_tests_of_the_repository():
    for module in ("graph_scale_dynamics/db/repo_campaigns.py", "graph_scale_dynamics/db/repo_shared.py",
                   "graph_scale_dynamics/db/repo_jobs.py"):
        chosen = set(suite.fast_selection([module])) - set(suite.FAST_ALWAYS)
        assert len(chosen) > 20, (module, len(chosen))
        assert any("integration" in t for t in chosen), module


def test_a_new_file_git_does_not_track_is_a_change(tmp_path, monkeypatch):
    calls = []

    class Done:
        def __init__(self, out):
            self.stdout = out

    def run(argv, **kwargs):
        calls.append(argv)
        return Done("docs/ROADMAP.md\n" if "diff" in argv else "tools/new_reader.py\n")
    monkeypatch.setattr(suite.subprocess, "run", run)
    assert suite.changed_files("HEAD") == ["docs/ROADMAP.md", "tools/new_reader.py"]
    assert any("--others" in argv for argv in calls)


def test_the_full_lane_splits_its_files_by_time():
    groups = suite.plan_shards(list(suite.HERMETIC_DIRS), 3, {"tests/unit/test_size_ratchet.py": 1e6})
    assert len(groups) == 3 and sum(len(g) for g in groups) == len({f for g in groups for f in g})
    heavy = next(g for g in groups if "tests/unit/test_size_ratchet.py" in g)
    assert heavy == ["tests/unit/test_size_ratchet.py"], "the heaviest file alone in its lane"


def test_a_fast_release_is_followed_by_a_full_one(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools"))
    import package_release as PR
    notes = tmp_path / "BUILD100_NOTES.md"
    notes.write_text("## Verification\n\n12 passed in 3.0s (fast lane, 9 test files)\n")
    monkeypatch.setattr(PR, "notes_path", lambda number: tmp_path / f"BUILD{number}_NOTES.md")
    with pytest.raises(RuntimeError, match="runs the full lane"):
        PR.fast_lane_command(101)
    notes.write_text("The fast lane's line reads `N passed (fast lane, M test files)`.\n\n## Verification\n\n"
                     "3705 passed, 2 skipped in 1600s\n")
    monkeypatch.setattr(suite, "recorded_build", lambda root=None: 99)
    with pytest.raises(RuntimeError, match="records build 99's"):
        PR.fast_lane_command(101)
    monkeypatch.setattr(suite, "recorded_build", lambda root=None: 100)
    command = PR.fast_lane_command(101)
    assert command[-3:] == ["--lane", "fast", "--require-postgres"] and "--changed-since" not in command


def test_a_test_of_the_folder_s_own_processes_runs_beside_no_fleet():
    groups = suite.plan_shards(list(suite.HERMETIC_DIRS), 4)
    sharded = {f for g in groups for f in g}
    for path in ("tests/unit/test_btop_sidecar_starts.py", "tests/unit/test_no_btop_outlives_its_owner.py",
                 "tests/unit/test_scratch_namespace.py"):
        assert path in suite.with_the_folder_s_processes([path]) and path not in sharded, (
            "670's first sharded gate: the slice's btop ran beside a lane that asked none be left")


def test_the_fast_lane_always_runs_the_contract_tests():
    from tools import test_suite
    chosen = test_suite.fast_selection(["graph_scale_dynamics/domain/cadence.py"])
    contract = sorted(str(p.relative_to(test_suite.ROOT)) for p in (test_suite.ROOT / "tests" / "contract").glob("test_*.py"))
    assert contract and set(contract) <= set(chosen)


def test_a_module_started_with_dash_m_counts_as_imported_by_what_starts_it():
    from tools import test_suite
    reached = test_suite.importers("graph_scale_dynamics/services/worker/child.py")
    assert "graph_scale_dynamics/services/worker/main.py" in reached


def test_the_lanes_warm_postgresql_alone_before_they_start_together():
    import subprocess
    from types import SimpleNamespace

    from tools import test_suite as T
    assert T.needs_warming([["tests/integration", "tests/unit/x.py"], ["tests/unit"]], True)
    assert not T.needs_warming([["tests/unit"], ["tests/contract"]], True)
    assert not T.needs_warming([["tests/integration"]], True), "one lane warms itself"
    assert not T.needs_warming([["tests/integration"], ["tests/unit"]], False)
    calls = []

    def run(command, **kw):
        calls.append(command)
        return SimpleNamespace(returncode=1 if len(calls) == 1 else 0, stdout="cold bootstrap failed", stderr="")
    assert "attempt 2" in T.warm_postgres({}, run=run) and calls[0][-1] == T.WARM_UP
    failing = T.warm_postgres({}, run=lambda command, **kw: SimpleNamespace(returncode=1, stdout="no", stderr=""))
    assert "failed 2 times" in failing and "no" in failing
    assert subprocess.run is not run


def test_what_main_starts_by_a_name_it_holds_is_seen_by_the_fast_lane():
    chosen = set(suite.fast_selection(["graph_scale_dynamics/services/executor/main.py"]))
    assert "tests/integration/test_operator_path.py" in chosen, "main.py starts the executor with the module in a variable"
    for service in ("executor", "maintenance", "controller", "telemetry", "proposer", "web"):
        assert "main.py" in suite.importers(f"graph_scale_dynamics/services/{service}/main.py"), service
    assert "main.py" in suite.launched_by("tests/integration/slice_driver.py"), "[sys.executable, \"main.py\", ...]"
    assert "graph_scale_dynamics/services/worker/child.py" in suite.launched_by("graph_scale_dynamics/services/worker/main.py")
    assert not suite.launched_by("graph_scale_dynamics/observability/resource_telemetry.py"), "names, not launches"


def test_a_change_to_the_tests_own_helpers_selects_the_tests_that_use_them():
    refused_seed = "tests/integration/test_a_refused_seed_leaves_the_worker_free_postgres.py"
    for helper in ("tests/conftest.py", "tests/support/postgres.py"):
        chosen = set(suite.fast_selection([helper]))
        assert refused_seed in chosen and "tests/integration/test_operator_path.py" in chosen, helper
    driver = set(suite.fast_selection(["tests/integration/slice_driver.py"]))
    assert "tests/integration/test_operator_path.py" in driver
    doubles = set(suite.fast_selection(["tests/support/doubles.py"])) - set(suite.FAST_ALWAYS)
    assert "tests/unit/test_the_fleet_outlives_its_database.py" in doubles
    assert refused_seed not in doubles, "a helper no integration test reaches does not select the lane"
