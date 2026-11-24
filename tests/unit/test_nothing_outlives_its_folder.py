from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from graph_scale_dynamics.operations import leftovers as L
from graph_scale_dynamics.operations import scratch_namespace as S

REPO = Path(__file__).resolve().parents[2]


def _alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().split()[2]
    except (OSError, IndexError):
        return False
    return state != "Z"


def _wait(predicate, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def _publisher(folder: Path, **kwargs) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "graph_scale_dynamics.operations.power_sidecar", "publish",
                             str(folder)], cwd=str(folder), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True,
                            env=dict(os.environ, PYTHONPATH=str(REPO)), **kwargs)


def _gsd_folder(path: Path) -> Path:
    (path / "graph_scale_dynamics").mkdir(parents=True)
    (path / "main.py").write_text("# a test's folder\n")
    return path


def test_a_publisher_ends_when_its_folder_is_deleted_and_never_makes_it_again(tmp_path):
    folder = tmp_path / "255" / "main"
    folder.mkdir(parents=True)
    process = _publisher(folder)
    try:
        assert _wait(lambda: (folder / "var" / "run" / "cpu-power.json").exists(), 20), "it never published"
        shutil.rmtree(folder)
        assert _wait(lambda: process.poll() is not None, 10), "the publisher outlived its folder"
        time.sleep(1.5)
        assert not folder.exists(), "the folder deleted under the publisher was made again"
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_a_publisher_ends_when_its_folder_is_made_again_and_writes_nothing_into_the_new_one(tmp_path):
    folder = tmp_path / "255" / "main"
    folder.mkdir(parents=True)
    process = _publisher(folder)
    try:
        assert _wait(lambda: (folder / "var" / "run" / "cpu-power.json").exists(), 20), "it never published"
        shutil.rmtree(folder)
        folder.mkdir()
        assert _wait(lambda: process.poll() is not None, 10), "the publisher took a new folder for its own"
        time.sleep(1.5)
        assert list(folder.iterdir()) == [], "the publisher wrote into a folder that is not the one it started in"
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_a_publisher_goes_with_the_run_that_started_it(tmp_path):
    folder = tmp_path / "main"
    folder.mkdir()
    parent = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import os, subprocess, sys, time
        sys.path.insert(0, {str(REPO)!r})
        from graph_scale_dynamics.operations.process_ownership import owned_env
        child = subprocess.Popen([sys.executable, "-m", "graph_scale_dynamics.operations.power_sidecar", "publish",
                                  {str(folder)!r}], cwd={str(folder)!r}, start_new_session=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 env=owned_env(dict(os.environ, PYTHONPATH={str(REPO)!r})))
        print(child.pid, flush=True)
        time.sleep(600)
        """)], stdout=subprocess.PIPE, text=True, start_new_session=True)
    child = None
    try:
        child = int(parent.stdout.readline())
        assert _wait(lambda: (folder / "var" / "run" / "cpu-power.json").exists(), 20), "it never published"
        os.kill(parent.pid, signal.SIGKILL)
        parent.wait(timeout=5)
        assert _wait(lambda: not _alive(child), 10), "the publisher outlived the run that started it"
        assert not (folder / "var" / "run" / "cpu-power.json").exists(), "it left its reading behind"
    finally:
        for pid in (parent.pid, child):
            if pid and _alive(pid):
                os.kill(pid, signal.SIGKILL)


def test_a_holder_ends_when_its_folder_is_gone(tmp_path, monkeypatch):
    if not (hasattr(os, "setns") and hasattr(os, "unshare")):
        pytest.skip("this Python has no os.setns (3.12 or later)")
    monkeypatch.setenv("GSD_SCRATCH_FOLDER_CHECK_SECONDS", "1")
    root = tmp_path / "main"
    root.mkdir()
    try:
        pid = S.ensure_holder(root)
    except RuntimeError as error:
        pytest.skip(f"the scratch holder could not start here: {error}")
    try:
        shutil.rmtree(root)
        assert _wait(lambda: not _alive(pid), 10), "the holder kept a deleted folder's RAM"
    finally:
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)


def _sleeper(cwd: Path, *words: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", *words], cwd=str(cwd),
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)


def test_a_start_ends_what_a_gone_folder_left_and_names_another_live_fleet(tmp_path):
    gone = _gsd_folder(tmp_path / "255" / "main")
    live = _gsd_folder(tmp_path / "254" / "main")
    starting = _gsd_folder(tmp_path / "256" / "main")
    left = _sleeper(gone, "graph_scale_dynamics.services.worker")
    other = _sleeper(live, "graph_scale_dynamics", "main.py", "run")
    yours = subprocess.Popen(["sleep", "600"], cwd=str(gone), start_new_session=True)
    lines: list[str] = []
    try:
        time.sleep(0.3)
        shutil.rmtree(gone)
        rows = {r["pid"]: r for r in L.survey()}
        assert rows[left.pid]["gone"] and rows[left.pid]["folder"] == str(gone)
        assert not rows[other.pid]["gone"] and rows[other.pid]["kind"] == "fleet supervisor"
        assert yours.pid not in rows, "a process is not taken for a fleet's for where it sits alone"
        result = L.at_start(starting, log=lambda line, **_: lines.append(line))
        assert left.wait(timeout=15) is not None, "the gone folder's process was not ended"
        assert other.poll() is None and yours.poll() is None, "a live fleet or the operator's own was touched"
        assert result["others"] == [str(live)]
        assert any(str(gone) in line and "gone" in line for line in lines)
        assert any("another fleet runs in " + str(live) in line for line in lines)
    finally:
        for process in (left, other, yours):
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


def test_a_folder_replaced_under_a_fleet_process_is_gone_and_its_subfolders_are_not(tmp_path):
    folder = _gsd_folder(tmp_path / "main")
    (folder / "var").mkdir()
    at_top = _sleeper(folder, "graph_scale_dynamics")
    inside = _sleeper(folder / "var", "graph_scale_dynamics")
    try:
        time.sleep(0.3)
        shutil.rmtree(folder / "var")
        rows = {r["pid"]: r for r in L.survey()}
        assert not rows[inside.pid]["gone"], "a deleted subfolder of a live folder is not a gone folder"
        assert rows[inside.pid]["folder"] == str(folder)
        shutil.rmtree(folder)
        _gsd_folder(folder)
        rows = {r["pid"]: r for r in L.survey()}
        assert rows[at_top.pid]["gone"], "a process of the folder that was deleted is not the new folder's"
    finally:
        for process in (at_top, inside):
            process.kill()
            process.wait(timeout=5)


def test_a_re_made_folder_s_old_postgres_is_gone_and_its_new_one_is_not(tmp_path):
    postgres = tmp_path / "bin" / "postgres"
    postgres.parent.mkdir()
    shutil.copy2(shutil.which("bash"), postgres)
    folder = _gsd_folder(tmp_path / "main")

    def server() -> subprocess.Popen:
        data = folder / "instance" / "pgdata"
        data.mkdir(parents=True, exist_ok=True)
        return subprocess.Popen([str(postgres), "-c", "sleep 600; true", "-D", str(data)], cwd=str(data),
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
    old = server()
    new = None
    try:
        time.sleep(0.3)
        rows = {r["pid"]: r for r in L.survey()}
        assert rows[old.pid]["kind"] == "postgres" and not rows[old.pid]["gone"], "a live folder's server stays"
        shutil.rmtree(folder)
        _gsd_folder(folder)
        new = server()
        time.sleep(0.3)
        rows = {r["pid"]: r for r in L.survey()}
        assert rows[old.pid]["gone"] and rows[old.pid]["folder"] == str(folder), (
            "the server of the folder that was deleted is not the re-made folder's")
        assert not rows[new.pid]["gone"], "the re-made folder's own server is left alone"
    finally:
        for process in (old, new):
            if process is not None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)


def test_the_tool_lists_by_folder_and_ends_one_folder(tmp_path):
    folder = _gsd_folder(tmp_path / "253" / "main")
    process = _sleeper(folder, "graph_scale_dynamics")
    try:
        time.sleep(0.3)
        listed = subprocess.run([sys.executable, str(REPO / "tools" / "leftovers.py")], capture_output=True,
                                text=True, timeout=60)
        assert str(folder) in listed.stdout and "(live, " in listed.stdout
        ended = subprocess.run([sys.executable, str(REPO / "tools" / "leftovers.py"), "--end", str(folder)],
                               capture_output=True, text=True, timeout=60)
        assert ended.returncode == 0 and "ended 1 of 1" in ended.stdout, ended.stdout
        assert process.wait(timeout=10) is not None
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_another_project_s_python_and_an_archive_naming_the_package_are_left_alone(tmp_path):
    other = tmp_path / "otherproj"
    (other / ".venv" / "bin").mkdir(parents=True)
    interpreter = other / ".venv" / "bin" / "python"
    interpreter.symlink_to(sys.executable)
    downloads = tmp_path / "Downloads" / "graph_scale_dynamics_build_627"
    downloads.mkdir(parents=True)
    starting = _gsd_folder(tmp_path / "256" / "main")
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GSD_")}
    kernel = subprocess.Popen([str(interpreter), "-c", "import subprocess, time; subprocess.Popen(['sleep', '600']); "
                               "time.sleep(600)"], cwd=str(other), env=clean, start_new_session=True,
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    archive = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", str(downloads / "main.py")],
                               cwd=str(downloads), env=clean, start_new_session=True, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.5)
        rows = {r["pid"]: r for r in L.survey()}
        assert kernel.pid not in rows, rows.get(kernel.pid)
        assert archive.pid not in rows, rows.get(archive.pid)
        assert not [r for r in rows.values() if r["ppid"] == kernel.pid], "the kernel's child was taken"
        L.at_start(starting, log=lambda *_a, **_k: None)
        assert kernel.poll() is None and archive.poll() is None, "another project's processes were ended"
    finally:
        for process in (kernel, archive):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def test_a_fleet_interpreter_named_by_its_venv_alone_is_a_fleet_s_only_with_the_fleet_s_environment(tmp_path):
    folder = _gsd_folder(tmp_path / "255" / "main")
    (folder / ".venv" / "bin").mkdir(parents=True)
    interpreter = folder / ".venv" / "bin" / "python"
    interpreter.symlink_to(sys.executable)
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GSD_")}
    marked = subprocess.Popen([str(interpreter), "-c", "import time; time.sleep(600)"], cwd=str(folder),
                              env=dict(clean, GSD_PROJECT_ROOT=str(folder)), start_new_session=True)
    unmarked = subprocess.Popen([str(interpreter), "-c", "import time; time.sleep(600)"], cwd=str(tmp_path),
                                env=clean, start_new_session=True)
    try:
        time.sleep(0.5)
        shutil.rmtree(folder)
        rows = {r["pid"]: r for r in L.survey()}
        assert rows[marked.pid]["gone"] and rows[marked.pid]["folder"] == str(folder)
        assert unmarked.pid not in rows
    finally:
        for process in (marked, unmarked):
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


def test_a_supervisor_started_from_outside_its_folder_is_gone_with_its_folder(tmp_path):
    folder = _gsd_folder(tmp_path / "255" / "main")
    (folder / ".venv" / "bin").mkdir(parents=True)
    interpreter = folder / ".venv" / "bin" / "python"
    interpreter.symlink_to(sys.executable)
    elsewhere = tmp_path / "home"
    elsewhere.mkdir()
    supervisor = subprocess.Popen([str(interpreter), "-c", "import time; time.sleep(600)", str(folder / "main.py"),
                                   "run"], cwd=str(elsewhere), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        time.sleep(0.3)
        rows = {r["pid"]: r for r in L.survey()}
        assert supervisor.pid in rows and not rows[supervisor.pid]["gone"], "its folder is there: not gone"
        shutil.rmtree(folder)
        rows = {r["pid"]: r for r in L.survey()}
        assert rows[supervisor.pid]["gone"] and rows[supervisor.pid]["folder"] == str(folder)
    finally:
        supervisor.kill()
        supervisor.wait(timeout=5)
