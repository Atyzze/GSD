from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from graph_scale_dynamics.operations import scratch_namespace as S
from graph_scale_dynamics.operations import volatile_storage as V

REPO = Path(__file__).resolve().parents[2]
UNSHARE = REPO / "runtime" / "bootstrap" / "linux-amd64" / "unshare"


@pytest.fixture
def folder(tmp_path):
    if not (hasattr(os, "setns") and hasattr(os, "unshare")):
        pytest.skip("this Python has no os.setns (3.12 or later)")
    root = tmp_path / "folder"
    root.mkdir()
    try:
        S.ensure_holder(root)
    except RuntimeError as error:
        pytest.skip(f"the scratch holder could not start here: {error}")
    yield root
    S.stop_holder(root)


def _inside(root: Path, body: str) -> str:
    code = (f"import os, subprocess, sys\nsys.path.insert(0, {str(REPO)!r})\nfrom pathlib import Path\n"
            f"from graph_scale_dynamics.operations import scratch_namespace as S\n"
            f"root = Path({str(root)!r})\nentered = S.enter(root, create=False)\n{body}")
    env = {k: v for k, v in os.environ.items() if k != "GSD_VOLATILE_DIR"}
    done = subprocess.run([sys.executable, "-c", code], cwd=str(root), capture_output=True, text=True,
                          env=env, timeout=60)
    assert done.returncode == 0, done.stderr[-800:]
    return done.stdout.strip()


def test_the_scratch_is_ram_inside_the_folder_and_private_to_the_fleet(folder):
    out = _inside(folder, "print(entered['inside'], S.mounted_here(root), os.environ['GSD_VOLATILE_DIR'])\n"
                          "(S.scratch_dir(root) / 'body').write_text('trajectory')\nprint(os.getcwd())")
    inside, mounted, named, cwd = out.split()
    assert (inside, mounted) == ("True", "True"), out
    assert named == str(folder.resolve() / "var" / "scratch"), "the volatile dir is the folder's"
    assert cwd == str(folder.resolve()), "joining keeps the working directory"
    assert not S.mounted_here(folder) and not (folder / "var" / "scratch" / "body").exists(), \
        "outside the fleet's namespace the directory is empty"


def test_the_contents_outlive_the_processes_that_wrote_them(folder):
    _inside(folder, "(S.scratch_dir(root) / 'body').write_text('kept')")
    assert _inside(folder, "print((S.scratch_dir(root) / 'body').read_text())") == "kept"


def test_the_postgres_runtime_can_make_its_namespace_inside_it(folder):
    if not UNSHARE.exists():
        pytest.skip("no bundled unshare in this tree")
    body = ("(S.scratch_dir(root) / 'tablespace').write_text('spill')\n"
            f"done = subprocess.run([{str(UNSHARE)!r}, '--user', f'--map-user={{os.getuid()}}', "
            "f'--map-group={os.getgid()}', '--fork', '--', 'cat', str(S.scratch_dir(root) / 'tablespace')], "
            "capture_output=True, text=True)\nprint(done.returncode, done.stdout.strip())")
    assert _inside(folder, body) == "0 spill"


def test_scratch_never_leaves_the_folder(monkeypatch):
    monkeypatch.delenv("GSD_VOLATILE_DIR", raising=False)
    monkeypatch.setattr(S, "mounted_here", lambda root: False)
    monkeypatch.setattr(S, "enter", lambda root, create=True: {"inside": False})
    fallback = V.choose_volatile_dir(namespace="scratch-rule", allow_persistent_fallback=True)
    assert fallback["persistent_fallback"] is True and fallback["volatile"] is False
    assert Path(fallback["path"]).is_relative_to(REPO / "var" / "scratch"), fallback["path"]
    refused = V.choose_volatile_dir(namespace="scratch-rule", allow_persistent_fallback=False)
    assert refused["path"] is None, "RAM scratch or an explicit fallback inside the folder, nothing else"


def test_a_threaded_process_is_told_why_it_cannot_join_and_a_fresh_one_joins(folder):
    code = (f"import os, subprocess, sys\nsys.path.insert(0, {str(REPO)!r})\nfrom pathlib import Path\n"
            "import threading, time\n"
            "threading.Thread(target=time.sleep, args=(5,), daemon=True).start()\n"
            f"from graph_scale_dynamics.operations import scratch_namespace as S\n"
            f"print(S.enter(Path({str(folder)!r}), create=False))\n")
    env = {k: v for k, v in os.environ.items() if k != "GSD_VOLATILE_DIR"}
    done = subprocess.run([sys.executable, "-c", code], cwd=str(folder), capture_output=True, text=True,
                          env=env, timeout=60)
    assert done.returncode == 0, done.stderr[-800:]
    assert "'inside': False" in done.stdout and "threads" in done.stdout, done.stdout
    assert _inside(folder, "print(entered['inside'])") == "True"


def test_every_tool_that_joins_the_scratch_joins_before_it_imports_anything_else():
    import ast

    for path in sorted((REPO / "tools").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        joined_at = None
        first_project_import = None
        for node in tree.body:
            text = ast.unparse(node)
            if joined_at is None and "scratch_namespace import enter" in text:
                joined_at = node.lineno
                others = [line for line in text.splitlines() if "import" in line
                          and ("graph_scale_dynamics" in line or "numpy" in line or "psutil" in line)
                          and "scratch_namespace" not in line]
                assert not others, f"{path.name} joins the scratch in the same block as {others}"
                continue
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.Try)) and first_project_import is None and (
                    "graph_scale_dynamics" in text or "numpy" in text or "psutil" in text):
                first_project_import = node.lineno
        if joined_at is None or "enter_scratch(ROOT" not in path.read_text(encoding="utf-8"):
            continue
        assert first_project_import is None or joined_at < first_project_import, (
            f"{path.name} imports the project (line {first_project_import}) before it joins the scratch "
            f"(line {joined_at}); a threaded process cannot join")


def test_no_room_for_the_scratch_is_the_start_s_last_word(monkeypatch):
    from graph_scale_dynamics.operations import scratch_holders as H
    from graph_scale_dynamics.operations import scratch_namespace as N
    others = [{"folder": "/data/projects/GSD/252 base 4 quadrant/main", "used_bytes": 0, "size_bytes": 46 << 30,
               "holder_pid": 669787, "busy": False, "members": [], "moved_from": "/data/projects/GSD/252/main"},
              {"folder": "/data/projects/GSD/254/main", "used_bytes": 0, "size_bytes": 1 << 30, "holder_pid": 1,
               "busy": False, "members": []}]
    monkeypatch.setattr(H, "discover", lambda **_: others)
    monkeypatch.delenv("GSD_ALLOW_PERSISTENT_SCRATCH", raising=False)
    result = {"scratch": "/data/projects/GSD/254/main/var/scratch", "inside": False,
              "reason": "RuntimeError: no room for this folder's scratch: other folders' scratch may grow to 82.0 GiB"}
    said = N.refusal(result)
    assert said.startswith("refusing to start: no room for this folder's RAM scratch (no room for this folder's")
    assert "holder pid 669787" in said and "renamed, moved or trashed" in said
    assert "/data/projects/GSD/254/main/var/scratch" not in said, "the folder starting is not one of the others"
    assert "ends no other folder's scratch" in said and said.endswith("Then start again.")
    assert "stop that folder's fleet" not in said, (
        "a stopped fleet kept its holder until 778 whatever its scratch held, so the words that sent the operator to "
        "stop it were wrong (2026-11-14 13:16)")
    assert "with its scratch empty ends its holder" in said and "`kill <pid>`" in said
    assert N.refusal({**result, "inside": True}) is None
    assert N.refusal({**result, "reason": "GSD_VOLATILE_DIR is set explicitly"}) is None
    monkeypatch.setenv("GSD_ALLOW_PERSISTENT_SCRATCH", "1")
    assert N.refusal(result) is None, "the operator's override for a run on disk"


def test_a_fleet_that_stops_with_its_scratch_empty_ends_its_holder_and_one_with_files_keeps_it(folder):
    kept = _inside(folder, "(S.scratch_dir(root) / 'checkpoint').write_text('the only copy')\n"
                           "r = S.release_when_empty(root)\nprint(r['ended'], r['files'], S.release_line(r))")
    assert kept.startswith("False 1 scratch: kept, 1 file(s)"), kept
    assert S.holder_pid(folder) is not None, "a scratch with a file in it keeps its holder"
    _inside(folder, "(S.scratch_dir(root) / 'checkpoint').unlink()\n(S.scratch_dir(root) / 'empty-dir').mkdir()")
    pid = S.holder_pid(folder)
    ended = _inside(folder, "r = S.release_when_empty(root)\nprint(r['ended'], S.release_line(r))")
    assert ended.startswith(f"True scratch: empty, so its holder (pid {pid}) ended"), ended
    import time
    for _ in range(100):
        if S.holder_pid(folder) is None:
            break
        time.sleep(0.05)
    assert S.holder_pid(folder) is None, "the holder of an empty scratch is gone once its fleet stops"


def test_a_folder_without_a_holder_says_nothing_and_one_not_seen_is_kept():
    assert S.release_line({"held": False}) is None
    unseen = S.release_line({"held": True, "pid": 42, "ended": False, "seen": False})
    assert unseen.startswith("scratch: kept, holder pid 42") and "`kill 42`" in unseen


def test_an_idle_scratch_is_parked_on_the_folder_s_disk_and_moved_back_whole(tmp_path):
    scratch, parked = tmp_path / "scratch", tmp_path / "parked"
    (scratch / "saves" / "job-7").mkdir(parents=True)
    (scratch / "saves" / "job-7" / "checkpoint.bin").write_bytes(b"x" * 4096)
    (scratch / "resume.json").write_text('{"seconds_spent": 12}')
    (scratch / "latest").symlink_to("saves/job-7/checkpoint.bin")
    os.mkfifo(scratch / "a.pipe")
    (scratch / "postgres-runtime").mkdir()
    (scratch / "postgres-runtime" / "postmaster.pid").write_text("4242")
    moved = S.park(scratch, parked)
    assert (moved["files"], moved["dropped"], moved["left"], moved["error"]) == (3, 2, 0, None), moved
    assert not (parked / "postgres-runtime").exists(), "PostgreSQL's runtime is remade at a start, as after a reboot"
    assert moved["bytes"] == 4096 + len('{"seconds_spent": 12}')
    assert list(scratch.iterdir()) == [], "the scratch is empty, directories and all, so its RAM is free"
    assert (parked / "saves" / "job-7" / "checkpoint.bin").read_bytes() == b"x" * 4096
    assert os.readlink(parked / "latest") == "saves/job-7/checkpoint.bin" and not (parked / "a.pipe").exists()
    assert '"files": 3' in (parked / S.PARKED_MANIFEST).read_text()
    back = S.restore(parked, scratch)
    assert (back["files"], back["left"], back["error"]) == (3, 0, None), back
    assert (scratch / "resume.json").read_text() == '{"seconds_spent": 12}'
    assert (scratch / "latest").read_bytes() == b"x" * 4096, "the link still points at its checkpoint"
    assert not parked.exists(), "nothing is left parked once every file is back"


def test_a_file_already_in_the_scratch_is_kept_and_its_parked_copy_stays_parked(tmp_path):
    scratch, parked = tmp_path / "scratch", tmp_path / "parked"
    scratch.mkdir()
    parked.mkdir()
    (parked / "a").write_text("parked")
    (parked / "b").write_text("parked")
    (scratch / "a").write_text("newer")
    back = S.restore(parked, scratch)
    assert (back["files"], back["left"]) == (1, 1) and (scratch / "a").read_text() == "newer"
    assert (scratch / "b").read_text() == "parked" and (parked / "a").exists()


def test_the_holder_counts_the_processes_in_its_namespace_and_no_other(tmp_path):
    proc = tmp_path / "proc"
    for name, ns in (("self", "mnt:[1]"), (str(os.getpid()), "mnt:[1]"), ("2", "mnt:[1]"), ("3", "mnt:[9]")):
        (proc / name / "ns").mkdir(parents=True)
        (proc / name / "ns" / "mnt").symlink_to(ns)
    (proc / "4").mkdir()
    assert S.members_of_my_namespace(proc) == [2]


def _holder_gone(root: Path, seconds: float) -> bool:
    import time
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if S.holder_pid(root) is None:
            return True
        time.sleep(0.1)
    return False


def test_a_holder_left_idle_parks_its_files_ends_and_the_next_start_moves_them_back(tmp_path, monkeypatch):
    if not (hasattr(os, "setns") and hasattr(os, "unshare")):
        pytest.skip("this Python has no os.setns (3.12 or later)")
    monkeypatch.setenv("GSD_SCRATCH_IDLE_GRACE_SECONDS", "2")
    monkeypatch.setenv("GSD_SCRATCH_FOLDER_CHECK_SECONDS", "1")
    root = tmp_path / "folder"
    root.mkdir()
    try:
        S.ensure_holder(root)
    except RuntimeError as error:
        pytest.skip(f"the scratch holder could not start here: {error}")
    try:
        busy = subprocess.Popen([sys.executable, "-c", (
            f"import sys, time\nsys.path.insert(0, {str(REPO)!r})\nfrom pathlib import Path\n"
            f"from graph_scale_dynamics.operations import scratch_namespace as S\n"
            f"root = Path({str(root)!r})\nassert S.enter(root, create=False)['inside']\n"
            f"(S.scratch_dir(root) / 'checkpoint').write_text('the only copy')\nprint('in', flush=True)\n"
            f"time.sleep(6)")], cwd=str(root), stdout=subprocess.PIPE, text=True,
            env={k: v for k, v in os.environ.items() if k != "GSD_VOLATILE_DIR"})
        assert busy.stdout.readline().strip() == "in"
        assert not _holder_gone(root, 4.5), "a holder with a process inside it waits, however long"
        busy.wait(timeout=30)
        assert _holder_gone(root, 20), "once the last process left, the holder ends after its grace"
        assert (S.parked_dir(root) / "checkpoint").read_text() == "the only copy", "its file is on the folder's disk"
        out = subprocess.run([sys.executable, "-c", (
            f"import sys\nsys.path.insert(0, {str(REPO)!r})\nfrom pathlib import Path\n"
            f"from graph_scale_dynamics.operations import scratch_namespace as S\n"
            f"root = Path({str(root)!r})\nentered = S.enter(root)\n"
            f"print(entered['inside'], entered['restored']['files'], (S.scratch_dir(root) / 'checkpoint').read_text())")],
            cwd=str(root), capture_output=True, text=True, timeout=60,
            env={k: v for k, v in os.environ.items() if k != "GSD_VOLATILE_DIR"})
        assert out.stdout.strip() == "True 1 the only copy", out.stderr[-800:]
        assert not S.parked_dir(root).exists(), "the start took every parked file back"
    finally:
        S.stop_holder(root)
