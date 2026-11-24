from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from graph_scale_dynamics.reporting import study_bundle as SB

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(not shutil.which("zstd"), reason="the study bundle's codec")


def _members(target: Path) -> list[tarfile.TarInfo]:
    with subprocess.Popen(["zstd", "-dc", str(target)], stdout=subprocess.PIPE) as unzstd:
        with tarfile.open(fileobj=unzstd.stdout, mode="r|") as archive:
            return list(archive)


def test_a_repeated_member_is_a_copy_every_time_and_an_unpacker_reaches_every_file(tmp_path):
    table = json.dumps({"cells": list(range(5000))}).encode("utf-8")
    members = [(f"study_x/campaign_{c}/evidence/probe_calibration.json", table) for c in (1, 2, 3)]
    members += [("study_x/campaign_1/manifest.json", b"{}"), ("study_x/explorer.html", b"<!doctype html>")]
    target = tmp_path / "study.tar.zst"
    SB._write_tar_zstd(target, iter(members))
    listed = _members(target)
    assert [m.name for m in listed] == [name for name, _payload in members], "in the order given"
    assert all(m.type == tarfile.REGTYPE for m in listed), "no hard link, no symlink: plain files only"
    for c in (1, 2, 3):
        repeat = next(m for m in listed if m.name == f"study_x/campaign_{c}/evidence/probe_calibration.json")
        assert repeat.size == len(table), "each repeat carries its own bytes"
    reached = []
    for member in listed:
        if not member.isfile():
            break
        reached.append(member.name)
    assert reached[-1] == "study_x/explorer.html", "an unpacker that stops at the first link reaches the last file"
    out = tmp_path / "out"
    out.mkdir()
    subprocess.run(["tar", "--zstd", "-xf", str(target), "-C", str(out)], check=True)
    for c in (1, 2, 3):
        assert (out / "study_x" / f"campaign_{c}" / "evidence" / "probe_calibration.json").read_bytes() == table
    assert (out / "study_x" / "explorer.html").read_bytes() == b"<!doctype html>"


def test_the_calibration_collector_still_finds_the_table_in_a_study_bundle(tmp_path):
    table = {"contract": "a table", "cells": list(range(3000))}
    payload = json.dumps(table).encode("utf-8")
    target = tmp_path / "study.tar.zst"
    SB._write_tar_zstd(target, iter([(f"s/c{c}/evidence/probe_calibration.json", payload) for c in (1, 2)]))
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import collect_calibration
    finally:
        sys.path.remove(str(ROOT / "tools"))
    assert collect_calibration._from_bundle(target) == table
