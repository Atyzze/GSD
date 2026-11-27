from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from graph_scale_dynamics.artifact_store import resume_state as R
from graph_scale_dynamics.scaleflow.one_shot import RESUME_CONTRACT, run_one_shot
from graph_scale_dynamics.scheduling.job_creation import one_shot_policy

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "graph_scale_dynamics" / "resources" / "configs"
VOLATILE = {"timing", "wall_seconds", "wall_seconds_so_far", "elapsed_seconds", "started_utc", "finished_utc",
            "resumed", "resource_usage", "engine", "runtime_fingerprint", "seconds"}


def _stable(value):
    if isinstance(value, dict):
        return json.dumps({k: json.loads(_stable(v)) for k, v in value.items() if k not in VOLATILE},
                          sort_keys=True, default=str)
    if isinstance(value, (list, tuple)):
        return json.dumps([json.loads(_stable(v)) for v in value], default=str)
    return json.dumps(value, default=str)


@pytest.fixture(scope="module")
def law():
    return json.loads((CONFIGS / "candidate_sparse_anchor.json").read_text())


@pytest.fixture(scope="module")
def policy():
    campaign = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    return dict(one_shot_policy(campaign), work_budget=10 ** 15, max_sweeps_multiplier=8, mean_degree_cap=16.0)


class _Stop(Exception):
    pass


def _bytes_held(value, seen=None) -> int:
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    held = sys.getsizeof(value)
    if isinstance(value, dict):
        held += sum(_bytes_held(k, seen) + _bytes_held(v, seen) for k, v in value.items())
    elif isinstance(value, (list, tuple)):
        held += sum(_bytes_held(v, seen) for v in value)
    return held


def _engine(name):
    from graph_scale_dynamics.services.worker import engine_registry as E
    if not E.available_engines().get(name, {}).get("available"):
        pytest.skip(f"the {name} engine is not built on this host")
    return E.simulate_of(name)


@pytest.mark.parametrize("engine", ["python", "rust"])
def test_a_seed_resumed_inside_a_chunk_and_let_go_of_its_saved_state_is_the_seed_never_stopped(tmp_path, monkeypatch,
                                                                                              law, policy, engine):
    monkeypatch.setattr(R, "PACK_FROM", 8)
    simulate = _engine(engine)

    def _run(law, policy, **kw):
        return run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60, simulate=simulate,
                            **kw)
    whole = _run(law, policy)
    units = [int(row["work_units"]) for row in whole["sampling_checkpoints"]]
    assert len(units) >= 2, "the case needs a second chunk to stop inside"
    every = max(1, min(units[0], units[1] - units[0]) // 2)
    never = _run(law, policy, save_every_units=every)
    path = tmp_path / "state.json.gz"
    written = []

    def keep(state):
        if state.get("in_chunk") and "whole" in state:
            R.save_resume_state(path, state, execution_spec_hash="h")
            written.append(state)
            raise _Stop()

    with pytest.raises(_Stop):
        _run(law, policy, save_every_units=every, on_chunk=keep)
    resume, note = R.load_resume_state(path, execution_spec_hash="h")
    edges = resume["checkpoint"]["chains"][0]["edge_list"]
    assert note == "resumed" and resume["contract"] == RESUME_CONTRACT and len(edges) >= 8
    assert all(type(edge) is tuple for edge in edges), "an edge read back as the engine wrote it, a pair"
    numbers: dict = {}
    assert all(numbers.setdefault(end, end) is end for edge in edges for end in edge), (
        "equal numbers of a saved state are one object")
    for key in ("checkpoint", "whole"):
        back, own = resume[key], written[0][key]
        chains_back = (back.get("checkpoint") or back)["chains"]
        chains_own = (own.get("checkpoint") or own)["chains"]
        for found, kept in zip(chains_back, chains_own, strict=True):
            assert _bytes_held(found["edge_list"]) <= 1.05 * _bytes_held(kept["edge_list"]), (
                f"a chain's edges in the {key} read back hold what the engine's own do, but a list's spare room")
    assert _bytes_held(resume["checkpoint"]) <= 1.1 * _bytes_held(written[0]["checkpoint"]), (
        "the checkpoint read back within 10% of the engine's own, as a fresh seed holds it")
    held = []

    def let_go(state):
        held.append(sorted(set(R.HELD_STATES) & set(resume)))
        R.let_go_of_its_states(resume)

    resumed = _run(law, policy, save_every_units=every, resume=resume, on_chunk=let_go)
    assert _stable(resumed) == _stable(never), "the saved state let go at the first save, the chain to the bit"
    assert held[0] == ["checkpoint", "whole"] and all(not found for found in held[1:])
    assert resume["history"] and resumed["rung_terminal"]["resumed"]["chunks_before"] == len(resume["history"])


def test_the_child_counts_a_resumed_seed_s_moves_from_its_state_and_lets_it_go_at_the_next(tmp_path, monkeypatch,
                                                                                           law):
    from graph_scale_dynamics.domain.version import ROOT as PKG_ROOT, environment_fingerprint, source_fingerprint
    from graph_scale_dynamics.dsl.dsl import fingerprint as law_fingerprint
    from graph_scale_dynamics.services.worker import child

    campaign = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    job_id = "c" * 64
    chains = [{"start": "empty", "attempted": {"add": 700, "delete": 200, "swap": 100}}]
    seen, published = [], []

    def fake_run_one_shot(*args, **kwargs):
        resume = kwargs["resume"] or {}
        seen.append(sorted(set(R.HELD_STATES) & set(resume)))
        kwargs["on_chunk"]({"contract": RESUME_CONTRACT, "checkpoint": {"chains": chains}, "multiplier": 1,
                            "consecutive": 0, "history": [{}, {}], "seconds_spent": 40.0, "attempts": 2})
        seen.append(sorted(set(R.HELD_STATES) & set(resume)))
        return {"rung_terminal": {"reason": "completed"},
                "sampling_checkpoint": {"chains": [{"start": "empty",
                                                    "attempted": {"add": 2000, "delete": 600, "swap": 400}}]}}

    def publish(store, envelope, **kwargs):
        published.append(envelope)
        return {"artifacts": {}}

    monkeypatch.setattr(child, "run_one_shot", fake_run_one_shot)
    monkeypatch.setattr(child, "RUN_ENGINE", {})
    monkeypatch.setattr(child, "publish_envelope_artifacts", publish)
    monkeypatch.setattr(child, "discard_resume_state", lambda path: None)
    job = {"job_id": job_id, "candidate_spec": law, "candidate_id": law_fingerprint(law), "n": 64, "seed": 1,
           "record_points": 30, "engine_version": child.ENGINE_VERSION, "publish_blob_root": str(tmp_path),
           "resume_root": str(tmp_path / "ram"),
           "execution_provenance": {"source_fingerprint": source_fingerprint(PKG_ROOT),
                                    "environment_fingerprint": environment_fingerprint()},
           "execution": {"sweeps_multiplier": 1, "one_shot": one_shot_policy(campaign)}}
    job_file, out_file = tmp_path / "job.json", tmp_path / "out.json"
    job_file.write_text(json.dumps(job))
    child._run([str(job_file), str(out_file)])
    assert seen == [[], []], "a seed with no saved state holds none"
    child._run([str(job_file), str(out_file)])
    assert seen[2:] == [["checkpoint"], []], "the saved state is held until the run hands out its next, then let go"
    speed = published[-1]["resource_usage"]["cpu_speed"]
    assert speed["moves"] == 3000 - 1000, "the moves of this attempt, counted from the saved state before it went"
