from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from graph_scale_dynamics.operations import scratch_holders as H
from graph_scale_dynamics.operations import scratch_namespace as N

REPO = Path(__file__).resolve().parents[2]
GIB = 1024 ** 3


class FakeHost:
    def __init__(self, tmp_path: Path):
        self.proc = tmp_path / "proc"
        self.root = tmp_path / "rootfs"
        self.proc.mkdir()
        self.root.mkdir()
        self.usage: dict[str, tuple[int, int]] = {}

    def process(self, pid: int, argv: list[str], ns: str, *, mounts: list[tuple[str, str]] = (), uid=None):
        d = self.proc / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        (d / "comm").write_text(Path(argv[0]).name[:15] + "\n")
        (d / "status").write_text(f"Name:\tx\nUid:\t{os.getuid() if uid is None else uid}\t0\t0\t0\n")
        (d / "ns").mkdir()
        os.symlink(ns, d / "ns" / "mnt")
        os.symlink(self.root, d / "root")
        lines = [f"{30 + i} 1 {device} / {mount} rw,nosuid,nodev - tmpfs tmpfs rw,size=48234496k,mode=700"
                 for i, (device, mount) in enumerate(mounts)]
        lines.append("22 1 8:1 / / rw - ext4 /dev/sda1 rw")
        (d / "mountinfo").write_text("\n".join(lines) + "\n")
        for _device, mount in mounts:
            (self.root / mount.lstrip("/")).mkdir(parents=True, exist_ok=True)

    def holder(self, pid: int, folder: str, ns: str, device: str, used_gib: float):
        scratch = f"{folder}/var/scratch"
        self.process(pid, [sys.executable, "-m", H.HOLDER_MODULE, "hold", folder], ns, mounts=[(device, scratch)])
        self.usage[str((self.root / scratch.lstrip("/")).resolve())] = (46 * GIB, int(used_gib * GIB))

    def statvfs(self, path):
        return self.usage.get(str(Path(path).resolve()), (None, None))

    def kill(self, pid, _signal):
        import shutil
        shutil.rmtree(self.proc / str(pid))


@pytest.fixture
def host(tmp_path, monkeypatch):
    fake = FakeHost(tmp_path)
    monkeypatch.setattr(H, "_statvfs", fake.statvfs)
    fake.holder(377790, "/data/projects/GSD/148/main", "mnt:[4026532148]", "0:148", 23)
    fake.holder(544648, "/data/projects/GSD/149/main", "mnt:[4026532149]", "0:149", 18)
    fake.holder(2432915, "/data/projects/GSD/150/main", "mnt:[4026532150]", "0:150", 11)
    fake.process(2432999, ["/usr/lib/postgresql/16/bin/postgres", "-D", "/data/projects/GSD/150/main/instance"],
                 "mnt:[4026532150]")
    fake.process(4242, ["/usr/bin/fish"], "mnt:[4026531832]")
    return fake


def test_every_folders_scratch_is_found_in_its_own_namespace(host):
    found = H.discover(proc=host.proc)
    assert [r["folder"] for r in found] == ["/data/projects/GSD/148/main", "/data/projects/GSD/149/main",
                                            "/data/projects/GSD/150/main"], "largest first"
    by_folder = {r["folder"]: r for r in found}
    assert by_folder["/data/projects/GSD/148/main"]["holder_pid"] == 377790
    assert by_folder["/data/projects/GSD/148/main"]["used_bytes"] == 23 * GIB
    assert not by_folder["/data/projects/GSD/148/main"]["busy"]
    current = by_folder["/data/projects/GSD/150/main"]
    assert current["busy"] and [m["pid"] for m in current["members"]] == [2432999]
    assert sum(r["used_bytes"] for r in found) == 52 * GIB, "all 52 GB named, none of it visible to df"


def test_another_users_processes_are_not_ours_to_read_or_end(host):
    host.holder(9001, "/data/other/main", "mnt:[4026539001]", "0:901", 5)
    (host.proc / "9001" / "status").write_text("Name:\tx\nUid:\t12345\t0\t0\t0\n")
    assert "/data/other/main" not in {r["folder"] for r in H.discover(proc=host.proc)}


def test_another_folders_scratch_is_named_idle_or_busy_and_none_is_ended(host):
    host.holder(1470, "/data/projects/GSD/147/main", "mnt:[4026532147]", "0:147", 2)
    host.process(1471, [sys.executable, "main.py", "run"], "mnt:[4026532147]")
    before = sorted(p.name for p in host.proc.iterdir())
    lines = []
    result = H.name_other_folders("/data/projects/GSD/150/main", log=lines.append, proc=host.proc)
    assert sorted(p.name for p in host.proc.iterdir()) == before, "no holder of another folder is ended"
    assert [r["folder"] for r in result["kept"]] == ["/data/projects/GSD/150/main"]
    assert sorted(r["folder"] for r in result["others"]) == [f"/data/projects/GSD/{n}/main" for n in (147, 148, 149)]
    warning = next(line for line in lines if "147" in line)
    assert "left alone" in warning and "in use" in warning and "holder pid 1470" in warning and "1471" in warning
    assert all("left alone" in line for line in lines)


def test_only_this_folders_scratch_is_walked(host, monkeypatch):
    walked = []
    monkeypatch.setattr(H, "breakdown", lambda inside: walked.append(str(inside)) or {"entries": {}, "complete": True})
    found = H.discover(proc=host.proc, breakdown_of="/data/projects/GSD/150/main")
    assert [r["folder"] for r in found if "breakdown" in r] == ["/data/projects/GSD/150/main"]
    assert len(walked) == 1 and walked[0].endswith("GSD/150/main/var/scratch")
    assert not any("breakdown" in r for r in H.discover(proc=host.proc))


def test_a_scratch_whose_holder_is_gone_is_busy_while_anything_keeps_it(host):
    host.process(5150, ["/usr/lib/postgresql/16/bin/postgres", "-D", "/data/projects/GSD/146/main/instance"],
                 "mnt:[4026532146]", mounts=[("0:146", "/data/projects/GSD/146/main/var/scratch")])
    host.usage[str((host.root / "data/projects/GSD/146/main/var/scratch").resolve())] = (46 * GIB, 3 * GIB)
    orphan = next(r for r in H.discover(proc=host.proc) if r["folder"].endswith("/146/main"))
    assert orphan["holder_pid"] is None and orphan["busy"]


def test_a_new_scratch_is_sized_so_every_folders_fits_the_host_less_the_floor(monkeypatch, tmp_path):
    monkeypatch.setattr(N, "_mem_total_bytes", lambda: 92 * GIB)
    monkeypatch.delenv("GSD_SCRATCH_SIZE", raising=False)
    monkeypatch.delenv("GSD_HOST_MEMORY_FLOOR_BYTES", raising=False)
    monkeypatch.setattr(H, "committed_bytes", lambda exclude=None, found=None: 0)
    alone = N.planned_size(tmp_path)
    assert alone["size_bytes"] == 46 * GIB and not alone["capped"], "half the RAM, as before, when alone"
    monkeypatch.setattr(H, "committed_bytes", lambda exclude=None, found=None: 2 * 46 * GIB)
    beside_two = N.planned_size(tmp_path)
    assert beside_two["capped"] and beside_two["size_bytes"] < 1 * GIB, "92 less 10 less 92: no room"
    with pytest.raises(RuntimeError, match="scratch_holders.py"):
        N.ensure_holder(tmp_path)
    monkeypatch.setattr(H, "committed_bytes", lambda exclude=None, found=None: 46 * GIB)
    beside_one = N.planned_size(tmp_path)
    assert beside_one["size_bytes"] == 36 * GIB, "92 less the 10 GiB floor less the other 46"
    monkeypatch.setenv("GSD_SCRATCH_SIZE", "512m")
    monkeypatch.setattr(H, "committed_bytes", lambda exclude=None, found=None: 81 * GIB)
    asked_small = N.planned_size(tmp_path)
    assert asked_small["size_bytes"] == 512 * 1024 ** 2 and not asked_small["capped"], "a small ask that fits"


def test_the_size_grammar_is_tmpfss():
    assert N.size_bytes("50%", 92 * GIB) == 46 * GIB
    assert N.size_bytes("46G", 0) == 46 * GIB
    assert N.size_bytes("512m", 0) == 512 * 1024 ** 2
    assert N.size_bytes("4211134464", 0) == 4211134464


@pytest.fixture
def real_holders(tmp_path, monkeypatch):
    if not (hasattr(os, "setns") and hasattr(os, "unshare")):
        pytest.skip("this Python has no os.setns (3.12 or later)")
    monkeypatch.setenv("GSD_SCRATCH_SIZE", "256m")
    started = []

    def start(name: str) -> Path:
        root = tmp_path / name
        root.mkdir()
        try:
            N.ensure_holder(root)
        except RuntimeError as error:
            pytest.skip(f"the scratch holder could not start here: {error}")
        started.append(root)
        return root

    yield start
    for root in started:
        N.stop_holder(root)


def _inside(root: Path, body: str, *, wait: bool = True):
    code = (f"import sys\nsys.path.insert(0, {str(REPO)!r})\nfrom pathlib import Path\n"
            "from graph_scale_dynamics.operations import scratch_namespace as S\n"
            f"root = Path({str(root)!r})\nS.enter(root, create=False)\n{body}")
    env = {k: v for k, v in os.environ.items() if k != "GSD_VOLATILE_DIR"}
    if wait:
        done = subprocess.run([sys.executable, "-c", code], cwd=str(root), capture_output=True, text=True,
                              env=env, timeout=60)
        assert done.returncode == 0, done.stderr[-800:]
        return done.stdout
    return subprocess.Popen([sys.executable, "-c", code], cwd=str(root), env=env)


def test_a_live_idle_holder_of_another_folder_is_left_alone(real_holders):
    old, current = real_holders("old"), real_holders("current")
    _inside(old, "(S.scratch_dir(root) / 'body').write_bytes(b'x' * (64 << 20))")
    record = next(r for r in H.discover() if Path(r["folder"]) == old.resolve())
    assert not record["busy"] and record["used_bytes"] >= 64 << 20
    result = H.name_other_folders(current, log=None,
                                  found=[r for r in H.discover() if Path(r["folder"]) in {old.resolve(), current.resolve()}])
    assert [r["folder"] for r in result["others"]] == [str(old.resolve())]
    assert N.holder_pid(old) is not None and N.holder_pid(current) is not None


def test_a_live_busy_holder_is_not_ended(real_holders):
    busy, current = real_holders("busy"), real_holders("current")
    visitor = _inside(busy, "import time\ntime.sleep(30)", wait=False)
    try:
        deadline = time.monotonic() + 10
        record = None
        while time.monotonic() < deadline:
            record = next(r for r in H.discover() if Path(r["folder"]) == busy.resolve())
            if record["busy"]:
                break
            time.sleep(0.1)
        assert record and record["busy"], "a process that joined makes the namespace busy"
        lines = []
        result = H.name_other_folders(current, log=lines.append,
                                      found=[r for r in H.discover() if Path(r["folder"]) in {busy.resolve(), current.resolve()}])
        assert [r["folder"] for r in result["others"]] == [str(busy.resolve())] and N.holder_pid(busy) is not None
        assert any(str(visitor.pid) in line and str(busy.resolve()) in line for line in lines), lines
    finally:
        visitor.kill()
        visitor.wait(timeout=10)


def test_no_second_holder_starts_for_a_folder_whose_pidfile_was_lost(real_holders):
    root = real_holders("lost")
    first = N.holder_pid(root)
    (root / "var" / "run" / "scratch-holder.json").unlink()
    assert N.holder_pid(root) == first, "found in /proc when the pidfile is gone"
    assert N.ensure_holder(root) == first


def test_a_holder_whose_folder_was_renamed_or_trashed_is_still_its_holder(tmp_path, monkeypatch):
    fake = FakeHost(tmp_path)
    monkeypatch.setattr(H, "_statvfs", fake.statvfs)
    trashed = "/data/.Trash-1000/files/main"
    renamed = "/data/projects/GSD/252 base 4 quadrant T_0, T_inf, d0-16, d0-32/main"
    for pid, named, ns, device, folder in ((4081618, "/data/projects/GSD/251/main", "mnt:[251]", "0:251", trashed),
                                           (669787, "/data/projects/GSD/252/main", "mnt:[252]", "0:252", renamed)):
        fake.process(pid, [sys.executable, "-m", H.HOLDER_MODULE, "hold", named], ns,
                     mounts=[(device, f"{folder}/var/scratch")])
        info = fake.proc / str(pid) / "mountinfo"
        info.write_text(info.read_text().replace(folder, folder.replace(" ", "\\040")))
        fake.usage[str((fake.root / f"{folder}/var/scratch".lstrip("/")).resolve())] = (46 * GIB, 0)
    records = {r["folder"]: r for r in H.discover(proc=fake.proc)}
    assert set(records) == {trashed, renamed}
    for folder, pid, named in ((trashed, 4081618, "/data/projects/GSD/251/main"),
                               (renamed, 669787, "/data/projects/GSD/252/main")):
        record = records[folder]
        assert (record["holder_pid"], record["moved_from"], record["busy"]) == (pid, named, False), record
        assert "renamed, moved or trashed" in H.describe(record)
    result = H.name_other_folders("/data/projects/GSD/253/main", proc=fake.proc, log=lambda *_: None)
    assert sorted(r["folder"] for r in result["others"]) == sorted([trashed, renamed])
    assert (fake.proc / "4081618").exists() and (fake.proc / "669787").exists(), "named, not ended"
    fake.process(669788, [sys.executable, "-m", H.HOLDER_MODULE, "hold", "/data/projects/GSD/252/main"], "mnt:[9]",
                 mounts=[("0:9", f"{renamed}/var/scratch")])
    info = fake.proc / "669788" / "mountinfo"
    info.write_text(info.read_text().replace(renamed, renamed.replace(" ", "\\040")))
    assert N._is_holder_of(669788, Path(renamed), proc=fake.proc)
    assert not N._is_holder_of(669788, Path("/data/projects/GSD/253/main"), proc=fake.proc)


def test_an_idle_holder_is_named_with_the_time_it_ends_itself_and_one_without_a_record_with_none(tmp_path):
    import json as _json

    from graph_scale_dynamics.operations import scratch_holders as H
    folder = tmp_path / "f"
    (folder / "var" / "run").mkdir(parents=True)
    record = {"folder": str(folder), "holder_pid": 7, "busy": False, "used_bytes": 0, "size_bytes": 1 << 30}
    assert H.idle_words(record) == "", "a holder whose run record is not read is not said to end"
    (folder / "var" / "run" / "scratch-holder.json").write_text(_json.dumps(
        {"pid": 7, "idle_grace_seconds": 600, "idle_since_utc": "2026-11-16T12:00:00Z"}))
    assert "idle since 2026-11-16T12:00:00Z, it moves its files to its folder's disk and ends by" in H.describe(record)
    assert H.idle_words(dict(record, busy=True)) == "", "a busy holder ends nothing"
