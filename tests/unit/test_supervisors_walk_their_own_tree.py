from __future__ import annotations

import subprocess
import sys
import time

import psutil

from graph_scale_dynamics.operations.subprocesses import descendant_pids, process_tree

TREE = """
import subprocess, sys, time
kids = [subprocess.Popen([sys.executable, '-c', 'import subprocess,sys,time; '
         'g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]); time.sleep(60)'])
        for _ in range(2)]
print('ready', flush=True)
time.sleep(60)
"""


def test_the_tree_is_the_same_one_psutil_finds_and_nothing_else():
    root = subprocess.Popen([sys.executable, "-c", TREE], stdout=subprocess.PIPE, text=True)
    unrelated = subprocess.Popen(["sleep", "60"])
    try:
        root.stdout.readline()
        deadline = time.monotonic() + 10
        expected = set()
        while time.monotonic() < deadline:
            expected = {p.pid for p in psutil.Process(root.pid).children(recursive=True)}
            if len(expected) == 4:
                break
            time.sleep(0.05)
        assert len(expected) == 4, "the fixture must build two children with a grandchild each"
        found = descendant_pids(root.pid)
        assert found is not None, "this kernel offers /proc/<pid>/task/<tid>/children"
        assert set(found) == expected and unrelated.pid not in found
        assert {p.pid for p in process_tree(root.pid)} == expected | {root.pid}
    finally:
        for p in psutil.Process(root.pid).children(recursive=True):
            p.kill()
        root.kill()
        unrelated.kill()
        root.wait()
        unrelated.wait()


def test_a_process_that_is_gone_has_no_tree():
    child = subprocess.Popen(["true"])
    child.wait()
    assert descendant_pids(child.pid) == []
