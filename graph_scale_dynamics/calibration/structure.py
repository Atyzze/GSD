from __future__ import annotations

import math

STRUCTURE_CONTRACT = "calibration-structure-2"
GAP_MAX_N = 1_048_576
CLIQUE_MAX_N = 1_048_576
SQUARE_MAX_N = 1_048_576
LIMITS_BEFORE_531 = {"gap_max_n": 1_048_576, "clique_max_n": 262_144, "square_max_n": 262_144}
CENSUS_MEMORY_FILE = "census_memory.json"
CENSUS_MEMORY_CONTRACT = "census-memory-1"


def census_memory_path():
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "resources" / "memory" / CENSUS_MEMORY_FILE


def committed_census_memory() -> dict | None:
    import json

    path = census_memory_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
FIXED_GRAPH_SEEDS = 1
DRAWN_GRAPH_SEEDS = 3
SHIFT_INVERT_BELOW_DIMENSION = 2.5

AVERAGED = ("mean_degree", "giant_fraction", "components", "cycle_rank_per_node", "gap",
            "diameter_lower", "diameter_upper", "degeneracy", "triangles_per_node",
            "largest_clique", "squares_per_node", "assortativity", "seconds")


def wanted(family: dict, seed: int) -> bool:
    drawn = bool(family.get("graph_varies_per_seed")) and callable(family.get("build_seeded"))
    return int(seed) < (DRAWN_GRAPH_SEEDS if drawn else FIXED_GRAPH_SEEDS)


def summary(n: int, edges) -> dict:
    from graph_scale_dynamics.measurements.structure_census import census

    c = census(n, edges, gap_max_n=GAP_MAX_N, shift_invert_below_dimension=SHIFT_INVERT_BELOW_DIMENSION,
               clique_max_n=CLIQUE_MAX_N, square_max_n=SQUARE_MAX_N)
    giant = c["largest_component"]
    gap = giant.get("spectral_gap") or {}
    cliques = c.get("cliques") or {}
    n = int(n)

    def per_node(value):
        return None if value is None or not n else float(value) / n

    return {
        "contract": STRUCTURE_CONTRACT, "census_contract": c["contract"], "n": n,
        "edges": int(c["edges"]), "mean_degree": (2.0 * c["edges"] / n) if n else None,
        "components": int(c["components"]["count"]),
        "giant_fraction": per_node(giant["size"]),
        "cycle_rank_per_node": per_node(giant["cycle_rank"]),
        "gap": gap.get("value"), "gap_method": gap.get("method"), "gap_reason": gap.get("reason"),
        "gap_seconds": gap.get("seconds"),
        "diameter_lower": giant["diameter"]["lower_bound"],
        "diameter_upper": giant["diameter"]["upper_bound"],
        "degeneracy": (c.get("k_core") or {}).get("degeneracy"),
        "triangles_per_node": per_node(cliques.get("triangles")),
        "largest_clique": cliques.get("largest_clique"),
        "largest_clique_exact": cliques.get("largest_clique_exact"),
        "squares_per_node": per_node(c.get("squares")),
        "assortativity": c.get("assortativity"),
        "seconds": c.get("seconds"),
    }


def cut_off(record: dict | None) -> bool:
    if not isinstance(record, dict) or record.get("error"):
        return False
    n = int(record.get("n") or 0)
    return ((record.get("gap") is None and "not computed above" in str(record.get("gap_reason") or ""))
            or (record.get("triangles_per_node") is None and n > LIMITS_BEFORE_531["clique_max_n"])
            or (record.get("squares_per_node") is None and n > LIMITS_BEFORE_531["square_max_n"]))


def measure(n: int, edges) -> dict:
    try:
        return summary(n, edges)
    except Exception as exc:  # noqa: BLE001
        return {"contract": STRUCTURE_CONTRACT, "error": f"{type(exc).__name__}: {exc}"}


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def rung_structure(cells: list[dict]) -> dict | None:
    records = [c.get("structure") for c in cells]
    records = [r for r in records if isinstance(r, dict) and not r.get("error")]
    if not records:
        errors = [c["structure"]["error"] for c in cells
                  if isinstance(c.get("structure"), dict) and c["structure"].get("error")]
        return {"seeds": 0, "error": errors[0]} if errors else None
    out = {"seeds": len(records)}
    for key in AVERAGED:
        values = [float(r[key]) for r in records if _finite(r.get(key))]
        out[key] = (sum(values) / len(values)) if values else None
        if key in ("gap", "diameter_lower") and len(values) >= 2:
            mean = out[key]
            out[f"{key}_spread"] = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
    methods = sorted({str(r.get("gap_method")) for r in records if r.get("gap_method")})
    out["gap_method"] = "/".join(methods) or None
    if out["gap"] is None:
        out["gap_reason"] = next((r.get("gap_reason") for r in records if r.get("gap_reason")), None)
    out["largest_clique_exact"] = all(r.get("largest_clique_exact") is not False for r in records)
    return out


def _slope(lo: dict, hi: dict, key: str):
    a, b = lo.get(key), hi.get(key)
    if not (_finite(a) and _finite(b)) or a <= 0 or b <= 0:
        return None
    size_a = lo["n"] * (lo.get("giant_fraction") or 1.0)
    size_b = hi["n"] * (hi.get("giant_fraction") or 1.0)
    if size_b <= size_a:
        return None
    return math.log(b / a) / math.log(size_b / size_a)


def local_exponents(rows: list[dict]) -> None:
    measured = [r for r in sorted(rows, key=lambda r: r["n"]) if isinstance(r.get("structure"), dict)
                and r["structure"].get("seeds")]
    for lo, hi in zip(measured, measured[1:], strict=False):
        a = dict(lo["structure"], n=lo["n"])
        b = dict(hi["structure"], n=hi["n"])
        s = hi["structure"]
        s["gap_slope"] = _slope(a, b, "gap")
        s["diameter_slope"] = _slope(a, b, "diameter_lower")
        s["implied_d_s"] = (-2.0 / s["gap_slope"]) if _finite(s["gap_slope"]) and s["gap_slope"] < -1e-9 else None
        s["implied_d_f"] = ((1.0 / s["diameter_slope"])
                            if _finite(s["diameter_slope"]) and s["diameter_slope"] > 1e-9 else None)
