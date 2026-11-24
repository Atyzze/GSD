from __future__ import annotations

import gzip
import json
import time
from pathlib import Path

import pytest

from graph_scale_dynamics.scaleflow.engine_door import run_simulation
from graph_scale_dynamics.scaleflow.one_shot import RESUME_CONTRACT, run_one_shot
from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
from graph_scale_dynamics.artifact_store import resume_state as R

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "graph_scale_dynamics" / "resources" / "configs"
VOLATILE = {"timing", "wall_seconds", "wall_seconds_so_far", "elapsed_seconds", "started_utc", "finished_utc",
            "resumed", "resource_usage", "engine", "runtime_fingerprint", "seconds"}


def _stable(value):
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, (list, tuple)):
        return [_stable(v) for v in value]
    return value


@pytest.fixture(scope="module")
def law():
    return json.loads((CONFIGS / "candidate_sparse_anchor.json").read_text())


@pytest.fixture(scope="module")
def policy():
    campaign = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    return dict(one_shot_policy(campaign), work_budget=10 ** 15, max_sweeps_multiplier=8, mean_degree_cap=16.0)


class _Stop(Exception):
    pass


def _run_stopped_after(law, policy, chunks: int, **kw):
    states, calls = [], [0]

    def simulate(*args, **kwargs):
        calls[0] += 1
        if calls[0] > chunks:
            raise _Stop()
        return run_simulation(*args, **kwargs)

    with pytest.raises(_Stop):
        run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60, simulate=simulate,
                     on_chunk=states.append, **kw)
    return json.loads(json.dumps(states[-1]))


def test_a_run_resumed_after_a_stop_is_the_run_that_was_never_stopped(law, policy):
    whole = run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60)
    assert whole["rung_terminal"]["chunks"] >= 2, "the case needs a chunk boundary to stop at"
    state = _run_stopped_after(law, policy, 1)
    assert state["contract"] == RESUME_CONTRACT and len(state["history"]) == 1
    resumed = run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60, resume=state)
    assert json.dumps(_stable(resumed), sort_keys=True, default=str) == json.dumps(_stable(whole), sort_keys=True,
                                                                                     default=str)
    assert resumed["rung_terminal"]["resumed"] == {"attempts_before": 1, "chunks_before": 1,
                                                   "seconds_before": state["seconds_spent"]}
    assert "resumed" not in whole["rung_terminal"]


def test_the_budget_counts_the_work_before_the_stop(law, policy):
    whole = run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60)
    assert len(whole["sampling_checkpoints"]) >= 3, "the case needs two chunks before the budget"
    tight = dict(policy, work_budget=int(whole["sampling_checkpoints"][1]["work_units"]) + 1)
    once = run_one_shot(law, 96, 3, one_shot=tight, initial_multiplier=1, record_points=60)
    assert once["rung_terminal"]["reason"] == "budget" and once["rung_terminal"]["chunks"] == 2
    state = _run_stopped_after(law, tight, 1)
    resumed = run_one_shot(law, 96, 3, one_shot=tight, initial_multiplier=1, record_points=60, resume=state)
    assert json.dumps(_stable(resumed), sort_keys=True, default=str) == json.dumps(_stable(once), sort_keys=True,
                                                                                     default=str), (
        "a stop and a resume end the seed at the same chunk with the same work, the work before the stop counted")


def test_every_boundary_hands_out_the_state_and_the_attempt_count_grows(law, policy):
    first = _run_stopped_after(law, policy, 1)
    states = []
    run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60, resume=first,
                 on_chunk=states.append)
    assert all(s["attempts"] == 2 for s in states)
    assert all(s["seconds_spent"] >= first["seconds_spent"] for s in states)


def test_a_state_from_another_contract_is_refused(law, policy):
    with pytest.raises(ValueError, match="resume contract"):
        run_one_shot(law, 96, 3, one_shot=policy, resume={"contract": "one-shot-resume-0"})


def test_the_state_file_round_trips_and_is_used_only_by_its_execution(tmp_path, law, policy):
    state = _run_stopped_after(law, policy, 1)
    path = R.resume_path(tmp_path, "a" * 64)
    assert path == tmp_path / R.RESUME_DIR / f"{'a' * 64}.json.gz"
    R.save_resume_state(path, state, execution_spec_hash="exec-1")
    loaded, note = R.load_resume_state(path, execution_spec_hash="exec-1")
    assert note == "resumed" and loaded["checkpoint"] == state["checkpoint"]
    assert not list(path.parent.glob("*.tmp")), "the write is a rename"
    other, why = R.load_resume_state(path, execution_spec_hash="exec-2")
    assert other is None and "another execution" in why
    path.write_bytes(b"not gzip")
    broken, why = R.load_resume_state(path, execution_spec_hash="exec-1")
    assert broken is None and why.startswith("unreadable")
    assert R.load_resume_state(tmp_path / "missing.json.gz", execution_spec_hash="x") == (None, "no saved state")
    R.discard_resume_state(path)
    R.discard_resume_state(path)
    assert not path.exists()
    assert R.resume_path(tmp_path, "../escape") is None and R.resume_path(None, "a" * 64) is None


_real_discard = R.discard_resume_state


def test_the_child_resumes_from_its_saved_state_and_saves_the_next(tmp_path, monkeypatch, law):
    from graph_scale_dynamics.domain.version import ROOT as PKG_ROOT, environment_fingerprint, source_fingerprint
    from graph_scale_dynamics.dsl.dsl import fingerprint as law_fingerprint
    from graph_scale_dynamics.services.worker import child

    campaign = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    job_id = "b" * 64
    seen: list[dict] = []

    def fake_run_one_shot(*args, **kwargs):
        seen.append(kwargs)
        kwargs["on_chunk"]({"contract": RESUME_CONTRACT, "checkpoint": {"n": 64}, "multiplier": 2, "consecutive": 1,
                            "history": [{"multiplier": 1}], "seconds_spent": 30.0, "attempts": 1})
        kwargs["on_chunk"]({"contract": RESUME_CONTRACT, "checkpoint": {"n": 64}, "multiplier": 4, "consecutive": 0,
                            "history": [{}, {}], "seconds_spent": 5.0, "attempts": 1})
        return {"rung_terminal": {"reason": "completed"}}

    monkeypatch.setattr(child, "run_one_shot", fake_run_one_shot)
    monkeypatch.setattr(child, "RUN_ENGINE", {})
    job = {"job_id": job_id, "candidate_spec": law, "candidate_id": law_fingerprint(law), "n": 64, "seed": 1,
           "record_points": 30, "engine_version": child.ENGINE_VERSION, "publish_blob_root": None,
           "execution_provenance": {"source_fingerprint": source_fingerprint(PKG_ROOT),
                                    "environment_fingerprint": environment_fingerprint()},
           "execution": {"sweeps_multiplier": 1, "one_shot": one_shot_policy(campaign)}}

    def run_child(payload):
        job_file, out_file = tmp_path / "job.json", tmp_path / "out.json"
        job_file.write_text(json.dumps(payload))
        monkeypatch.setattr(child, "publish_envelope_artifacts", lambda *a, **k: {"artifacts": {}})
        child._run([str(job_file), str(out_file)])

    run_child(job)
    assert seen[-1]["resume"] is None
    monkeypatch.setattr(R, "discard_resume_state", lambda path: None)
    monkeypatch.setattr(child, "discard_resume_state", lambda path: None)
    ram = tmp_path / "ram"
    run_child(dict(job, publish_blob_root=str(tmp_path), resume_root=str(ram)))
    path = R.resume_path(ram, job_id)
    with gzip.open(path, "rt") as handle:
        kept = json.load(handle)
    assert (kept["multiplier"], kept["seconds_spent"]) == (2, 30.0)
    assert R.resume_path(tmp_path, job_id).exists() is False, "a saved state is not written to the disk root"
    run_child(dict(job, publish_blob_root=str(tmp_path), resume_root=str(ram)))
    assert seen[-1]["resume"]["multiplier"] == 2 and seen[-1]["resume"]["execution_spec_hash"]

    disk_state = R.resume_path(tmp_path, job_id)
    disk_state.parent.mkdir(parents=True, exist_ok=True)
    path.replace(disk_state)
    monkeypatch.setattr(child, "discard_resume_state", _real_discard)
    run_child(dict(job, publish_blob_root=str(tmp_path), resume_root=str(ram / "fresh"),
                   disk_resume_root=str(tmp_path)))
    assert seen[-1]["resume"]["multiplier"] == 2, "the state saved on disk by the earlier build was not resumed"
    assert not disk_state.exists(), "the disk copy stays behind after it was read"


def test_a_resumed_rung_is_decided_on_its_seeds_work_not_their_seconds():
    from graph_scale_dynamics.db.decision_store import DecisionStore
    store = DecisionStore.__new__(DecisionStore)
    work = {"contract": "gsd-seed-work-1", "budget": 900, "units": 800, "moves": 40,
            "first_chunk": {"units": 100, "moves": 10, "multiplier": 1}}
    store._measurements = {"law": [
        {"n": 1048576, "seed": 0, "metrics": {"health": {"rung_terminal": {
            "reason": "completed", "wall_seconds": 1500.0, "final_multiplier": 4, "work": work,
            "resumed": {"attempts_before": 1}}}}},
        {"n": 1048576, "seed": 1, "metrics": {"health": {"rung_terminal": {
            "reason": "budget", "wall_seconds": 880.0, "final_multiplier": 8, "work": dict(work, units=900)}}}},
    ]}
    rows = store.seed_rows("1", "law")[1048576]
    assert [row["ended"] for row in rows] == ["completed", "budget"]
    assert [row["work_units"] for row in rows] == [800, 900] and all("wall_seconds" not in row for row in rows)
    assert [row["final_multiplier"] for row in rows] == [4, 8] and rows[0]["first_chunk_moves"] == 10


@pytest.mark.parametrize("lands", ["in_the_chain", "in_the_rebuild"])
def test_a_run_stopped_in_the_middle_of_a_chunk_resumes_to_the_run_that_was_never_stopped(tmp_path, monkeypatch,
                                                                                         law, policy, lands):
    from graph_scale_dynamics.engine import engine as E
    from graph_scale_dynamics.scaleflow.one_shot import StopRequested
    monkeypatch.setattr(E, "STOP_CHECK_SECONDS", 0.0)
    whole = run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60)
    assert whole["rung_terminal"]["chunks"] >= 2
    stop = tmp_path / "stop"
    states, calls = [], [0]

    def in_the_chain(*args, **kwargs):
        stop.write_text("")
        return E.run_chain(*args, **kwargs)

    def simulate(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 2:
            if lands == "in_the_chain":
                return run_simulation(*args, chain_runner=in_the_chain, **kwargs)
            stop.write_text("")
        return run_simulation(*args, **kwargs)

    with pytest.raises(StopRequested):
        run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60, simulate=simulate,
                     on_chunk=states.append, stop_file=str(stop))
    state = json.loads(json.dumps(states[-1]))
    if lands == "in_the_chain":
        assert state["in_chunk"] is True and len(state["history"]) == 1
        assert state["checkpoint"]["in_segment"]["chain"] in {"empty", "given"}
    else:
        assert "in_chunk" not in state and len(state["history"]) == 1, "resumed from the chunk boundary"
    stop.unlink()
    resumed = run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60, resume=state,
                           stop_file=str(stop))
    assert json.dumps(_stable(resumed), sort_keys=True, default=str) == json.dumps(_stable(whole), sort_keys=True,
                                                                                     default=str)


def test_the_child_exits_stopped_without_publishing_when_asked(tmp_path, monkeypatch, law):
    from graph_scale_dynamics.domain.version import ROOT as PKG_ROOT, environment_fingerprint, source_fingerprint
    from graph_scale_dynamics.dsl.dsl import fingerprint as law_fingerprint
    from graph_scale_dynamics.scaleflow.one_shot import StopRequested
    from graph_scale_dynamics.services.worker import child

    seen = {}

    def stopping_run_one_shot(*args, **kwargs):
        seen.update(kwargs)
        raise StopRequested("stopped")

    monkeypatch.setattr(child, "run_one_shot", stopping_run_one_shot)
    campaign = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    job = {"job_id": "c" * 64, "candidate_spec": law, "candidate_id": law_fingerprint(law), "n": 64, "seed": 1,
           "record_points": 30, "engine_version": child.ENGINE_VERSION,
           "execution_provenance": {"source_fingerprint": source_fingerprint(PKG_ROOT),
                                    "environment_fingerprint": environment_fingerprint()},
           "execution": {"sweeps_multiplier": 1, "one_shot": one_shot_policy(campaign)}}
    staging = tmp_path / "staging"
    staging.mkdir()
    job_file, out_file = staging / "job.json", staging / "result.json"
    job_file.write_text(json.dumps(job))
    assert child._run([str(job_file), str(out_file)]) == child.STOPPED_EXIT_CODE
    assert seen["stop_file"] == str(staging / "stop")
    assert not out_file.exists(), "a stopped child publishes nothing"


def test_a_worker_asks_its_child_to_stop_and_kills_only_a_child_that_does_not(tmp_path, monkeypatch):
    import subprocess
    import sys
    from graph_scale_dynamics.services.worker import main as worker
    staging = tmp_path / "staging"
    staging.mkdir()
    polite = subprocess.Popen([sys.executable, "-c", (
        "import os, sys, time\n"
        f"p = {str(staging / 'stop')!r}\n"
        "while not os.path.exists(p): time.sleep(0.05)\n"
        "sys.exit(75)\n")], start_new_session=True)
    monkeypatch.setattr(worker, "CURRENT_CHILD", polite)
    worker.stop_current_child(staging, grace=10.0)
    assert polite.wait(timeout=5) == 75 and (staging / "stop").exists()
    (staging / "stop").unlink()
    stubborn = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    monkeypatch.setattr(worker, "CURRENT_CHILD", stubborn)
    started = time.monotonic()
    worker.stop_current_child(staging, grace=0.5)
    assert stubborn.wait(timeout=5) != 0 and time.monotonic() - started < 5


def test_the_panel_reads_the_note_beside_a_saved_state(tmp_path, law, policy):
    from graph_scale_dynamics.observability import live_panel
    state = _run_stopped_after(law, policy, 1)
    job_id = "d" * 64
    ram = R.resume_root(tmp_path)
    path = R.resume_path(ram, job_id)
    R.save_resume_state(path, dict(state, seconds_spent=1263.4), execution_spec_hash="h")
    assert R.read_resume_note(ram, job_id)["seconds_spent"] == 1263.4
    live_panel.RESUME_ROOT = tmp_path
    try:
        row = live_panel.lane_and_budget({"job_id": job_id, "n": 1048576, "spec": {}}, {64})
        assert (row["resumed_seconds"], row["resumed_chunks"]) == (1263.4, 1)
        assert "resumed_seconds" not in live_panel.lane_and_budget({"job_id": "e" * 64, "n": 64, "spec": {}}, {64})
    finally:
        live_panel.RESUME_ROOT = None
    R.discard_resume_state(path)
    assert R.read_resume_note(ram, job_id) is None, "the note goes with its state"


def test_a_disk_copy_outlives_a_hard_stop_before_the_next_boundary(tmp_path, monkeypatch, law):
    from graph_scale_dynamics.domain.version import ROOT as PKG_ROOT, environment_fingerprint, source_fingerprint
    from graph_scale_dynamics.dsl.dsl import fingerprint as law_fingerprint
    from graph_scale_dynamics.scaleflow.one_shot import StopRequested
    from graph_scale_dynamics.services.worker import child

    campaign = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    job_id = "c" * 64
    job = {"job_id": job_id, "candidate_spec": law, "candidate_id": law_fingerprint(law), "n": 64, "seed": 1,
           "record_points": 30, "engine_version": child.ENGINE_VERSION, "publish_blob_root": str(tmp_path),
           "resume_root": str(tmp_path / "ram"), "disk_resume_root": str(tmp_path),
           "execution_provenance": {"source_fingerprint": source_fingerprint(PKG_ROOT),
                                    "environment_fingerprint": environment_fingerprint()},
           "execution": {"sweeps_multiplier": 1, "one_shot": one_shot_policy(campaign)}}
    monkeypatch.setattr(child, "RUN_ENGINE", {})
    monkeypatch.setattr(child, "publish_envelope_artifacts", lambda *a, **k: {"artifacts": {}})
    state = {"contract": RESUME_CONTRACT, "checkpoint": {"n": 64}, "multiplier": 2, "consecutive": 1,
             "history": [{"multiplier": 1}], "seconds_spent": 30.0, "attempts": 1}
    disk = R.resume_path(tmp_path, job_id)
    ram = R.resume_path(tmp_path / "ram", job_id)

    def run_child():
        job_file, out_file = tmp_path / "job.json", tmp_path / "out.json"
        job_file.write_text(json.dumps(job))
        return child._run([str(job_file), str(out_file)])

    probe: dict = {}

    def keep_hash(*args, **kwargs):
        kwargs["on_chunk"](dict(state))
        raise StopRequested("probe")

    monkeypatch.setattr(child, "run_one_shot", keep_hash)
    run_child()
    disk.parent.mkdir(parents=True, exist_ok=True)
    ram.replace(disk)
    assert disk.exists() and not ram.exists()

    def killed_before_the_boundary(*args, **kwargs):
        probe.update(kwargs)
        raise MemoryError("shed before the first boundary")

    monkeypatch.setattr(child, "run_one_shot", killed_before_the_boundary)
    with pytest.raises(MemoryError):
        run_child()
    assert probe["resume"]["multiplier"] == 2, "the disk copy was resumed"
    assert disk.exists(), "a hard stop before the next boundary keeps the state it resumed from"

    def saves_then_stops(*args, **kwargs):
        kwargs["on_chunk"](dict(state, multiplier=4, seconds_spent=60.0))
        raise StopRequested("asked")

    monkeypatch.setattr(child, "run_one_shot", saves_then_stops)
    run_child()
    assert ram.exists() and not disk.exists(), "a newer state saved in RAM supersedes the disk copy"


def test_a_state_saved_under_other_engine_sources_starts_the_rung_again_and_says_so(tmp_path, monkeypatch, law):
    from graph_scale_dynamics.domain.version import ROOT as PKG_ROOT, environment_fingerprint, source_fingerprint
    from graph_scale_dynamics.dsl.dsl import fingerprint as law_fingerprint
    from graph_scale_dynamics.scaleflow.one_shot import StopRequested
    from graph_scale_dynamics.services.worker import child

    campaign = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    job = {"job_id": "e" * 64, "candidate_spec": law, "candidate_id": law_fingerprint(law), "n": 64, "seed": 1,
           "record_points": 30, "engine_version": child.ENGINE_VERSION, "publish_blob_root": str(tmp_path),
           "resume_root": str(tmp_path / "ram"),
           "execution_provenance": {"source_fingerprint": source_fingerprint(PKG_ROOT),
                                    "environment_fingerprint": environment_fingerprint()},
           "execution": {"sweeps_multiplier": 1, "one_shot": one_shot_policy(campaign)}}
    monkeypatch.setattr(child, "RUN_ENGINE", {})
    published: list[dict] = []
    monkeypatch.setattr(child, "publish_envelope_artifacts", lambda store, envelope, **k: published.append(envelope)
                        or {"artifacts": {}})
    seen: list[dict] = []

    def run_child():
        job_file, out_file = tmp_path / "job.json", tmp_path / "out.json"
        job_file.write_text(json.dumps(job))
        return child._run([str(job_file), str(out_file)])

    def saves_then_stops(*args, **kwargs):
        kwargs["on_chunk"]({"contract": RESUME_CONTRACT, "checkpoint": {"n": 64}, "multiplier": 2, "consecutive": 1,
                            "history": [{"multiplier": 1}], "seconds_spent": 30.0, "attempts": 1})
        raise StopRequested("asked")

    def completes(*args, **kwargs):
        seen.append(kwargs)
        return {"rung_terminal": {"reason": "completed"}}

    monkeypatch.setattr(child, "run_one_shot", saves_then_stops)
    run_child()
    monkeypatch.setattr(child, "run_one_shot", completes)
    monkeypatch.setattr(child, "engine_sources_digest", lambda: "another-engine")
    run_child()
    assert seen[-1]["resume"] is None, "a chain saved under other dynamics is not continued under these"
    assert published[-1]["resume_refused"], "the rung's record says why it started again"


def test_a_state_carries_its_last_whole_chunk_through_the_file(tmp_path, law, policy):
    states = []
    run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60,
                 on_chunk=lambda state: states.append(dict(state, history=list(state["history"]))),
                 save_every_units=2 * 10 ** 6)
    assert any(state.get("in_chunk") and not state["history"] and "whole" not in state for state in states), (
        "a save inside the first chunk has no whole chunk to carry")
    inside = [state for state in states if state.get("in_chunk") and state["history"]][0]
    path = R.resume_path(tmp_path, "a-job")
    R.save_resume_state(path, inside, execution_spec_hash="abc")
    loaded, reason = R.load_resume_state(path, execution_spec_hash="abc")
    assert reason == "resumed" and loaded["in_chunk"] is True
    assert _stable(loaded["whole"]) == _stable(json.loads(json.dumps(inside["whole"]))), (
        "the last whole chunk, its checkpoint and its record, is what a seed cut at its budget ends on")
    assert loaded["whole"]["checkpoint"] != loaded["checkpoint"], "beside the state inside the chunk, not in its place"
    note = R.read_resume_note(tmp_path, "a-job")
    assert note["in_chunk"] is True and note["chunks"] == len(inside["history"])


def test_a_whole_chunk_json_refuses_is_left_out_and_the_seed_is_still_saved(tmp_path):
    from graph_scale_dynamics.services.worker.child import without_the_whole_chunk
    state = {"contract": RESUME_CONTRACT, "checkpoint": {"chains": []}, "history": [{"work_units": 1}],
             "seconds_spent": 30.0, "whole_envelope": {"late": float("nan")}}
    path = R.resume_path(tmp_path, "a-job")
    with pytest.raises(ValueError):
        R.save_resume_state(path, state, execution_spec_hash="abc")
    try:
        R.save_resume_state(path, state, execution_spec_hash="abc")
    except ValueError as refused:
        R.save_resume_state(path, without_the_whole_chunk(state, refused), execution_spec_hash="abc")
    loaded, reason = R.load_resume_state(path, execution_spec_hash="abc")
    assert reason == "resumed" and "whole_envelope" not in loaded
    assert loaded["whole_chunk_left_out"].startswith("ValueError"), "and the state says what it lacks"
    from graph_scale_dynamics.scaleflow.one_shot import whole_chunk_of
    assert whole_chunk_of(loaded) is None, "so that seed's next chunk runs whole, as before 840"
