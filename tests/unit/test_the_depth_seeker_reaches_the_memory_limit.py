from __future__ import annotations

import gzip
import json
import random
import time

import pytest

GIB = 1024 ** 3


def test_the_next_size_is_priced_from_the_law_s_own_peak_growth():
    from graph_scale_dynamics.operations import depth_reach as D
    priced = D.price({16384: 300 * 2 ** 20, 65536: 1 * GIB, 262144: 4 * GIB}, 1048576)
    assert priced["reached"] == 262144 and priced["from"] == "N=65,536 and N=262,144"
    assert priced["growth"] == 1.0 and priced["needs_bytes"] == pytest.approx(16 * GIB * D.SAFETY, rel=1e-6)
    steep = D.price({65536: 1 * GIB, 262144: 32 * GIB}, 1048576)
    assert steep["growth"] == D.GROWTH_MOST, "never priced steeper than quadratic"
    flat = D.price({65536: 2 * GIB, 262144: 2 * GIB}, 1048576)
    assert flat["growth"] == D.GROWTH_LEAST and flat["needs_bytes"] == pytest.approx(8 * GIB * D.SAFETY, rel=1e-6), (
        "never cheaper than linear in N")
    assert D.price({262144: 4 * GIB}, 1048576)["growth"] == 1.0, "one size read: linear from it"
    assert D.price({}, 1048576) is None


def test_a_size_past_the_reach_settles_the_law_at_its_memory_ceiling_and_one_that_fits_is_bought():
    from graph_scale_dynamics.operations import depth_reach as D
    ladder = [64, 4096, 65536, 262144, 1048576, 4194304]
    peaks = {65536: 1 * GIB, 262144: 4 * GIB}
    room = {"reach_bytes": 16 * GIB, "floor_bytes": 10 * GIB}
    found = D.judge(peaks, ladder, room)
    assert found["next_n"] == 1048576 and found["needs_bytes"] > 16 * GIB, "4 GiB at 262,144: about 17.6 at 1,048,576"
    assert found["reach_bytes"] == 16 * GIB and found["free_bytes"] == 10 * GIB
    assert D.judge(peaks, ladder, {"reach_bytes": 40 * GIB, "floor_bytes": 10 * GIB}) is None, "it fits: bought"
    assert D.judge({4194304: 50 * GIB}, ladder, room) is None, "the top of the ladder: nothing to buy"


def test_the_decision_turns_a_purchase_past_the_ceiling_into_a_stop_and_replays_from_its_inputs():
    from graph_scale_dynamics.decisions import engine as E
    from graph_scale_dynamics.decisions import gates as G
    from graph_scale_dynamics.decisions import memory_ceiling as MC
    from graph_scale_dynamics.decisions import replay as R
    entry = {"reached": 262144, "next_n": 1048576, "needs_bytes": 70 * GIB, "reach_bytes": 40 * GIB,
             "free_bytes": 10 * GIB, "from": "N=65,536 and N=262,144"}
    buy = E.Decision(law="a" * 64, action=E.RUN_NEXT, rule="let_through", reason="r", at_n=262144, next_n=1048576)
    settled = MC.settle(buy, entry, E.Policy())
    assert (settled.action, settled.rule, settled.next_n, settled.at_n) == (E.STOP, MC.RULE, None, 262144)
    assert "settled at its memory ceiling" in settled.reason and "70.0 GiB" in settled.reason
    assert settled.facts["memory_ceiling"]["needs_bytes"] == 70 * GIB and settled.facts["refused"]["next_n"] == 1048576
    lower = E.Decision(law="a" * 64, action=E.RUN_NEXT, rule="r", reason="r", at_n=65536, next_n=262144)
    assert MC.settle(lower, entry, E.Policy()) is lower, "a size below the ceiling is bought"
    assert MC.settle(buy, None, E.Policy()) is buy, "no entry, no change: every other campaign decides as before"
    assert MC.RULE in E.PARKING_RULES and not G.BY_NAME[MC.RULE].salted, "a limit, not a verdict: parked, kept"
    value = MC.flag({"14": {"a" * 64: entry}})
    assert MC.entries_of(json.dumps(value), "14") == {"a" * 64: entry} and MC.entries_of(json.dumps(value), "12") == {}
    source = R.replay.__code__.co_names
    assert "memory_settle" in source, "replay applies the recorded entry as the decider did"


def test_the_depth_ladder_is_open_to_4_194_304_in_the_plan():
    from graph_scale_dynamics import PROJECT_ROOT
    from graph_scale_dynamics.operations import focus
    found = focus.plan(PROJECT_ROOT)
    assert found["depth"]["beyond"] == [262144, 1048576, 4194304]
    assert "memory ceiling" in found["depth"]["why"]


def test_a_seed_s_save_packs_its_edges_and_reads_back_the_same_and_fits_1_048_576_s_stop_grace(tmp_path):
    from graph_scale_dynamics.artifact_store import resume_state as R
    rng = random.Random(873)
    edges = [(rng.randrange(1 << 20), rng.randrange(1 << 20)) for _ in range(400_000)]
    state = {"contract": R.RESUME_CONTRACT, "history": [{"chunk": 1}], "seconds_spent": 40.0,
             "checkpoint": {"chains": {"given": {"edge_list": edges, "few": [[1, 2]], "wide": [2 ** 40, 1] * 3000,
                                                 "not": [[1, 2]] * 5000 + [[1, 2, 3]], "flags": [True] * 5000}}}}
    path = tmp_path / "j.json.gz"
    started = time.process_time()
    R.save_resume_state(path, state, execution_spec_hash="h")
    packed_seconds = time.process_time() - started
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        raw = json.load(handle)
    given = raw["checkpoint"]["chains"]["given"]
    assert given["edge_list"][R.PACKED] == "pairs" and given["edge_list"]["type"] == "i"
    assert given["wide"]["type"] == "q" and isinstance(given["not"], list) and isinstance(given["flags"], list)
    back, why = R.load_resume_state(path, execution_spec_hash="h")
    assert why == "resumed" and back["checkpoint"] == json.loads(json.dumps(state["checkpoint"])), (
        "read back exactly as the plain JSON was, every pair a list")
    old = tmp_path / "old.json.gz"
    with gzip.open(old, "wt", encoding="utf-8") as handle:
        json.dump(dict(state, execution_spec_hash="h"), handle)
    assert R.load_resume_state(old, execution_spec_hash="h")[1] == "resumed", "a save made before 873 still reads"
    started = time.process_time()
    with gzip.open(tmp_path / "plain.json.gz", "wt", encoding="utf-8", compresslevel=1) as handle:
        json.dump(state, handle, separators=(",", ":"))
    plain_seconds = time.process_time() - started
    assert packed_seconds * 2 < plain_seconds, f"packed {packed_seconds:.2f}s against plain {plain_seconds:.2f}s"
    at_a_million = packed_seconds / len(edges) * (1048576 * 32 // 2) * 8
    assert at_a_million < R.STOP_GRACE_SECONDS, (
        f"eight chains of 1,048,576 nodes at mean degree 32 save in about {at_a_million:.0f}s of their own work "
        f"here, inside the stop's {R.STOP_GRACE_SECONDS:.0f}s; the processor's time, so a busy host does not "
        f"read as a slow save")
