from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from tools import test_suite as suite

ROOT = Path(__file__).resolve().parents[2]


def _junit(tmp_path: Path, *cases: str) -> Path:
    path = tmp_path / "lane.xml"
    path.write_text('<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests"><testsuite name="pytest">'
                    + "".join(cases) + "</testsuite></testsuites>", encoding="utf-8")
    return path


def _case(classname: str, name: str, skipped: str | None = None, kind: str = "pytest.skip") -> str:
    inner = f'<skipped type="{kind}" message="{skipped}">{skipped}</skipped>' if skipped is not None else ""
    return f'<testcase classname="{classname}" name="{name}" time="0.0">{inner}</testcase>'


HERE = "tests.unit.test_a_skip_nobody_declared_fails_the_gate"
NODE = "tests/unit/test_a_skip_nobody_declared_fails_the_gate.py::test_an_undeclared_skip_fails_a_passing_lane"


def test_an_undeclared_skip_fails_a_passing_lane(tmp_path):
    junit = _junit(tmp_path, _case(HERE, "test_ran"),
                   _case(HERE, "test_an_undeclared_skip_fails_a_passing_lane", "zstd is not installed"))
    skips = suite.undeclared_skips(junit, allowed={})
    assert skips == [(NODE, "zstd is not installed")]
    assert suite._judge_skips(0, skips, allow=False) == suite.SKIPS_REFUSED
    assert suite._judge_skips(1, skips, allow=False) == 1, "a failing lane keeps its own status"
    assert suite._judge_skips(0, skips, allow=True) == 0, "development may look past it; the release does not"


def test_a_table_s_tests_may_skip_only_while_this_tree_declares_its_recalibration_owed(tmp_path):
    reason = f"{suite.RECALIBRATION_OWED}755: 1730 seed cells above 0 nodes were measured under estimator a"
    junit = _junit(tmp_path, _case(HERE, "test_an_undeclared_skip_fails_a_passing_lane", reason))
    assert suite.undeclared_skips(junit, allowed={}, owed=True) == []
    assert suite.undeclared_skips(junit, allowed={}, owed=False) == [(NODE, reason)], "no declaration, no skip"
    other = _junit(tmp_path, _case(HERE, "test_an_undeclared_skip_fails_a_passing_lane", "no table: " + reason))
    assert len(suite.undeclared_skips(other, allowed={}, owed=True)) == 1, "the reason the declaration gives, first"
    whole = _junit(tmp_path, f'<testcase classname="{HERE}" name="" time="0.0"><skipped type="pytest.skip" '
                             f'message="{suite.COLLECTION_SKIPPED}">(\'x.py\', 22, \'Skipped: {reason}\')</skipped></testcase>')
    assert suite.undeclared_skips(whole, allowed={}, owed=True) == [], "a whole file that needs the table"
    assert len(suite.undeclared_skips(whole, allowed={}, owed=False)) == 1
    from graph_scale_dynamics.calibration import owed
    assert suite.recalibration_is_owed() == (owed.recalibration_owed() is not None)


def test_a_declared_skip_passes(tmp_path):
    junit = _junit(tmp_path, _case(HERE, "test_an_undeclared_skip_fails_a_passing_lane[case-1]", "no root here"))
    assert suite.undeclared_skips(junit, allowed={NODE: "needs root"}) == []
    other = _junit(tmp_path, _case(HERE, "test_a_declared_skip_passes", "no root here"))
    assert len(suite.undeclared_skips(other, allowed={NODE: "needs root"})) == 1
    assert suite._judge_skips(0, [], allow=False) == 0


def test_an_expected_failure_is_not_a_skip_and_postgres_may_skip_only_in_development(tmp_path):
    junit = _junit(tmp_path, _case(HERE, "test_known", "615 and 616", kind="pytest.xfail"),
                   _case("tests.integration.test_x_postgres", "test_y",
                         f"{suite.POSTGRES_UNAVAILABLE}: RuntimeError: no initdb"))
    assert suite.undeclared_skips(junit, allowed={}, postgres_may_skip=True) == []
    assert [node for node, _ in suite.undeclared_skips(junit, allowed={})] == ["tests/integration/test_x_postgres::test_y"]


def test_every_declared_skip_names_a_test_in_the_tree_and_none_is_the_release_lanes():
    release = set(suite.LANES["release"])
    for node, reason in suite.ALLOWED_SKIPS.items():
        path, _, name = node.partition("::")
        assert (ROOT / path).is_file(), node
        assert not name or f"def {name.split('[')[0]}(" in (ROOT / path).read_text(encoding="utf-8"), node
        assert reason.strip(), f"{node} is declared without a reason"
        assert path not in release, f"{node}: the tests that execute the interface may not skip in a release"


def test_the_release_runs_the_lane_that_refuses_skips():
    source = (ROOT / "tools" / "package_release.py").read_text(encoding="utf-8")
    assert '"tools/test_suite.py", "--lane", "all", "--require-postgres",\n                             "--shards", "auto"]' in source
    assert '"--lane", "fast", "--require-postgres"]' in source
    assert "--allow-skips" not in source


def test_the_lane_runner_refuses_a_skip_end_to_end(tmp_path):
    test_file = tmp_path / "test_lane_skips.py"
    test_file.write_text(textwrap.dedent("""
        import pytest
        def test_runs():
            assert True
        def test_skips():
            pytest.skip("a tool this host lacks")
    """))
    driver = textwrap.dedent("""
        import sys
        sys.path.insert(0, sys.argv[1])
        import tools.test_suite as suite
        suite.LANES["all"] = [sys.argv[2], "-p", "no:cacheprovider"]
        raise SystemExit(suite.main(["--lane", "all", *sys.argv[3:]]))
    """)

    def lane(*flags):
        return subprocess.run([sys.executable, "-c", driver, str(ROOT), str(test_file), *flags], cwd=ROOT,
                              capture_output=True, text=True, timeout=300)

    refused = lane()
    assert refused.returncode == suite.SKIPS_REFUSED, refused.stdout + refused.stderr
    assert "a tool this host lacks" in refused.stdout and "ALLOWED_SKIPS" in refused.stdout
    assert lane("--allow-skips").returncode == 0
