from __future__ import annotations

import json
from functools import lru_cache

from graph_scale_dynamics.measurements import starts as the_starts
from graph_scale_dynamics.research import dimension_test as T
from graph_scale_dynamics.resources import committed

RULE_CONTRACT = "gsd-dimension-rule-1"
GROWN = {"empty": the_starts.EMPTY, "given": the_starts.RANDOM}
LATTICES = {start.name: start.name for start in the_starts.known_lattices()}
KEPT_FATES = ("holds", "unmoved")
LINE_BELOW = 1.5
SHOWN = ("mean_degree", "giant_fraction", "reach", "d_s", "d_V", "d_B", "d_w", "triangles_per_node",
         "squares_per_node", "kappa")
KINDS = ("grown", "changed", "kept_d")


CALIBRATED_ON = {"criterion": "dimension_test_criterion_4.json", "training": "dimension_test_4_training.json",
                 "judged": "dimension_test_4_judged.json"}


@lru_cache(maxsize=1)
def calibration() -> dict:
    judged = json.loads(committed.path(CALIBRATED_ON["judged"]).read_text(encoding="utf-8"))
    criterion = json.loads(committed.path(CALIBRATED_ON["criterion"]).read_text(encoding="utf-8"))
    seeds = [s for c in judged["cases"] if c["part"] == "training" and c["expected"] == "dimensional"
             for s in c["seeds"] if s["right"]]
    judged_bands = {case["family"]: case["d"] for case in criterion["training"]["cases"] if case["family"] in LATTICES}
    of_a_dimension = {the_starts.named(name).dimension: band for name, band in judged_bands.items()}
    bands = {start.name: judged_bands.get(start.name) or of_a_dimension[start.dimension]
             for start in the_starts.known_lattices()}
    measured = json.loads(committed.path(CALIBRATED_ON["training"]).read_text(encoding="utf-8"))
    own: dict = {}
    for row in measured["rows"]:
        if row.get("built") and row["family"] in LATTICES and T.mass_dimension(row) is not None:
            own.setdefault(row["family"], {}).setdefault(str(row["n"]), []).append(T.mass_dimension(row))
    lattice_d = {family: {n: round(sum(v) / len(v), 4) for n, v in sorted(by_n.items(), key=lambda x: int(x[0]))}
                 for family, by_n in own.items()}
    for start in the_starts.known_lattices():
        lattice_d.setdefault(start.name, {str(T.RULE.from_n): float(start.dimension)})
    return {"rule": judged["rule"], "lattice_d": lattice_d, "lattice_bands": bands,
            "reach_exponent_checked_down_to": round(min(s["signals"]["reach_exponent"] for s in seeds), 4),
            "d_checked_up_to": round(max(s["d"] for s in seeds), 4)}


def _round(value, digits=3):
    return round(float(value), digits) if isinstance(value, (int, float)) else None


def judged_chain(rows: list, columns: list) -> dict:
    cells = [dict(zip(columns, row, strict=False)) for row in rows or []]
    judged = T.judge_chain(cells)
    found = judged["signals"]
    top = max(cells, key=lambda c: int(c["n"])) if cells else {}
    used = next((c for c in cells if found["sizes"] and int(c["n"]) == found["sizes"][-1]), {})
    return {"verdict": judged["verdict"], "d": _round(judged["d"]), "why": judged["why"], "sizes": found["sizes"],
            "reach_exponent": _round(found.get("reach_exponent")), "growth_gap": _round(found.get("growth_gap")),
            "einstein_gap": _round(found.get("einstein_gap")), "top_n": int(top["n"]) if top else None,
            "at_d": {k: _round(used.get(k), 4) for k in SHOWN}}


def own_d(cal: dict, chain: str, n: int) -> float:
    by_n = cal["lattice_d"][chain]
    below = [int(k) for k in by_n if int(k) <= n]
    return by_n[str(max(below) if below else min(int(k) for k in by_n))]


def kind_of(chain: str, judged: dict, cal: dict) -> str | None:
    if judged["verdict"] != "dimensional":
        return None
    if chain in GROWN:
        return "grown"
    judged["own_d"] = own_d(cal, chain, judged["sizes"][-1])
    low, high = cal["lattice_bands"][chain]
    near = abs(judged["d"] - judged["own_d"]) <= (high - low) / 2
    return "kept_d" if low <= judged["d"] <= high or near else "changed"


def mark(name: str, judged: dict, fate: str | None, cal: dict) -> dict:
    judged["kind"] = kind_of(name, judged, cal)
    judged["fate"] = fate
    judged["beyond_checked"] = judged["kind"] is not None and (
        judged["reach_exponent"] < cal["reach_exponent_checked_down_to"] or judged["d"] > cal["d_checked_up_to"])
    judged["line"] = judged["kind"] is not None and judged["d"] < LINE_BELOW
    return judged


def read_at(judged: dict, n) -> dict:
    sizes = judged.get("sizes") or []
    if judged.get("kind") and (n is None or not sizes or int(sizes[-1]) != int(n)):
        return dict(judged, kind=None, line=False, beyond_checked=False)
    return judged


def tier_of(chains: dict) -> int | None:
    kinds = {c["kind"] for c in chains.values() if c["kind"]}
    if kinds & {"grown", "changed"}:
        return 1
    if any(c["kind"] == "kept_d" and c["fate"] not in KEPT_FATES for c in chains.values()):
        return 2
    return 3 if "kept_d" in kinds else None


def block(values: dict, columns: list, fates: dict, *, read_at_top: bool = False) -> dict:
    cal = calibration()
    chains = {name: mark(name, judged_chain(rows, columns), (fates.get(name) or [None])[0], cal)
              for name, rows in (values or {}).items()}
    stale = []
    if read_at_top:
        top = max((c["top_n"] for c in chains.values() if c.get("top_n") is not None), default=None)
        stale = sorted(name for name, c in chains.items() if c["kind"] and read_at(c, top) is not c)
        chains = {name: read_at(c, top) for name, c in chains.items()}
    tier = tier_of(chains)
    return {"contract": RULE_CONTRACT, "test": T.DIMENSION_TEST_CONTRACT, "tier": tier,
            "chains": {name: {k: c[k] for k in ("verdict", "d", "kind", "fate", "sizes", "reach_exponent",
                                                 "growth_gap", "beyond_checked", "line")}
                       for name, c in chains.items() if c["kind"]},
            **({"not_read_at": {"n": top, "chains": stale}} if stale else {})}
