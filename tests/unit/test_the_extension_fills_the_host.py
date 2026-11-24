from __future__ import annotations


from graph_scale_dynamics.calibration import admission as A
from graph_scale_dynamics.calibration.cells import measure_cell
from graph_scale_dynamics.calibration.suite import _hold_line
from graph_scale_dynamics.observability import shared_memory as S
from graph_scale_dynamics.research.record_report import build_record_sections

GIB = 1024 ** 3


def test_a_family_measured_once_is_priced_from_its_peak_and_the_others_by_the_model():
    cells = {"t:19:0": {"family": "balanced_binary_tree", "n": 1048575, "status": "ok",
                        "peak_rss_bytes": int(1.09 * GIB)},
             "s:64:0": {"family": "periodic_ring", "n": 4096, "status": "ok", "peak_rss_bytes": 5 * GIB}}
    price = A.cell_pricing(cells)
    measured, basis = price("balanced_binary_tree", 4194303)
    assert basis == "measured on this family"
    assert measured < A.predicted_cell_bytes(4194303) / 3
    assert measured > A.PROCESS_INTERCEPT_BYTES + 4 * (1.09 * GIB - A.PROCESS_INTERCEPT_BYTES)
    assert price("periodic_ring", 4194304) == (A.predicted_cell_bytes(4194304), "the 4 KiB per node model")
    assert price("periodic_hypercubic_lattice_4d", 4100625)[1] == "the 4 KiB per node model"


def test_a_cell_records_its_peak_memory():
    cell = measure_cell("periodic_ring", 64, 1, cell_fingerprint="x", science_fingerprint="y")
    assert cell["status"] == "ok" and cell["peak_rss_bytes"] > 10 * 1024 * 1024


def test_a_run_held_by_memory_says_so_in_numbers():
    decision = {"available_bytes": 27.5 * GIB, "reserve_bytes": 10 * GIB, "budget_bytes": 17.5 * GIB}
    line = _hold_line(3, 31, {"key": "balanced_binary_tree:19:0", "n": 1048575}, int(4.9 * GIB),
                      "the 4 KiB per node model", int(14.7 * GIB), decision)
    for needle in ("3 of 31 worker(s) busy", "memory, not CPU", "4.9 GiB", "17.5 GiB", "14.7 GiB"):
        assert needle in line, needle


def test_the_holders_of_shared_memory_are_named(tmp_path, monkeypatch):
    mountinfo = ("22 1 0:20 / /dev/shm rw - tmpfs tmpfs rw\n"
                 "23 1 0:21 / /data/old/var/scratch rw - tmpfs tmpfs rw\n"
                 "24 1 8:1 / / rw - ext4 /dev/sda1 rw\n")

    class Stat:
        f_frsize, f_blocks = 4096, 10 * 262144
        def __init__(self, used):
            self.f_bfree = self.f_blocks - used // 4096

    used = {"/dev/shm": 1 * GIB, "/data/old/var/scratch": 30 * GIB}
    monkeypatch.setattr(S.os, "statvfs", lambda mount: Stat(used[mount]))
    mounts = S.tmpfs_mounts(mountinfo)
    assert [m["mount"] for m in mounts] == ["/data/old/var/scratch", "/dev/shm"]
    assert mounts[0]["used_bytes"] == 30 * GIB

    proc = tmp_path / "proc"
    for pid, argv, shmem_kb in ((101, ["/usr/lib/postgresql/16/bin/postgres", "-D", "/data/old/pg"], 8 * 1024 * 1024),
                                (102, ["postgres: checkpointer"], 8 * 1024 * 1024),
                                (103, ["python3", "tiny.py"], 1024)):
        d = proc / str(pid)
        d.mkdir(parents=True)
        (d / "status").write_text(f"Name:\tx\nRssShmem:\t{shmem_kb} kB\n")
        (d / "cmdline").write_text("\0".join(argv))
    monkeypatch.setattr(S.os, "readlink", lambda path: "/data/old/pg")
    found = S.shmem_processes(str(proc))
    assert len(found) == 1 and found[0]["holder"] == "postgres cluster /data/old/pg"
    assert found[0]["shmem_bytes"] == 8 * GIB and found[0]["processes"] == 2
    lines = S.summary_lines({"tmpfs_mounts": mounts, "processes": found})
    assert "tmpfs /data/old/var/scratch: 30.0 GiB in files" in lines
    assert "postgres cluster /data/old/pg: 8.0 GiB shared (2 process(es))" in lines


def test_report_28_reads_the_cost_split_per_contract():
    old = {"child": {"cpu_seconds": 4.0, "io": {"write_bytes": 100}},
           "bookkeeping": {"cpu_seconds": 0.1, "io": {"write_bytes": 100}}}
    new = {"contract": "attempt-cost-2", "child": {"cpu_seconds": 4.0, "io": {"write_bytes": 100}},
           "bookkeeping": {"cpu_seconds": 0.1, "io": {"write_bytes": 7}}}
    costs = build_record_sections({"costs": [{"n": 1024, "cost": old}, {"n": 1024, "cost": new}]})["cost_per_attempt"]
    assert set(costs["by_contract"]) == {"attempt-cost-1", "attempt-cost-2"}
    assert costs["contract_read"] == "attempt-cost-2"
    assert costs["by_rung"]["1024"]["bookkeeping_write_bytes"]["median"] == 7.0
    assert costs["by_contract"]["attempt-cost-1"]["by_rung"]["1024"]["bookkeeping_write_bytes"]["median"] == 100.0
