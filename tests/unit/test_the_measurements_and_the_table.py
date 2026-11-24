from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_an_ended_given_chain_is_built_at_restore_on_the_rust_path(monkeypatch):
    from graph_scale_dynamics.services.worker import engine_rs
    built = []
    monkeypatch.setattr(engine_rs, "_rebuilt_now_through", lambda door, ctx, chain, **kw: built.append(kw) or "built")
    ended = engine_rs.rebuild(None, {"ended": {"reason": "mean_degree_cap"}, "edge_list": []})
    assert ended == "built" and built == [{"stop_file": None}]
    from types import SimpleNamespace
    running = engine_rs.rebuild(SimpleNamespace(n=4), {"edge_list": [(0, 1)]})
    assert isinstance(running, engine_rs.DeferredRustState) and len(built) == 1, "a chain that runs is still deferred"


def _rungs(at_cap: bool):
    from graph_scale_dynamics.decisions.engine import Rung, Seed
    seeds = tuple(Seed(termination="completed", given_at_cap=at_cap and i == 0) for i in range(3))
    base = [Rung(n=n, mean_degree=2.5, connected_fraction=0.9, probes={}, seeds_measured=3, seeds=seeds)
            for n in (64, 256, 1024)]
    return base + [Rung(n=4096, mean_degree=2.6, connected_fraction=0.9, probes={}, seeds_measured=3, seeds=seeds,
                        d_s_refusal="REFUSED_CHAINS_DISAGREED")]


def test_a_given_chain_at_the_cap_parks_without_a_longer_chain():
    from graph_scale_dynamics.decisions.engine import Policy, decide
    law = "a" * 64
    sampling = decide(law, _rungs(False), Policy())
    capped = decide(law, _rungs(True), Policy())
    if sampling.rule != "longer_chain":
        pytest.skip(f"the plain rules decide this fixture by {sampling.rule}, not by the d_s refusal")
    assert capped.rule == "no_reading"
    assert capped.facts["d_s_refusal"] == {"kind": "limits", "bucket": "REFUSED_CHAINS_DISAGREED",
                                           "longer_chain": False, "given_at_cap": True}
    assert "mean-degree cap" in capped.reason


def test_the_seed_rows_say_which_given_chain_ended_at_the_cap(monkeypatch):
    from graph_scale_dynamics.db import decision_store as DS

    class Conn:
        def execute(self, sql, params):
            class Rows:
                def fetchall(self):
                    return [{"n": 4096, "seed": 0, "wall_seconds": 9.0}, {"n": 4096, "seed": 1, "wall_seconds": 9.0}]
            return Rows()

    store = DS.DecisionStore.__new__(DS.DecisionStore)
    store.repo = type("Repo", (), {"conn": Conn()})()
    measured = [{"n": 4096, "seed": 0, "metrics": {"given_ended_at_cap": ["given"], "health": {}}},
                {"n": 4096, "seed": 1, "metrics": {"health": {}}}]
    monkeypatch.setattr(store, "_law_measurements", lambda c, law: measured, raising=False)
    monkeypatch.setattr(DS, "best_runs", lambda rows: rows)
    rows = store.seed_rows("6", "law")
    assert [row.get("given_at_cap") for row in rows[4096]] == [True, False]


def test_the_top_rung_s_own_error_leaves_a_block_unresolved_on_measured_errors():
    from graph_scale_dynamics.research.stability_score import score_block
    block = score_block([1.0, 1.01, 1.02, 1.01], [None] * 4, floor=0.05, sizes=[1024, 4096, 16384, 65536],
                        ses=[0.01] * 4, measured_ses=[0.01, 0.01, 0.01, 0.5])
    assert block["bucket"] == "UNRESOLVED_AT_TOP_RUNG"


def test_a_move_is_priced_by_the_moves_run():
    from graph_scale_dynamics.research import compute_efficiency as CE
    spec = {"candidate_spec": {"dynamics": {"sweeps": 10}}, "execution": {"sweeps_multiplier": 1.0}}
    recorded = {"n": 100, "spec": spec, "resource_json": json.dumps({"cpu_speed": {"moves": 10_000}})}
    before_547 = {"n": 100, "spec": spec, "resource_json": json.dumps({"engine": {"name": "rust"}})}
    proxy = CE.attempted_move_proxy(before_547)
    assert CE.attempted_moves(recorded) == 10_000.0
    assert CE.attempted_moves(before_547) == proxy and proxy is not None
    assert CE._moves_basis([recorded, before_547]) == {"recorded": 1, "declared": 1}


def _cell(family, n, seed, fingerprint, value=2.0):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    return {"family": family, "n": n, "seed": seed, "parameter": None, "status": "ok", "analysis": ANALYSIS_VERSION,
            "cell_fingerprint": fingerprint, "science_fingerprint": "old",
            "channels": {"d_s": {"value": value, "se": 0.01, "valid": True}}}


def test_a_stale_cell_is_read_by_no_one_and_stays_stale_through_an_adoption(monkeypatch):
    from graph_scale_dynamics.calibration import adopt as ADOPT
    from graph_scale_dynamics.calibration import fingerprint as FP
    from graph_scale_dynamics.calibration import table as T
    from graph_scale_dynamics.research.stability_score import control_family_reference
    monkeypatch.setattr(FP, "cell_fingerprint", lambda family, root=None: "now")
    current, stale = _cell("periodic_ring", 64, 0, "now", 2.0), _cell("periodic_ring", 1048576, 9, "pre-627", 9.0)
    assert T.cell_is_current(current) and not T.cell_is_current(stale)
    reference = control_family_reference({"cells": {"a": current, "b": stale}})
    assert list(reference["periodic_ring"]) == [64]
    cells = {f"r:{n}:{s}": _cell("periodic_ring", n, s, "before") for s, n in enumerate((64, 256, 1024))}
    cells["r:1048576:9"] = _cell("periodic_ring", 1048576, 9, "pre-627")
    assert ADOPT.restamp_current({"cells": cells}, "new-science") == (3, 1)
    assert cells["r:1048576:9"]["cell_fingerprint"] == "pre-627"


def test_an_adopted_table_is_judged_and_never_crashes_the_start(tmp_path, monkeypatch):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    from graph_scale_dynamics.calibration import adopt, suite
    from graph_scale_dynamics.calibration import contract as C
    from graph_scale_dynamics.calibration import fingerprint as FP
    here = tmp_path / "main"
    (here / C.DURABLE_DIR).mkdir(parents=True)
    (here / C.DURABLE_DIR / C.DURABLE_NAME).write_bytes((ROOT / C.DURABLE_DIR / C.SEED_TABLE_NAME).read_bytes())
    real = FP.cell_fingerprint
    monkeypatch.setattr(FP, "cell_fingerprint", lambda family, root=None: "edited:" + real(family, root))

    def adopted(document, **kw):
        for cell in document["cells"].values():
            cell["cell_fingerprint"] = FP.cell_fingerprint(str(cell.get("family")), None)
        return {"adopted": True, "sampled": 2, "notices": [], "refused": [], "worst_deviation": 0.0,
                "worst_host_spread": 0.0}

    def refuse(*_, **__):
        raise AssertionError("the suite ran after the table was adopted")

    monkeypatch.setattr(adopt, "verify_and_adopt", adopted)
    monkeypatch.setattr(suite, "run_suite", refuse)
    status = suite.ensure_calibration(root=here, var=here / "var", log=lambda *_: None, profile=C.PROFILE_FULL)
    assert status["path"] == str(here / C.DURABLE_DIR / C.DURABLE_NAME)
    assert status["verdict"] == "PASS" and status["cells"]["stale"] == 0


def test_the_adoption_tool_is_the_start_s_own_check(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / "tools"))
    import adopt_calibration as tool
    from graph_scale_dynamics.calibration import adopt
    from graph_scale_dynamics.calibration import table as T
    from graph_scale_dynamics.calibration.contract import DURABLE_DIR, DURABLE_NAME
    called, read = [], []
    monkeypatch.setattr(adopt, "verify_and_adopt", lambda document, **kw: called.append(kw) or {
        "adopted": False, "refused": [], "sampled": 0, "stale_cells": 0, "worst_deviation": 0.0,
        "worst_host_spread": 0.0, "notices": ["every cell already matches this runtime; nothing to adopt"]})
    monkeypatch.setattr(T, "load", lambda path: read.append(Path(path)) or {"cells": {}})
    monkeypatch.chdir(tmp_path)
    assert tool.main([]) == 0
    assert called
    assert read == [ROOT / DURABLE_DIR / DURABLE_NAME], "the table is this folder's, wherever the tool is run from"
