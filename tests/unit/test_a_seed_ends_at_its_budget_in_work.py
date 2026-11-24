from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.engine import engine as engine_module
from graph_scale_dynamics.engine.engine import CLOCK_STRIDE_MAX_MOVES, CLOCK_STRIDE_START_MOVES, ChainContext, next_clock_stride, run_chain
from graph_scale_dynamics.scaleflow import one_shot as O
from graph_scale_dynamics.scaleflow.engine_door import run_simulation
from graph_scale_dynamics.scaleflow.one_shot import run_one_shot
from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
from graph_scale_dynamics.services.worker.engine_registry import resolve_engine
from tests.support.engines import require_rust_engine

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "graph_scale_dynamics" / "resources" / "configs"
VOLATILE = {"timing", "wall_seconds", "wall_seconds_so_far", "elapsed_seconds", "seconds", "resource_usage"}


@pytest.fixture(scope="module")
def law():
    return json.loads((CONFIGS / "candidate_sparse_anchor.json").read_text())


@pytest.fixture(scope="module")
def policy():
    campaign = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    return dict(one_shot_policy(campaign), work_budget=10 ** 15, max_sweeps_multiplier=16, mean_degree_cap=16.0)


def _stable(value):
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, (list, tuple)):
        return [_stable(v) for v in value]
    return value


def test_a_seed_s_work_is_its_parts_weighed_by_the_committed_unit(law, policy):
    envelope = run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60)
    parts = O.seed_work_parts(CL.move_accounting(envelope))
    weights = O.work_weights(policy)
    work = envelope["rung_terminal"]["work"]
    assert work["units"] == sum(weights[name] * parts[name] for name in O.WORK_PARTS) > 0
    assert work["moves"] == parts["moves"] and work["budget"] == policy["work_budget"]
    first = envelope["sampling_checkpoints"][0]
    assert work["first_chunk"] == {"units": first["work_units"], "moves": first["moves"],
                                   "multiplier": first["multiplier"]}


def test_no_chunk_starts_once_the_next_would_not_fit(law, policy):
    whole = run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60)
    rows = whole["sampling_checkpoints"]
    assert len(rows) >= 3, "the case needs a third chunk to refuse"
    tight = dict(policy, work_budget=int(rows[1]["work_units"]) + 1)
    ended = run_one_shot(law, 96, 3, one_shot=tight, initial_multiplier=1, record_points=60)
    terminal = ended["rung_terminal"]
    assert (terminal["reason"], terminal["chunks"]) == ("budget", 2)
    assert terminal["work"]["next_chunk_predicted"] > 1, "the next chunk was predicted and did not fit"
    assert terminal["work"]["units"] == rows[1]["work_units"] <= tight["work_budget"], "no chunk was cut"
    assert _stable(ended["sampling_checkpoints"]) == _stable(rows[:2]), "the chunks it ran are the run's own"
    assert terminal["classification"], "a seed ended at its budget is classed by its certificate as any other"


def test_the_prediction_is_the_last_chunk_s_work_a_move_times_the_next_chunk_s_moves(law, policy):
    whole = run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60)
    rows = whole["sampling_checkpoints"]
    later = [row for row in rows[1:] if "predicted_units" in row]
    assert later, "every chunk after the first carries the prediction it was admitted on"
    for before, row in zip(rows, rows[1:], strict=False):
        assert row["predicted_units"] > 0
        if before is rows[0]:
            moves = before["moves"]
            assert row["predicted_units"] == -(-before["work_units"] * (row["moves"] - before["moves"]) // moves)


def test_the_clock_decides_nothing_a_seed_does(law, policy):
    ticks = iter(range(0, 10 ** 9, 10 ** 6))
    leaping = run_one_shot(law, 96, 3, one_shot=dict(policy, work_budget=10 ** 12), initial_multiplier=1,
                           record_points=60, clock=lambda: float(next(ticks)))
    steady = run_one_shot(law, 96, 3, one_shot=dict(policy, work_budget=10 ** 12), initial_multiplier=1,
                          record_points=60, clock=lambda: 0.0)
    assert _stable(leaping) == _stable(steady), "a clock that leaps a million seconds a reading changes nothing"


@pytest.mark.parametrize("engine", ["python", "rust"])
def test_no_deadline_reaches_an_engine(law, engine, monkeypatch):
    if engine == "rust":
        require_rust_engine()
    _, run, _ = resolve_engine({"engine": engine})
    plain = run(law, 128, 2, record_points=30, target_sweeps=40)
    real = time.monotonic

    class Leaping:
        now = real()

        @classmethod
        def monotonic(cls):
            cls.now += 3600.0
            return cls.now

    monkeypatch.setattr(engine_module, "time", Leaping)
    leaped = run(law, 128, 2, record_points=30, target_sweeps=40)
    assert leaped["termination"]["reason"] == "completed", leaped["termination"]
    assert CL.sorted_edges(plain) == CL.sorted_edges(leaped)
    assert "deadline_applied" not in leaped["limits"]


def test_the_stop_check_s_stride_is_sized_by_time_not_by_moves():
    tick = 4.0
    assert CLOCK_STRIDE_START_MOVES == 1
    assert next_clock_stride(256, 1.0, tick) == 512, "doubles while a stride takes under half a tick"
    assert next_clock_stride(256, 3.0, tick) == 256, "holds between half a tick and a tick"
    assert next_clock_stride(256, 100.0, tick) == 5, "shrinks in proportion when a stride overruns"
    assert next_clock_stride(1, 9.0, tick) == 1, "never below one move"
    assert next_clock_stride(CLOCK_STRIDE_MAX_MOVES, 0.0, tick) == CLOCK_STRIDE_MAX_MOVES


def _slow_runner(seconds_per_move, moves=None):
    def runner(ctx, *args, **kwargs):
        inner = ctx.apply_edge

        def slow(state, u, v, adding, energy):
            time.sleep(seconds_per_move)
            if moves is not None:
                moves.append(1)
            return inner(state, u, v, adding, energy)
        return run_chain(ChainContext(**{**ctx.__dict__, "apply_edge": slow}), *args, **kwargs)
    return runner


def test_an_expensive_move_cannot_hide_a_stop_request(law, monkeypatch, tmp_path):
    monkeypatch.setattr(engine_module, "STOP_CHECK_SECONDS", 0.2)
    stop = tmp_path / "stop"
    stop.write_text("")
    moves: list = []
    envelope = run_simulation(law, 128, 1, target_sweeps=400, record_points=1, stop_file=str(stop),
                              chain_runner=_slow_runner(0.008, moves))
    assert envelope.get("stopped") and envelope["termination"]["reason"] == "stop_requested", envelope.get("termination")
    assert len(moves) <= (0.2 + 0.25) / 0.008, (
        f"{len(moves)} moves of at least 8 ms ran before a stop with a 0.2 s tick was seen; a busy host makes each "
        "move slower and so this count smaller, never larger")


def test_a_job_s_unit_must_weigh_every_part_by_a_whole_number(law, policy):
    with pytest.raises(ValueError, match="whole number"):
        run_one_shot(law, 64, 0, one_shot=dict(policy, work_unit=dict(policy["work_unit"],
                                                                     weights={"moves": 1.5})))
    with pytest.raises(ValueError, match="gsd-work-unit-1"):
        run_one_shot(law, 64, 0, one_shot=dict(policy, work_unit={"weights": policy["work_unit"]["weights"]}))


def _run(law, policy, engine="python", **more):
    if engine == "rust":
        require_rust_engine()
    return run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60,
                        simulate=resolve_engine({"engine": engine})[1], **more)


def _but_the_prediction(rows) -> list:
    return [{key: value for key, value in row.items() if key != "predicted_units"} for row in _stable(rows)]


def _a_budget_inside_the_third_chunk(rows) -> int:
    return int(rows[1]["work_units"]) + (int(rows[2]["work_units"]) - int(rows[1]["work_units"])) // 2


@pytest.mark.parametrize("engine", ["python", "rust"])
def test_a_chunk_that_passes_the_budget_is_cut_inside_and_the_seed_ends_on_its_last_whole_chunk(
        law, policy, engine, monkeypatch):
    rows = _run(law, policy, engine)["sampling_checkpoints"]
    assert len(rows) >= 3, "the case needs a third chunk to cut"
    budget = _a_budget_inside_the_third_chunk(rows)
    between = _run(law, dict(policy, work_budget=budget), engine)
    assert between["rung_terminal"]["chunks"] == 2 and "cut_inside_a_chunk" not in between["rung_terminal"]["work"]
    monkeypatch.setattr(O, "predicted_chunk_units", lambda *args, **kwargs: 0)
    cut = _run(law, dict(policy, work_budget=budget), engine)
    terminal = cut["rung_terminal"]
    assert (terminal["reason"], terminal["chunks"]) == ("budget", 2), "a chunk admitted on a prediction too low"
    inside = terminal["work"]["cut_inside_a_chunk"]
    assert inside["multiplier"] == rows[2]["multiplier"] and inside["chain"] in CL.ran_names(cut)
    a_check = int(rows[2]["work_units"]) // max(1, int(rows[2]["moves"])) * 4 * engine_module.WORK_CHECK_MOVES
    assert budget <= inside["units"] <= budget + a_check, "it stops within one check of the budget, on any machine"
    assert terminal["work"]["units"] == rows[1]["work_units"] <= budget, "what it reads is its last whole chunk"
    assert _but_the_prediction(cut["sampling_checkpoints"]) == _but_the_prediction(between["sampling_checkpoints"])
    for name in CL.ran_names(cut):
        assert CL.sorted_edges(cut, name) == CL.sorted_edges(between, name), name
    assert terminal["classification"] == between["rung_terminal"]["classification"]


def test_both_engines_cut_a_chunk_at_the_same_move_and_the_same_work(law, policy, monkeypatch):
    require_rust_engine()
    rows = _run(law, policy)["sampling_checkpoints"]
    monkeypatch.setattr(O, "predicted_chunk_units", lambda *args, **kwargs: 0)
    budget = _a_budget_inside_the_third_chunk(rows)
    cuts = [_run(law, dict(policy, work_budget=budget), engine)["rung_terminal"]["work"]["cut_inside_a_chunk"]
            for engine in ("python", "rust")]
    assert cuts[0] == cuts[1] and cuts[0]["at_move"] % engine_module.WORK_CHECK_MOVES == (
        engine_module.WORK_CHECK_MOVES - 1), cuts


def test_the_first_chunk_runs_whole_whatever_the_budget(law, policy):
    ended = _run(law, dict(policy, work_budget=1))
    terminal = ended["rung_terminal"]
    assert (terminal["reason"], terminal["chunks"]) == ("budget", 1)
    assert "cut_inside_a_chunk" not in terminal["work"] and terminal["work"]["units"] > 1, (
        "a seed has no whole chunk to end on before its first: a law's first chunk is weighed before it is bought")


@pytest.mark.parametrize("engine", ["python", "rust"])
def test_a_seed_saved_inside_its_chunks_on_a_period_of_work_reads_what_it_reads_unsaved(law, policy, engine):
    plain = _run(law, policy, engine, save_every_units=None)
    rows = plain["sampling_checkpoints"]
    saved = []
    period = int(rows[0]["work_units"]) // 3
    often = _run(law, policy, engine, save_every_units=period,
                 on_chunk=lambda state: saved.append(dict(state, history=list(state["history"]))))
    assert _stable(often) == _stable(plain), "a save inside a chunk changes nothing the seed reads"
    inside = [state for state in saved if state.get("in_chunk")]
    assert len(inside) >= 5, "a chunk longer than the period is saved inside"
    first = [state for state in inside if not state["history"]]
    assert first and all("whole" not in state for state in first), "nothing whole before the first chunk ends"
    later = [state for state in inside if state["history"]]
    assert later and all(state["whole"]["checkpoint"]["chains"] and "sampling_checkpoint" not in
                         state["whole"]["envelope"] for state in later), "the last whole chunk rides beside it"
    whole = [state for state in saved if not state.get("in_chunk")]
    assert whole and all("sampling_checkpoint" not in state["whole_envelope"] for state in whole)


def _as_read_from_disk(state: dict) -> dict:
    return json.loads(json.dumps(state))


@pytest.mark.parametrize("where", ["inside the chunk", "where a chunk ended"])
def test_a_seed_resumed_from_its_save_is_cut_at_the_budget_as_one_never_stopped(law, policy, where, monkeypatch):
    rows = _run(law, policy)["sampling_checkpoints"]
    budget = _a_budget_inside_the_third_chunk(rows)
    monkeypatch.setattr(O, "predicted_chunk_units", lambda *args, **kwargs: 0)
    never_stopped = _run(law, dict(policy, work_budget=budget))
    saved = []
    period = (int(rows[1]["work_units"]) - int(rows[0]["work_units"])) // 3
    _run(law, dict(policy, work_budget=budget), save_every_units=period, on_chunk=lambda state: saved.append(
        _as_read_from_disk(state)))
    if where == "inside the chunk":
        state = [s for s in saved if s.get("in_chunk") and len(s["history"]) == 2][0]
    else:
        state = [s for s in saved if not s.get("in_chunk") and len(s["history"]) == 2][0]
    resumed = _run(law, dict(policy, work_budget=budget), resume=state)
    terminal = resumed["rung_terminal"]
    assert (terminal["reason"], terminal["chunks"]) == ("budget", 2)
    assert terminal["work"]["cut_inside_a_chunk"] == never_stopped["rung_terminal"]["work"]["cut_inside_a_chunk"]
    assert _stable(resumed["sampling_checkpoints"]) == _stable(never_stopped["sampling_checkpoints"])
    for name in CL.ran_names(resumed):
        assert CL.sorted_edges(resumed, name) == CL.sorted_edges(never_stopped, name), name
    assert terminal["classification"] == never_stopped["rung_terminal"]["classification"]


def test_a_state_saved_before_840_goes_on_and_its_chunk_runs_whole(law, policy, monkeypatch):
    rows = _run(law, policy)["sampling_checkpoints"]
    budget = _a_budget_inside_the_third_chunk(rows)
    monkeypatch.setattr(O, "predicted_chunk_units", lambda *args, **kwargs: 0)
    saved = []
    _run(law, dict(policy, work_budget=budget), on_chunk=lambda state: saved.append(_as_read_from_disk(state)))
    old = [s for s in saved if not s.get("in_chunk") and len(s["history"]) == 2][0]
    old.pop("whole_envelope")
    resumed = _run(law, dict(policy, work_budget=budget), resume=old)
    work = resumed["rung_terminal"]["work"]
    assert "cut_inside_a_chunk" not in work and resumed["rung_terminal"]["chunks"] >= 3, (
        "with no whole chunk in its state there is nothing to end on, so that one chunk runs as it did before")


def test_a_chunk_stopped_at_a_point_of_work_stops_alike_on_both_engines_and_goes_on_to_the_chunk_never_stopped(
        law, policy):
    require_rust_engine()
    weights = [O.work_weights(policy)[name] for name in O.WORK_PARTS]
    runs = {name: resolve_engine({"engine": name})[1] for name in ("python", "rust")}
    asked = {"record_points": 30, "target_sweeps": 40}
    whole = {name: run(law, 128, 2, **asked) for name, run in runs.items()}
    total = O.units_of(O.seed_work_parts(CL.move_accounting(whole["rust"])), O.work_weights(policy))
    for share in (0.05, 0.5, 0.77):
        stopped = {name: run(law, 128, 2, work_budget=int(total * share), work_weights=weights, **asked)
                   for name, run in runs.items()}
        python, rust = stopped["python"], stopped["rust"]
        assert python["stopped"] and python["termination"] == rust["termination"], share
        assert python["termination"]["reason"] == "work_budget" and python["work_units"] == rust["work_units"]
        assert int(total * share) <= python["work_units"], "it stops once the work is there, not before"
        assert _stable(python["sampling_checkpoint"]) == _stable(rust["sampling_checkpoint"]), share
        for name, run in runs.items():
            went_on = run(law, 128, 2, resume_checkpoint=json.loads(json.dumps(stopped[name]["sampling_checkpoint"])),
                          **asked)
            assert _stable(went_on) == _stable(whole[name]), (name, share)
    past = runs["rust"](law, 128, 2, work_budget=total + 1, work_weights=weights, **asked)
    assert _stable(past) == _stable(whole["rust"]), "a point of work the chunk does not reach changes nothing"
