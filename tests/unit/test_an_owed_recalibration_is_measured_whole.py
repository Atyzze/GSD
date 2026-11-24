from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.calibration import contract as C

ROOT = Path(__file__).resolve().parents[2]
SHIPPED = ROOT / C.DURABLE_DIR / C.SEED_TABLE_NAME


class Measured(Exception):
    pass


DEEP_FROM = 65536


def _a_seed_whose_deep_cells_another_analysis_measured() -> dict:
    from graph_scale_dynamics.calibration import fingerprint as FP
    from graph_scale_dynamics.calibration import start_reading
    from graph_scale_dynamics.calibration.cells import plan_cells, suite_families
    seed = json.loads(SHIPPED.read_text(encoding="utf-8"))
    science = FP.science_fingerprint()
    template = next(iter(seed["cells"].values()))
    for task in plan_cells(suite_families(), seeds=C.AUTHORITATIVE_SEEDS):
        if task["key"] not in seed["cells"]:
            seed["cells"][task["key"]] = dict(template, family=task["family"], parameter=task["parameter"],
                                              seed=task["seed"], n=task["n"])
    for cell in seed["cells"].values():
        deep = int(cell.get("n") or 0) > DEEP_FROM
        cell["host"] = "box" if deep else "vm"
        if deep:
            cell["cell_fingerprint"] = "measured-under-another-analysis"
        else:
            cell.update(cell_fingerprint=FP.cell_fingerprint(str(cell.get("family")), None), science_fingerprint=science)
            if isinstance(cell.get("start"), dict):
                cell["start"] = dict(cell["start"], fingerprint=start_reading.fingerprint())
    return seed


def _the_ladders() -> tuple[int, int]:
    from graph_scale_dynamics.calibration.cells import plan_cells, suite_families
    plan = plan_cells(suite_families(), seeds=C.AUTHORITATIVE_SEEDS)
    deep = sum(1 for task in plan if int(task["n"]) > DEEP_FROM)
    assert 0 < deep < len(plan)
    return deep, len(plan) - deep


def _folder(tmp_path) -> Path:
    tree = tmp_path / "study" / "main"
    (tree / C.DURABLE_DIR).mkdir(parents=True)
    (tree / C.DURABLE_DIR / C.SEED_TABLE_NAME).write_text(
        json.dumps(_a_seed_whose_deep_cells_another_analysis_measured()), encoding="utf-8")
    return tree


def _start(tree, monkeypatch, *, host: str, owed: bool, adopt=None):
    from graph_scale_dynamics.calibration import adopt as ADOPT
    from graph_scale_dynamics.calibration import owed as OWED
    from graph_scale_dynamics.calibration import suite

    seen = {}

    def run(document, *_, **__):
        seen.update(document["plan"])
        raise Measured

    def refuse(*_, **__):
        raise AssertionError("no spot check or adoption while a recalibration is owed")

    monkeypatch.setattr(suite.platform, "node", lambda: host)
    monkeypatch.setattr(OWED, "recalibration_owed", lambda: {"build": 1, "owed": {}} if owed else None)
    monkeypatch.setattr(OWED, "reason", lambda document: "owed since a build that changed a probe")
    monkeypatch.setattr(suite, "run_suite", run)
    if owed:
        monkeypatch.setattr(ADOPT, "spot_check", refuse)
        monkeypatch.setattr(ADOPT, "verify_and_adopt", refuse)
    else:
        monkeypatch.setattr(ADOPT, "spot_check", lambda document, **_: {
            "sampled": 1, "worst_deviation": 0.0, "worst_host_spread": 0.0, "moved": []})
        monkeypatch.setattr(ADOPT, "verify_and_adopt", adopt)
    lines: list[str] = []
    with pytest.raises(Measured):
        suite.ensure_calibration(root=tree, var=tree / "var", log=lines.append, profile=C.PROFILE_FULL)
    return seen, lines


def test_an_owed_recalibration_measures_every_stale_cell(tmp_path, monkeypatch):
    seed = _a_seed_whose_deep_cells_another_analysis_measured()
    assert {cell["host"] for cell in seed["cells"].values()} == {"vm", "box"}, "the sandbox's and the host's"
    deep, shallow = _the_ladders()
    plan, lines = _start(_folder(tmp_path), monkeypatch, host="the operator's host", owed=True)
    assert (plan["stale"], plan["current"]) == (deep, shallow), "stale by their fingerprints, wherever measured"
    assert any("every cell stale under this tree's code is measured" in line for line in lines), lines


def test_cells_an_adoption_leaves_stale_are_measured_not_refused(tmp_path, monkeypatch):
    def adopted(document, **_):
        return {"adopted": True, "notices": ["all sampled reproduced; the cells already stale left stale"],
                "refused": [], "sampled": 51, "worst_deviation": 0.0, "worst_host_spread": 0.0}

    deep, _ = _the_ladders()
    plan, lines = _start(_folder(tmp_path), monkeypatch, host="vm", owed=False, adopt=adopted)
    assert plan["stale"] == deep, "measured, where until 697 a start refused a table with stale cells left in it"
    assert not any("No recalibration needed" in line for line in lines), lines
    assert any("were stale before it and are measured now" in line for line in lines), lines


def test_once_this_host_has_measured_the_cells_the_start_is_allowed(tmp_path, monkeypatch):
    from graph_scale_dynamics.calibration import adopt as ADOPT
    from graph_scale_dynamics.calibration import fingerprint as FP
    from graph_scale_dynamics.calibration import owed as OWED
    from graph_scale_dynamics.calibration import start_reading
    from graph_scale_dynamics.calibration import suite
    from graph_scale_dynamics.calibration import table as T

    measured = []

    def run(document, path, families, *, seeds, max_nodes, waivers=None, **_):
        science = FP.science_fingerprint()
        for key, cell in document["cells"].items():
            fresh = FP.cell_fingerprint(str(cell.get("family")), None)
            if (cell.get("cell_fingerprint") != fresh or cell.get("science_fingerprint") != science
                    or not start_reading.current_where_wanted(cell)):
                cell.update(cell_fingerprint=fresh, science_fingerprint=science, host="the operator's host")
                if isinstance(cell.get("start"), dict):
                    cell["start"] = dict(cell["start"], fingerprint=start_reading.fingerprint())
                measured.append(key)
        T.refresh(document, families, seeds=seeds, max_nodes=max_nodes, waivers=waivers)
        T.write(document, path)
        return {"cells_computed": len(measured)}

    def refuse(*_, **__):
        raise AssertionError("no spot check or adoption while a recalibration is owed")

    monkeypatch.setattr(suite.platform, "node", lambda: "the operator's host")
    monkeypatch.setattr(OWED, "recalibration_owed", lambda: {"build": 1, "owed": {}})
    monkeypatch.setattr(OWED, "reason", lambda document: "owed since a build that changed a probe")
    monkeypatch.setattr(suite, "run_suite", run)
    monkeypatch.setattr(ADOPT, "spot_check", refuse)
    monkeypatch.setattr(ADOPT, "verify_and_adopt", refuse)
    tree = _folder(tmp_path)
    deep, shallow = _the_ladders()
    status = suite.ensure_calibration(root=tree, var=tree / "var", log=lambda *_: None, profile=C.PROFILE_FULL)
    assert status["verdict"] == "PASS" and status["cells"]["current"] == deep + shallow, status.get("summary")
    assert len(measured) >= deep, "the stale cells, measured"
    again = suite.ensure_calibration(root=tree, var=tree / "var", log=lambda *_: None, profile=C.PROFILE_FULL)
    assert again["verdict"] == "PASS" and again["computed"] == 0, "the next start measures nothing again"


def test_a_cell_current_by_its_fingerprints_is_kept_whoever_measured_it(tmp_path, monkeypatch):
    deep, shallow = _the_ladders()
    plan, lines = _start(_folder(tmp_path), monkeypatch, host="a host that measured none of them", owed=True)
    assert (plan["current"], plan["stale"]) == (shallow, deep), "those another analysis measured, alone"
