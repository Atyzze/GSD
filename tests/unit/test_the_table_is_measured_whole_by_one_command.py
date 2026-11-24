from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from graph_scale_dynamics.calibration import contract as C
from graph_scale_dynamics.calibration import fingerprint as FP
from graph_scale_dynamics.calibration import start_reading
from graph_scale_dynamics.calibration import table as T
from graph_scale_dynamics.calibration.cells import plan_cells, plan_extension_cells, suite_families

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "probe_calibration.py"
PAST_THE_LADDERS = {"periodic_ring": (100,)}
AS_A_KEYPRESS_REACHES_IT = ("import os, signal, sys; signal.signal(signal.SIGINT, signal.SIG_DFL); "
                            "os.execv(sys.executable, [sys.executable] + sys.argv[1:])")


@pytest.fixture()
def tools():
    from tools import collect_calibration, probe_calibration
    return probe_calibration, collect_calibration


@pytest.fixture()
def a_small_whole_table(monkeypatch, tmp_path):
    folder = tmp_path / "folder"
    monkeypatch.setattr(C, "MAX_NODES", 130)
    monkeypatch.setattr(C, "AUTHORITATIVE_SEEDS", 1)
    monkeypatch.setattr(C, "EXTENSION_SEEDS", 1)
    monkeypatch.setattr(C, "LADDER_EXTENSIONS", dict(PAST_THE_LADDERS))
    monkeypatch.setattr(C, "durable_artifact_path", lambda root=None: folder / C.DURABLE_DIR / C.DURABLE_NAME)
    monkeypatch.delenv(C.ENV_PROFILE, raising=False)
    monkeypatch.delenv(C.ENV_INTEGRATION_TEST, raising=False)
    return folder


def _measured(tools, folder: Path) -> tuple[int, list[str]]:
    said: list[str] = []
    code = tools[0].measure_the_table_whole(ROOT, folder / "var", workers=0, log=said.append)
    return code, said


def test_one_command_measures_the_table_whole_collects_it_and_says_the_verdict(tools, a_small_whole_table):
    folder = a_small_whole_table
    ladders = plan_cells(suite_families(), seeds=1)
    past = plan_extension_cells(suite_families(), seeds=1)
    assert len(past) == 1 and len(ladders) > 10
    code, said = _measured(tools, folder)
    assert code == 0, said[-8:]
    table = json.loads((folder / C.DURABLE_DIR / C.DURABLE_NAME).read_text())
    assert table["authoritative"] is True and table["profile"]["name"] == "full"
    assert table["suite_version"] == C.SUITE_VERSION
    assert set(table["cells"]) == {task["key"] for task in ladders + past}
    assert all(cell["status"] == "ok" for cell in table["cells"].values())
    packed = Path(said[-1])
    assert packed.parent == folder and packed.name.startswith("calibration_") and packed.suffix == ".zip"
    assert said[-2] == "Send this one file, and start nothing else:"
    assert any(line.startswith(f"The table is whole: {len(ladders):,} cells on the ladders and 1 past them")
               for line in said), said[-8:]
    assert any(line.startswith("The gate passes: ") for line in said)
    with zipfile.ZipFile(packed) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        assert json.loads(bundle.read("probe_calibration.json"))["cells"] == table["cells"]
    assert manifest["gate_complete"] and manifest["extension_complete"]
    assert manifest["in_plain_words"] == said[-2 - len(manifest["in_plain_words"]):-2]
    assert manifest["whole_table"] == {"cells": len(ladders), "current": len(ladders), "seeds": 1}


def test_typed_again_it_measures_no_cell_again(tools, a_small_whole_table):
    folder = a_small_whole_table
    assert _measured(tools, folder)[0] == 0
    first = json.loads((folder / C.DURABLE_DIR / C.DURABLE_NAME).read_text())["cells"]
    code, said = _measured(tools, folder)
    again = json.loads((folder / C.DURABLE_DIR / C.DURABLE_NAME).read_text())["cells"]
    assert code == 0 and again == first, "every cell as it was, its time of measuring among them"
    total = len(first)
    assert f"   measured and kept so far: {total:,} of {total:,} cells" in said
    assert any("computing 0" in line for line in said)
    assert said[-2] == "Send this one file, and start nothing else:"


def test_a_gate_that_fails_names_the_family_the_probe_and_the_size_and_keeps_the_table(
        tools, a_small_whole_table, monkeypatch):
    from graph_scale_dynamics.measurements import calibration
    folder = a_small_whole_table
    monkeypatch.setattr(calibration, "ladder_tolerance", lambda family, channel, n: (
        1e-9 if (family, channel, int(n)) == ("periodic_ring", "d_s", 128) else None))
    code, said = _measured(tools, folder)
    assert code == 1
    at = said.index("The gate does not pass, in 1 place(s):")
    assert said[at + 1].startswith("    periodic_ring, d_s at 128 nodes: ") and "held within 1e-09" in said[at + 1]
    assert said[at + 2] == "The table is kept as measured: no cell is measured again, and nothing in it is changed."
    assert said[-2] == "Send this one file, and start nothing else:" and Path(said[-1]).is_file()
    first = json.loads((folder / C.DURABLE_DIR / C.DURABLE_NAME).read_text())["cells"]
    code, said = _measured(tools, folder)
    assert code == 1 and json.loads((folder / C.DURABLE_DIR / C.DURABLE_NAME).read_text())["cells"] == first
    assert "The gate does not pass, in 1 place(s):" in said


def test_a_cell_that_failed_is_named_and_measured_again_by_the_same_command(tools, a_small_whole_table, monkeypatch):
    from graph_scale_dynamics.calibration import suite
    folder = a_small_whole_table
    measure = suite._worker_measure

    def one_fails(task: dict) -> dict:
        cell = measure(task)
        if (cell["family"], cell["n"]) == ("periodic_ring", 64):
            cell = dict(cell, status="failed", error="MemoryError: stood in for by the test", channels={})
        return cell

    monkeypatch.setattr(suite, "_worker_measure", one_fails)
    code, said = _measured(tools, folder)
    assert code == 1
    assert "The table is not whole: 1 of its cells are not measured:" in said
    assert "    periodic_ring:64:0 (64 nodes): failed: MemoryError: stood in for by the test" in said
    assert said[-2].startswith("`uv run python tools/probe_calibration.py --whole` measures what is missing.")
    monkeypatch.setattr(suite, "_worker_measure", measure)
    code, said = _measured(tools, folder)
    assert code == 0 and any(line.endswith("computing 1 inline") for line in said), said[:8]
    assert said[-2] == "Send this one file, and start nothing else:"


ANOTHER_SUITE_S = json.dumps({"contract": C.CONTRACT, "suite_version": C.SUITE_VERSION - 1, "cells": {
    "periodic_ring:64:0": {"family": "periodic_ring", "parameter": 64, "seed": 0, "n": 64, "status": "ok",
                           "kept": "as it was"}}})


@pytest.mark.parametrize("found", [ANOTHER_SUITE_S, '{"cells": {"periodic_ring:64:0": 1}, "torn'],
                         ids=["another suite's", "torn"])
def test_a_table_it_cannot_go_on_from_is_set_aside_byte_for_byte_and_a_new_one_measured(
        tools, a_small_whole_table, found):
    folder = a_small_whole_table
    table = folder / C.DURABLE_DIR / C.DURABLE_NAME
    table.parent.mkdir(parents=True)
    table.write_text(found)
    code, said = _measured(tools, folder)
    assert code == 0
    kept = sorted(C.history_dir(folder / "var").glob("unusable_table_*.json"))
    assert len(kept) == 1 and kept[0].read_text() == found
    assert any(str(kept[0]) in line and "a new table is measured in its place" in line for line in said)
    measured = json.loads(table.read_text())
    assert measured["suite_version"] == C.SUITE_VERSION and "kept" not in measured["cells"]["periodic_ring:64:0"]
    assert measured["cells"]["periodic_ring:64:0"]["status"] == "ok"


def test_a_table_it_cannot_set_aside_is_left_as_it_is(tools, a_small_whole_table, monkeypatch):
    folder = a_small_whole_table
    table = folder / C.DURABLE_DIR / C.DURABLE_NAME
    table.parent.mkdir(parents=True)
    table.write_text(ANOTHER_SUITE_S)
    monkeypatch.setattr(tools[0], "_set_aside", lambda table, history: None)
    code, said = _measured(tools, folder)
    assert code == 2 and table.read_text() == ANOTHER_SUITE_S
    assert "move it away and type the command again" in said[-1]


def test_whole_takes_no_option_that_would_make_another_table(tools, capsys):
    for extra in (["--seeds", "3"], ["--max-nodes", "64"], ["--families", "periodic_ring"], ["--recompute"],
                  ["--out", "elsewhere.json"], ["--probe-ladders"], ["--extend"], ["--json"]):
        with pytest.raises(SystemExit) as refused:
            tools[0].main(["--whole", *extra])
        assert refused.value.code == 2
        assert f"not {extra[0]}" in capsys.readouterr().err


def _a_whole_table_of_this_suite() -> dict:
    families = suite_families()
    document = T.new_table(families, seeds=C.AUTHORITATIVE_SEEDS, max_nodes=None, authoritative=True,
                           profile="full", root=str(ROOT))
    document["profile"]["families"] = [family["name"] for family in families]
    for task in (plan_cells(families, seeds=C.AUTHORITATIVE_SEEDS)
                 + plan_extension_cells(families, seeds=C.EXTENSION_SEEDS)):
        cell = {"family": task["family"], "parameter": task["parameter"], "seed": task["seed"], "n": task["n"],
                "status": "ok", "cell_fingerprint": FP.cell_fingerprint(task["family"], str(ROOT)),
                "channels": {}, "elapsed_seconds": 36.0}
        if start_reading.wanted(task["family"], task["n"], task["seed"]):
            cell["start"] = {"contract": start_reading.CONTRACT, "fingerprint": start_reading.fingerprint()}
        document["cells"][task["key"]] = cell
    return document


def test_the_seed_is_a_whole_table_of_this_suite_or_it_is_refused(tools, tmp_path):
    collector = tools[1]
    whole = _a_whole_table_of_this_suite()
    assert len(whole["cells"]) == 2560 + 24
    table = tmp_path / "probe_calibration.json"
    target = tmp_path / "seed_table.json"

    table.write_text(json.dumps(whole))
    installed, summary = collector.install_seed(collector.collect(ROOT, tmp_path, table_path=table), ROOT,
                                                target=target)
    assert installed == target and summary["gate_complete"] and summary["extension_complete"]
    assert summary["whole_table"] == {"cells": 2560, "current": 2560, "seeds": 10}
    assert json.loads(target.read_text())["cells"] == whole["cells"]

    reduced = json.loads(json.dumps(whole))
    kept = {task["key"] for task in plan_cells(suite_families(), seeds=2, max_nodes=65536)}
    reduced["cells"] = {key: cell for key, cell in reduced["cells"].items() if key in kept}
    reduced["authoritative"] = False
    reduced["profile"] = dict(reduced["profile"], name="reduced", seeds=2, max_nodes=65536)
    table.write_text(json.dumps(reduced))
    packed = collector.collect(ROOT, tmp_path, table_path=table)
    with pytest.raises(SystemExit, match="a reduced table: 416 of the whole table's 2,560 cells"):
        collector.install_seed(packed, ROOT, target=target)
    assert collector.install_seed(packed, ROOT, partial=True, target=target)[0] == target

    for unwanted, why in (
            (dict(whole, suite_version=C.SUITE_VERSION - 1), f"a suite {C.SUITE_VERSION - 1} table"),
            (dict(whole, contract="another-contract"), "not a gsd-calibration-table-1 table"),
            (dict(whole, cells={key: dict(cell, cell_fingerprint="measured by other code")
                                for key, cell in whole["cells"].items()}), "gate cells not current here")):
        table.write_text(json.dumps(unwanted))
        with pytest.raises(SystemExit, match=why):
            collector.install_seed(table, ROOT, target=target)


def test_a_cell_that_is_not_current_says_which_part_of_it_is_owed(tools):
    collector = tools[1]
    whole = _a_whole_table_of_this_suite()
    assert collector.cells_not_measured(whole, ROOT) == []
    assert collector.in_plain_words(whole, ROOT)[0].startswith("The table is whole: 2,560 cells on the ladders and 24 ")
    start = "periodic_face_centred_cubic_lattice:1048576:0"
    assert start_reading.wanted("periodic_face_centred_cubic_lattice", 1048576, 0)
    whole["cells"][start]["start"] = {"contract": start_reading.CONTRACT, "fingerprint": start_reading.fingerprint(),
                                      "error": "MemoryError: stood in for by the test"}
    whole["cells"]["periodic_ring:64:3"]["cell_fingerprint"] = "another tree's"
    whole["cells"]["periodic_ring:64:4"].update(status="failed", error="its process ended with exit code -9")
    del whole["cells"]["uniform_random_tree:1048576:2"]
    whole["extension_blocked_cells"] = [{"key": "uniform_random_tree:1048576:2", "n": 1048576,
                                         "reason": "ended 2 times: the host could not hold it"}]
    assert collector.cells_not_measured(whole, ROOT) == [
        "periodic_ring:64:3 (64 nodes): measured by other code than this tree's",
        "periodic_ring:64:4 (64 nodes): failed: its process ended with exit code -9",
        "periodic_face_centred_cubic_lattice:1048576:0 (1,048,576 nodes): its probes are measured and its reading as "
        "a start is not: MemoryError: stood in for by the test",
        "uniform_random_tree:1048576:2 (1,048,576 nodes): held back: ended 2 times: the host could not hold it"]
    said = collector.in_plain_words(whole, ROOT)
    assert said[0] == "The table is not whole: 4 of its cells are not measured:"
    assert said[-1] == "Nothing measured so far fails the gate; the gate's verdict needs the table whole."


def test_each_way_a_reading_can_fail_the_gate_is_said_in_words(tools):
    from graph_scale_dynamics.measurements.calibration import ladder_tolerance
    collector = tools[1]
    families = suite_families(["periodic_ring", "random_4_regular"])
    held = {channel: ladder_tolerance("periodic_ring", channel, 4096) for channel in C.CHANNELS}
    assert all(tolerance is not None for tolerance in held.values()), "the rule holds a ring of 4,096 on every probe"

    def cell(family: str, seed: int, readings: dict) -> dict:
        return {"family": family, "parameter": 4096, "seed": seed, "n": 4096, "status": "ok",
                "cell_fingerprint": FP.cell_fingerprint(family, str(ROOT)), "elapsed_seconds": 1.0,
                "channels": {channel: {"valid": value is not None, "value": value, "se": None,
                                       "reason": None if value is not None else "refused by the test"}
                             for channel, value in readings.items()}}

    document = T.new_table(families, seeds=3, max_nodes=4096, authoritative=False, profile="reduced", root=str(ROOT))
    document["profile"]["families"] = [family["name"] for family in families]
    ring = [{"d_s": 1.0, "d_V": 1.9, "d_B": None, "d_w": 2.0},
            {"d_s": 1.0, "d_V": 1.9, "d_B": None, "d_w": None},
            {"d_s": 1.0, "d_V": 1.9, "d_B": None, "d_w": None}]
    random = [{"d_s": None, "d_V": None, "d_B": None, "d_w": 2.5},
              {"d_s": None, "d_V": None, "d_B": None, "d_w": None},
              {"d_s": None, "d_V": None, "d_B": None, "d_w": None}]
    for seed in range(3):
        document["cells"][f"periodic_ring:4096:{seed}"] = cell("periodic_ring", seed, ring[seed])
        document["cells"][f"random_4_regular:4096:{seed}"] = cell("random_4_regular", seed, random[seed])
    T.refresh(document, families, seeds=3, max_nodes=4096, root=str(ROOT))
    judged = collector.rows_judged(document)
    assert judged["failing"] == [
        f"periodic_ring, d_B at 4,096 nodes: refused on every seed where 1 is held within {held['d_B']:g}",
        f"periodic_ring, d_V at 4,096 nodes: reads 1.9 where 1 is held within {held['d_V']:g}",
        f"periodic_ring, d_w at 4,096 nodes: read on 1 of 3 seeds where 2 is held within {held['d_w']:g}, fewer "
        "than the 50% that must read",
        "random_4_regular, d_w at 4,096 nodes: read on 1 of 3 seeds (2.5) where every probe must refuse from 4,096 "
        "nodes"]
    assert judged["held_and_inside"] == 1 and judged["refusals_required_and_held"] == 3 and judged["shown"] == 0
    said = collector.in_plain_words(document, ROOT)
    assert said[0].startswith("The table is not whole: ")
    assert "The gate does not pass, in 4 place(s):" in said


def _typed(var: Path, **settings) -> subprocess.Popen:
    env = {key: value for key, value in os.environ.items() if key != C.ENV_INTEGRATION_TEST}
    env.update({C.ENV_PROFILE: C.PROFILE_REDUCED, C.ENV_REDUCED_SEEDS: "1", C.ENV_REDUCED_MAX_NODES: "260",
                "PYTHONUNBUFFERED": "1", **settings})
    return subprocess.Popen([sys.executable, "-c", AS_A_KEYPRESS_REACHES_IT, str(TOOL), "--whole", "--workers", "2",
                             "--var", str(var)], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, start_new_session=True)


def _cells(var: Path) -> dict:
    try:
        return json.loads(C.non_authoritative_artifact_path(var).read_text())["cells"]
    except (OSError, ValueError):
        return {}


def _stopped_part_way(var: Path, stop) -> tuple[subprocess.Popen, str, dict]:
    run = _typed(var)
    try:
        deadline = time.monotonic() + 240
        while len(_cells(var)) < 6 and run.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert run.poll() is None, run.stdout.read()
        stop(run)
        said = run.communicate(timeout=120)[0]
    finally:
        if run.poll() is None:
            os.killpg(run.pid, signal.SIGKILL)
            run.wait(timeout=30)
    assert "Traceback" not in said and "KeyboardInterrupt" not in said, said
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            os.killpg(run.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("a process of the stopped run is still alive")
    return run, said, _cells(var)


def test_ctrl_c_keeps_every_finished_cell_and_the_same_command_goes_on(tmp_path):
    var = tmp_path / "var"
    total = len(plan_cells(suite_families(), seeds=1, max_nodes=260))
    run, said, kept = _stopped_part_way(var, lambda run: os.killpg(run.pid, signal.SIGINT))
    assert run.returncode == 130, said
    assert 6 <= len(kept) < total
    assert "Stopped by Ctrl-C after " in said and f" {len(kept):,} of {total:,} cells are measured and kept in " in said
    assert said.rstrip().endswith("Type the same command to go on: it measures no finished cell again.")

    again = _typed(var)
    try:
        said = again.communicate(timeout=480)[0]
    finally:
        if again.poll() is None:
            os.killpg(again.pid, signal.SIGKILL)
    assert again.returncode == 0, said
    assert f"calibration: {len(kept)} of {total} cells current; computing {total - len(kept)} with 2 worker(s)" in said
    whole = _cells(var)
    assert len(whole) == total and all(whole[key] == cell for key, cell in kept.items()), "no finished cell twice"
    lines = said.rstrip().splitlines()
    packed = Path(lines[-1])
    assert packed.parent == C.non_authoritative_artifact_path(var).parent and packed.is_file()
    assert lines[-2] == "A rehearsal has nothing to send. Its file, made as the whole table's is:"
    assert not list(ROOT.glob("calibration_*.zip")), "a rehearsal leaves nothing in the tree"


def test_ended_from_outside_it_stops_as_cleanly_and_leaves_no_worker_behind(tmp_path):
    var = tmp_path / "var"
    total = len(plan_cells(suite_families(), seeds=1, max_nodes=260))
    run, said, kept = _stopped_part_way(var, lambda run: os.kill(run.pid, signal.SIGTERM))
    assert run.returncode == 128 + signal.SIGTERM, said
    assert 6 <= len(kept) < total
    assert "Stopped by SIGTERM after " in said and f" {len(kept):,} of {total:,} cells are measured and kept in " in said
