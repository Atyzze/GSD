from __future__ import annotations

import ast
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from graph_scale_dynamics.operations import process_ownership
from graph_scale_dynamics.operations.process_ownership import (
    OWNER_PID_ENV, interrupt_on, owned_env, stop_process_group,
)

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"),
                                reason="the owner-death signal is a Linux facility")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return state != "Z"


def _wait_gone(pid: int, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return not _alive(pid)


def _read_pid(path: Path, seconds: float = 15.0) -> int:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        text = path.read_text().strip() if path.exists() else ""
        if text.endswith("\n") or text.isdigit():
            return int(text)
        time.sleep(0.05)
    raise AssertionError(f"{path} never received a pid")


def _env() -> dict[str, str]:
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    env.pop(OWNER_PID_ENV, None)
    return env


OWNER = textwrap.dedent("""
    import os, subprocess, sys, time
    from graph_scale_dynamics.operations.process_ownership import owned_env
    child_code = sys.argv[2]
    env = owned_env() if sys.argv[3] == "owned" else dict(os.environ)
    child = subprocess.Popen([sys.executable, "-c", child_code], env=env, start_new_session=True)
    open(sys.argv[1], "w").write(str(child.pid))
    time.sleep(120)
""")

ARMED_CHILD = textwrap.dedent("""
    import os, subprocess, sys, time
    from graph_scale_dynamics.operations.process_ownership import die_with_owner, OWNER_PID_ENV
    state = die_with_owner()
    grandchild = subprocess.Popen([sys.executable, "-c", "import os, time; "
        "print(os.environ.get('GSD_OWNER_PID', 'absent'), flush=True); time.sleep(120)"],
        stdout=open(os.environ["PROBE_OUT"], "w"), start_new_session=True)
    open(os.environ["PROBE_STATE"], "w").write(state + " " + str(grandchild.pid))
    time.sleep(120)
""")


def _start_owner(tmp_path: Path, owned: bool) -> tuple[subprocess.Popen, int]:
    pid_file = tmp_path / "child.pid"
    env = _env()
    env["PROBE_OUT"] = str(tmp_path / "grandchild.out")
    env["PROBE_STATE"] = str(tmp_path / "state")
    owner = subprocess.Popen([sys.executable, "-c", OWNER, str(pid_file), ARMED_CHILD,
                              "owned" if owned else "plain"], env=env)
    return owner, _read_pid(pid_file)


def _state(tmp_path: Path) -> tuple[str, int]:
    path = tmp_path / "state"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not (path.exists() and path.read_text().strip()):
        time.sleep(0.05)
    state, grandchild = path.read_text().split()
    return state, int(grandchild)


def _cleanup(*pids: int) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def test_an_owned_child_dies_when_its_owner_is_killed_outright(tmp_path):
    owner, child = _start_owner(tmp_path, owned=True)
    state, grandchild = _state(tmp_path)
    try:
        assert state == "armed"
        owner.kill()
        owner.wait(timeout=5)
        assert _wait_gone(child), "the child outlived an owner killed with SIGKILL"
    finally:
        _cleanup(child, grandchild)


def test_the_owner_is_not_inherited_by_a_grandchild(tmp_path):
    owner, child = _start_owner(tmp_path, owned=True)
    _, grandchild = _state(tmp_path)
    try:
        out = tmp_path / "grandchild.out"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not out.read_text().strip():
            time.sleep(0.05)
        assert out.read_text().strip() == "absent", (
            "a grandchild found its grandparent named as its owner and would take itself for an orphan")
    finally:
        owner.kill()
        owner.wait(timeout=5)
        _cleanup(child, grandchild)


def test_a_process_nobody_owns_keeps_running(tmp_path):
    owner, child = _start_owner(tmp_path, owned=False)
    state, grandchild = _state(tmp_path)
    try:
        assert state == "unowned"
        owner.kill()
        owner.wait(timeout=5)
        time.sleep(0.5)
        assert _alive(child), "a process with no owner was killed with the shell that started it"
    finally:
        _cleanup(child, grandchild)


def test_a_child_whose_owner_is_already_gone_stops_itself():
    env = _env()
    env[OWNER_PID_ENV] = "1" if os.getppid() != 1 else str(os.getpid() + 999999)
    result = subprocess.run(
        [sys.executable, "-c", "import time\nfrom graph_scale_dynamics.operations.process_ownership "
         "import die_with_owner\ndie_with_owner()\ntime.sleep(30)"],
        env=env, timeout=20)
    assert result.returncode == -signal.SIGTERM


def test_owned_env_names_the_caller_and_copies_the_rest():
    env = owned_env({"KEEP": "1", OWNER_PID_ENV: "12345"})
    assert env == {"KEEP": "1", OWNER_PID_ENV: str(os.getpid())}


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP])
def test_a_stop_signal_unwinds_and_the_handler_is_restored(sig):
    before = signal.getsignal(sig)
    ran_finally = []
    with pytest.raises(KeyboardInterrupt):
        with interrupt_on():
            try:
                os.kill(os.getpid(), sig)
                time.sleep(5)
            finally:
                ran_finally.append(True)
    assert ran_finally == [True]
    assert signal.getsignal(sig) == before


def _entry_modules() -> set[str]:
    found: set[str] = set()
    sources = [ROOT / "main.py", ROOT / "graph_scale_dynamics/services/worker/main.py",
               ROOT / "graph_scale_dynamics/services/analyzer/main.py"]
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value.startswith("graph_scale_dynamics.services.")
                    and (node.value.endswith(".main") or node.value.endswith(".child"))):
                found.add(node.value)
    return found


def test_every_launched_entry_point_arms_itself_before_it_runs():
    modules = _entry_modules()
    assert "graph_scale_dynamics.services.executor.main" in modules
    assert "graph_scale_dynamics.services.worker.child" in modules
    unarmed = []
    for module in sorted(modules):
        path = ROOT / (module.replace(".", "/") + ".py")
        tree = ast.parse(path.read_text())
        block = next((node for node in tree.body if isinstance(node, ast.If)
                      and "__name__" in ast.unparse(node.test)), None)
        calls = [ast.unparse(stmt) for stmt in (block.body if block else [])]
        armed = [i for i, call in enumerate(calls) if call == "die_with_owner()"]
        runs = [i for i, call in enumerate(calls) if "main(" in call]
        if not armed or not runs or armed[0] > runs[0]:
            unarmed.append(module)
    assert not unarmed, f"these entry points do not arm themselves before running: {unarmed}"


LANE_TEST = textwrap.dedent("""
    import os, subprocess, sys, time
    def test_holds_a_process_in_the_lane():
        # Like the vertical slice: a process the test starts, in the lane's group.
        keeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        open(os.environ["LANE_PIDS"], "w").write(f"{os.getpid()} {keeper.pid}")
        time.sleep(120)
""")

LANE_DRIVER = textwrap.dedent("""
    import sys
    sys.path.insert(0, sys.argv[1])
    import tools.test_suite as suite
    suite.LANES["all"] = [sys.argv[2], "-p", "no:cacheprovider"]
    raise SystemExit(suite.main(["--lane", "all"]))
""")


def _start_lane(tmp_path: Path) -> tuple[subprocess.Popen, int, int]:
    test_file = tmp_path / "test_lane_holds.py"
    test_file.write_text(LANE_TEST)
    pids = tmp_path / "lane.pids"
    env = _env()
    env["LANE_PIDS"] = str(pids)
    runner = subprocess.Popen([sys.executable, "-c", LANE_DRIVER, str(ROOT), str(test_file)],
                              cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not (pids.exists() and pids.read_text().strip()):
        time.sleep(0.1)
    pytest_pid, keeper = (int(value) for value in pids.read_text().split())
    return runner, pytest_pid, keeper


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP, signal.SIGINT])
def test_a_stopped_lane_leaves_nothing_behind(tmp_path, sig):
    runner, pytest_pid, keeper = _start_lane(tmp_path)
    try:
        runner.send_signal(sig)
        assert runner.wait(timeout=60) == 130
        assert _wait_gone(pytest_pid), "pytest outlived the lane runner"
        assert _wait_gone(keeper), "a process a test started outlived the lane runner"
    finally:
        _cleanup(runner.pid, pytest_pid, keeper)


def test_a_release_killed_outright_takes_its_lane_with_it(tmp_path):
    lane_driver = tmp_path / "lane_driver.py"
    lane_driver.write_text(textwrap.dedent("""
        import sys
        sys.path.insert(0, sys.argv[1])
        from graph_scale_dynamics.operations.process_ownership import die_with_owner
        die_with_owner()
        import tools.test_suite as suite
        suite.LANES["all"] = [sys.argv[2], "-p", "no:cacheprovider"]
        raise SystemExit(suite.main(["--lane", "all"]))
    """))
    test_file = tmp_path / "test_lane_holds.py"
    test_file.write_text(LANE_TEST)
    pids = tmp_path / "lane.pids"
    env = _env()
    env["LANE_PIDS"] = str(pids)
    release = subprocess.Popen([sys.executable, "-c", (
        "import sys; sys.path.insert(0, sys.argv[1]); import tools.package_release as r; "
        "r.run_gate_and_capture_summary([sys.executable, sys.argv[2], sys.argv[1], sys.argv[3]])"),
        str(ROOT), str(lane_driver), str(test_file)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not (pids.exists() and pids.read_text().strip()):
            time.sleep(0.1)
        pytest_pid, keeper = (int(value) for value in pids.read_text().split())
        release.kill()
        release.wait(timeout=5)
        assert _wait_gone(pytest_pid, 60), "the lane outlived a release killed with SIGKILL"
        assert _wait_gone(keeper, 60), "a process in the lane outlived a release killed with SIGKILL"
    finally:
        _cleanup(release.pid, *(int(v) for v in (pids.read_text().split() if pids.exists() else [])))


def test_stop_process_group_escalates_past_a_group_that_ignores_the_polite_signals(tmp_path):
    stubborn = subprocess.Popen([sys.executable, "-c", (
        "import signal, subprocess, sys, time\n"
        "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "subprocess.Popen([sys.executable, '-c', 'import signal, time; "
        "signal.signal(signal.SIGINT, signal.SIG_IGN); signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "time.sleep(120)'])\n"
        "print('ready', flush=True)\n"
        "time.sleep(120)\n")], start_new_session=True, stdout=subprocess.PIPE, text=True)
    try:
        assert stubborn.stdout.readline().strip() == "ready"
        said: list[str] = []
        assert stop_process_group(stubborn, grace=1.0, log=said.append) == -signal.SIGKILL
        assert not process_ownership._group_alive(stubborn.pid)
        assert any("SIGTERM" in line for line in said), said
    finally:
        if stubborn.poll() is None:
            stubborn.kill()
