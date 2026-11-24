from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import coverage_reading as C  # noqa: E402

OPS = ("edge_count", "triangle_count", "square_count", "degree_square_sum", "wedge_count")


def law(rng: random.Random, *, hole: str | None = None) -> dict:
    while True:
        ops = [rng.choice(OPS) for _ in range(rng.choice((1, 2, 3, 4)))]
        if hole is None or hole not in ops:
            break
    return {"terms": [[op, None, rng.choice((-1, 1)) * rng.uniform(0.05, 2.0), rng.choice(("one", "log_N")), None]
                      for op in ops],
            "zero_temperature": rng.random() < 0.3, "beta": 10 ** rng.uniform(-1, 2),
            "local_move": "toggle", "locality": rng.random(), "swap_share": rng.random()}


def stratum(compact: dict) -> str:
    return ("zeroT" if compact["zero_temperature"] else "finiteT") + ("/3-4" if len(compact["terms"]) > 2 else "/1-2")


def stratified(rng: random.Random, size: int, *, hole: str | None = None) -> list[dict]:
    wanted = ("zeroT/1-2", "zeroT/3-4", "finiteT/1-2", "finiteT/3-4")
    out = []
    while len(out) < size:
        target = wanted[len(out) % len(wanted)]
        candidate = law(rng, hole=hole if target == "finiteT/1-2" else None)
        if stratum(candidate) == target:
            out.append(candidate)
    return out


def read(measured: list[dict], run: list[dict], weights=None) -> dict:
    return C.compare([C.features(c) for c in measured], [stratum(c) for c in measured],
                     [C.features(c) for c in run], [stratum(c) for c in run], weights)


def flagged(result: dict, key: str) -> list[tuple[str, str]]:
    return [(axis, row["value"]) for axis, body in result["axes"].items() for row in body["rows"] if row[key]]


def test_a_sample_from_the_measure_itself_is_neither_thin_nor_thick_though_its_strata_are_reallocated():
    rng = random.Random(1)
    result = read([law(rng) for _ in range(20_000)], stratified(rng, 4_000))
    assert flagged(result, "thin") == [] and flagged(result, "thick") == []
    assert result["within_strata"] == []
    assert result["strata"]["zeroT/3-4"]["laws"] == 1_000
    assert result["axes"]["temperature"]["total_variation"] < 0.02


def test_a_hole_planted_in_one_stratum_is_thin_there_and_nothing_else_is():
    rng = random.Random(2)
    result = read([law(rng) for _ in range(20_000)], stratified(rng, 4_000, hole="square_count"))
    within = [(r["stratum"], r["axis"], r["value"]) for r in result["within_strata"] if r["thin"]]
    assert ("finiteT/1-2", "operator", "square_count") in within
    assert all("square_count" in value for _h, _axis, value in within)
    assert not [r for r in result["within_strata"] if r["thick"] and "square_count" in r["value"]]
    assert all("square_count" in value for _axis, value in flagged(result, "thin"))


def test_the_gate_s_weights_restore_what_it_skipped():
    rng = random.Random(3)
    measured = [law(rng) for _ in range(20_000)]
    drawn = stratified(rng, 6_000)
    run, weights = [], []
    for compact in drawn:
        gated = any(term[0] == "triangle_count" for term in compact["terms"])
        if not gated:
            run.append(compact)
            weights.append(1.0)
        elif rng.random() < 0.25:
            run.append(compact)
            weights.append(4.0)
    unweighted = read(measured, run)
    assert ("operator", "triangle_count") in flagged(unweighted, "thin")
    weighted = read(measured, run, weights)
    assert ("operator", "triangle_count") not in flagged(weighted, "thin")
    row = next(r for r in weighted["axes"]["operator"]["rows"] if r["value"] == "triangle_count")
    assert row["run_ratio"] < 0.5 and 0.85 < row["ratio"] < 1.15


def test_the_bins_close_at_the_grid_s_top():
    assert C._bin(2.0, C.MAGNITUDE_EDGES) == "1.6 to 2"
    assert C._bin(100.0, C.BETA_EDGES) == "31.6 to 100"
    assert C._bin(0.99, C.SHARE_EDGES) == "0.8 to 1"
    assert C._bin(0.01, C.MAGNITUDE_EDGES) is None
