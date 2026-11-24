from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_every_module_root_constant_is_the_repository():
    pattern = ast.parse("Path(__file__).resolve().parents[0]").body[0].value
    wrong: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in {"var", "instance", "build", "dist", ".venv"}:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or not target.id.endswith("ROOT"):
                continue
            depth = _resolve_depth(node.value, pattern)
            if depth is None:
                continue
            resolved = path.resolve().parents[depth]
            if resolved != ROOT:
                wrong.append(f"{rel}:{node.lineno} {target.id} -> {resolved}")
    assert not wrong, "root constants that are not the repository:\n" + "\n".join(wrong)


def _resolve_depth(value: ast.expr, _pattern) -> int | None:
    text = ast.unparse(value)
    if not text.startswith("Path(__file__).resolve()"):
        return None
    tail = text[len("Path(__file__).resolve()"):]
    if tail == ".parent":
        return 0
    if tail.startswith(".parents[") and tail.endswith("]"):
        try:
            return int(tail[len(".parents["):-1])
        except ValueError:
            return None
    return None


def test_a_child_carries_the_project_root_the_reaper_looks_for():
    from graph_scale_dynamics.operations.startup_reaper import CHILD_ROOT_ENV
    from graph_scale_dynamics.services.analyzer import main as analyzer
    from graph_scale_dynamics.services.worker import main as worker

    assert worker.ROOT == ROOT
    assert analyzer.ROOT == ROOT
    assert CHILD_ROOT_ENV == "GSD_PROJECT_ROOT"


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="the reaper reads /proc")
def test_the_reaper_finds_a_child_launched_the_way_the_worker_launches_one():
    from graph_scale_dynamics.operations import startup_reaper
    from graph_scale_dynamics.services.worker import main as worker

    env = dict(os.environ, PYTHONPATH=str(worker.ROOT), GSD_CHILD_KIND="simulation",
               GSD_PROJECT_ROOT=str(worker.ROOT), GSD_CHILD_N="64")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"],
                             env=env, start_new_session=True)
    try:
        deadline = time.monotonic() + 5.0
        seen: list[int] = []
        while time.monotonic() < deadline and not seen:
            seen = [row["pid"] for row in startup_reaper.survey_orphan_children(ROOT)
                    if row["pid"] == child.pid]
            if not seen:
                time.sleep(0.1)
        assert seen, "a child stamped by this tree's worker is invisible to this tree's reaper"
    finally:
        child.kill()
        child.wait(timeout=5)


def test_the_cpu_sampler_takes_one_reading_however_many_threads_ask():
    from graph_scale_dynamics.observability import host_resources as H

    calls: list[float] = []

    def slow_sample():
        calls.append(time.monotonic())
        time.sleep(0.003)
        return _times(busy=50.0 + len(calls), idle=50.0)

    real = H.psutil.cpu_times
    H.psutil.cpu_times = slow_sample
    try:
        H._CPU_SAMPLE.update(at=0.0, value=11.0, armed=True, times=(40.0, 90.0, 0.0))
        threads = [threading.Thread(target=H.cpu_percent_sampled) for _ in range(32)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(calls) == 1, f"{len(calls)} concurrent psutil samples in one interval"
    finally:
        H.psutil.cpu_times = real
        H._CPU_SAMPLE.update(at=0.0, value=None, armed=False, times=None)


def _times(*, busy: float, idle: float, iowait: float = 0.0):
    import collections
    return collections.namedtuple("scputimes", "user nice system idle iowait")(busy, 0.0, 0.0, idle, iowait)


def test_the_warm_up_reading_arms_the_interval():
    from graph_scale_dynamics.observability import host_resources as H

    H._CPU_SAMPLE.update(at=0.0, value=None, armed=False, times=None)
    real = H.psutil.cpu_times
    H.psutil.cpu_times = lambda: _times(busy=100.0, idle=100.0)
    try:
        assert H.cpu_percent_sampled(now=1000.0) is None
        assert H._CPU_SAMPLE["armed"] is True
        assert H._CPU_SAMPLE["at"] == 1000.0
        H.psutil.cpu_times = lambda: _times(busy=191.0, idle=109.0)
        assert H.cpu_percent_sampled(now=1000.2) is None, "still inside the interval"
        assert H.cpu_percent_sampled(now=1001.5) == 91.0
    finally:
        H.psutil.cpu_times = real
        H._CPU_SAMPLE.update(at=0.0, value=None, armed=False, times=None)


def test_a_new_thread_reads_the_same_window_not_its_own_empty_one():
    from graph_scale_dynamics.observability import host_resources as H

    H._CPU_SAMPLE.update(at=0.0, value=None, armed=False, times=None, iowait=None)
    real = H.psutil.cpu_times
    try:
        H.psutil.cpu_times = lambda: _times(busy=1000.0, idle=1000.0, iowait=0.0)
        assert H.cpu_percent_sampled(now=5000.0) is None
        H.psutil.cpu_times = lambda: _times(busy=1050.0, idle=1040.0, iowait=10.0)
        read = []
        thread = threading.Thread(target=lambda: read.append(H.cpu_percent_sampled(now=5001.5)))
        thread.start()
        thread.join()
        assert read == [50.0], read
        assert H.cpu_iowait_sampled() == 10.0, "the I/O wait share of the same window"
    finally:
        H.psutil.cpu_times = real
        H._CPU_SAMPLE.update(at=0.0, value=None, armed=False, times=None, iowait=None)


def test_a_non_ascii_capability_header_is_a_refusal_not_a_traceback():
    from graph_scale_dynamics.services.api.main import build_handler

    handler = build_handler(db_path="folder", blobs_path=str(ROOT / "var" / "blobs"),
                            admin_token="a-real-token", port=0)
    matches = handler._token_matches
    assert matches("a-real-token", "a-real-token") is True
    assert matches("wrong", "a-real-token") is False
    assert matches("", "a-real-token") is False
    assert matches("tökenü", "a-real-token") is False
    assert matches("a-real-token", "") is False


def test_the_non_science_runtime_has_no_dead_local_bindings():
    pytest.importorskip("pyflakes")
    frozen = set(json.loads((ROOT / "tests/fixtures/science_freeze.json").read_text())["files"])
    targets = [str(ROOT / "graph_scale_dynamics"), str(ROOT / "tools"), str(ROOT / "main.py")]
    done = subprocess.run([sys.executable, "-m", "pyflakes", *targets],
                          capture_output=True, text=True, cwd=ROOT)
    offences = []
    for line in done.stdout.splitlines():
        if "assigned to but never used" not in line and "f-string is missing placeholders" not in line:
            continue
        rel = Path(line.split(":", 1)[0]).resolve().relative_to(ROOT).as_posix()
        if rel in frozen:
            continue
        offences.append(line)
    assert not offences, "\n".join(offences)


def test_a_malformed_law_is_an_exception_the_child_can_catch():
    from tests.support.engines import a_chain_request, every_door_of_every_engine
    good_state, good_index = [0] * 624, 624
    ok_term = {"op": "edge_count", "coeff": 1.0}
    for _door, call in every_door_of_every_engine():
        def run(terms, words, index):
            return call("run_chain", a_chain_request(8, terms, [], 0.0, words=words, index=index))

        with pytest.raises(KeyError):
            run([{"op": "edge_count"}], good_state, good_index)
        with pytest.raises(KeyError):
            run([{"coeff": 1.0}], good_state, good_index)
        with pytest.raises(ValueError):
            run([ok_term], [0] * 10, 3)
        with pytest.raises(ValueError):
            run([ok_term], good_state, 900)


class _TerminatedConnection:
    class _Info:
        transaction_status = 4

    closed = True
    info = _Info()

    def execute(self, *_args, **_kwargs):
        raise RuntimeError("the connection is closed")


def test_a_terminated_session_is_not_a_transaction_to_roll_back():
    from graph_scale_dynamics.db.connection import PostgresConnection

    conn = PostgresConnection.__new__(PostgresConnection)
    conn.raw = _TerminatedConnection()

    assert conn.closed is True
    assert conn.in_transaction is False, "UNKNOWN is a connection to give up on, not a transaction to end"
    assert conn.rollback_if_open() is False
    try:
        raise ValueError("the real cause")
    except ValueError:
        conn.rollback_if_open()
    assert True


def test_the_idle_in_transaction_timeout_is_classified_as_transient():
    from graph_scale_dynamics.db.connection import PostgresConnection

    assert "25P03" in PostgresConnection.TRANSIENT_STATES


def test_the_snapshot_worker_sizes_its_session_from_its_own_deadline():
    from graph_scale_dynamics.operations.report_session import apply_snapshot_session_policy

    default: dict[str, str] = {}
    apply_snapshot_session_policy(default)
    assert int(default["GSD_DATABASE_IDLE_TX_TIMEOUT_MS"]) > 3_600_000, (
        "the default bound must outlast the default snapshot deadline"
    )

    short = {"GSD_REPORT_SNAPSHOT_TIMEOUT": "900"}
    apply_snapshot_session_policy(short)
    assert int(short["GSD_DATABASE_IDLE_TX_TIMEOUT_MS"]) == 1_200_000

    operator = {"GSD_DATABASE_IDLE_TX_TIMEOUT_MS": "5000"}
    apply_snapshot_session_policy(operator)
    assert operator["GSD_DATABASE_IDLE_TX_TIMEOUT_MS"] == "5000", "an explicit setting is not overridden"

    unreadable = {"GSD_REPORT_SNAPSHOT_TIMEOUT": "not-a-number"}
    apply_snapshot_session_policy(unreadable)
    assert int(unreadable["GSD_DATABASE_IDLE_TX_TIMEOUT_MS"]) > 3_600_000


def test_no_rollback_in_this_tree_can_raise_over_the_error_it_is_handling():
    offenders = []
    for path in sorted((ROOT / "graph_scale_dynamics").rglob("*.py")):
        if path.name == "connection.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            code = line.split("#", 1)[0]
            if 'execute("ROLLBACK")' in code:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{number}")
    assert not offenders, (
        "these roll back with a bare execute, which raises when the session is "
        f"already gone and masks the real error: {offenders}"
    )


def test_every_connection_double_answers_the_rollback_contract():
    from graph_scale_dynamics.db.connection import PostgresConnection
    from tests.support.doubles import RollbackCapable

    contract = {"execute", "rollback_if_open", "in_transaction"}
    assert contract <= set(dir(PostgresConnection)) | {"execute"}

    missing = []
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            methods = {item.name for item in node.body if isinstance(item, ast.FunctionDef)}
            if "execute" not in methods:
                continue
            body = ast.unparse(node)
            if "BEGIN" not in body and "ROLLBACK" not in body:
                continue
            bases = {ast.unparse(base) for base in node.bases}
            if "rollback_if_open" in methods or "RollbackCapable" in bases:
                continue
            missing.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno} {node.name}")
    assert not missing, (
        "connection doubles that cannot roll back the way the real connection "
        f"does; mix in tests.support.doubles.RollbackCapable: {missing}"
    )
    assert hasattr(RollbackCapable, "rollback_if_open")


def test_the_lint_config_excludes_exactly_the_frozen_sources():
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ignores = config["tool"]["ruff"]["lint"]["per-file-ignores"]
    frozen = {name for name in json.loads(
        (ROOT / "tests/fixtures/science_freeze.json").read_text())["files"]
        if name.endswith(".py")}

    exempt: set[str] = set()
    for pattern, rules in ignores.items():
        if "F" not in rules or "B" not in rules:
            continue
        exempt |= {p.relative_to(ROOT).as_posix() for p in ROOT.glob(pattern) if p.is_file()}

    assert exempt - frozen == set(), (
        f"lint-exempt files that are not frozen science: {sorted(exempt - frozen)}")
    assert frozen - exempt == set(), (
        f"frozen science the lint config does not exempt: {sorted(frozen - exempt)}")
