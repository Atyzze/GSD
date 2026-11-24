from __future__ import annotations

from graph_scale_dynamics.scheduling import memory as M

G = 10 ** 9
HOST = M.MemorySnapshot(total=98746621952, available=47731810304)
QUANTILES = {("simulation", 65536): (int(0.30 * G), int(0.40 * G)),
             ("simulation", 262144): (int(1.8 * G), int(3.5 * G)),
             ("simulation", 1048576): (int(12.5 * G), int(14.0 * G))}
RUNNING = [{"kind": "simulation", "id": "a", "n": 65536, "reserved_bytes": int(0.9 * G), "current_bytes": int(0.28 * G)},
           {"kind": "simulation", "id": "b", "n": 65536, "reserved_bytes": int(0.9 * G), "current_bytes": int(0.28 * G)},
           {"kind": "simulation", "id": "c", "n": 262144, "reserved_bytes": int(4.0 * G), "current_bytes": int(1.13 * G)},
           {"kind": "simulation", "id": "d", "n": 1048576, "reserved_bytes": int(17.3 * G),
            "current_bytes": int(5.25 * G)}]
TAKEN = {"kind": "simulation", "id": "e", "n": 1048576, "reserved_bytes": 0, "current_bytes": None}


def headroom(rows):
    return M.admission_headroom(None, snapshot=HOST, observations=rows, quantiles=QUANTILES)


def test_the_seed_being_admitted_is_not_memory_still_to_come():
    alone = headroom(RUNNING)
    asking = headroom(RUNNING + [TAKEN])
    assert asking["unrealised_bytes"] == alone["unrealised_bytes"]
    assert asking["headroom_bytes"] == alone["headroom_bytes"] > int(15.4 * G), \
        "the 15.4 GB a seed at 1,048,576 asks fits in what the four running children leave"


def test_seeds_other_workers_are_taking_cost_nothing_until_admitted():
    others = headroom(RUNNING + [TAKEN, dict(TAKEN, id="f"), dict(TAKEN, id="g", n=262144)])
    assert others["headroom_bytes"] == headroom(RUNNING)["headroom_bytes"]


def test_a_child_that_shows_memory_counts_even_with_no_reservation_written():
    showing = dict(TAKEN, current_bytes=int(2 * G))
    assert headroom(RUNNING + [showing])["unrealised_bytes"] > headroom(RUNNING)["unrealised_bytes"]


def test_an_admitted_seed_that_has_not_started_counts_its_typical_peak():
    admitted = dict(TAKEN, reserved_bytes=int(15.4 * G))
    grown = headroom(RUNNING + [admitted])["unrealised_bytes"] - headroom(RUNNING)["unrealised_bytes"]
    assert grown >= QUANTILES[("simulation", 1048576)][0]


def test_with_room_beyond_the_floor_the_diagnosis_does_not_say_floor():
    from graph_scale_dynamics.operations.compute_ecology import memory_floor_verdict
    operators = {"total_bytes": 98746621952, "available_bytes": 47731810304, "floor_bytes": 10737418240,
                 "shed_below_bytes": 8589934592, "unrealised_bytes": 13967793358, "headroom_bytes": 23026598706,
                 "small_pool_limit_bytes": 987466219}
    state, severity, text = memory_floor_verdict(operators, waiting=1846, deferred=12, idle=12, slots=16)
    assert (state, severity) == ("SEEDS_LARGER_THAN_HEADROOM", "normal")
    assert "not at its floor" in text and "21.4 GiB headroom" in text and "down to" not in text
    at_floor = dict(operators, headroom_bytes=int(0.5 * G))
    assert memory_floor_verdict(at_floor, waiting=1846, deferred=12, idle=12, slots=16)[0] == "MEMORY_FLOOR"
