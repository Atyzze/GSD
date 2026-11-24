from __future__ import annotations

from graph_scale_dynamics.research.structure_reading import law_structure, of_chain

CONTRACT = "every-chain-graph-1"
EMPTY, GIVEN = "empty", "given"


def listed(chains: dict | None, given_start: str | None = None) -> list[dict]:
    every = (chains or {}).get("every_chain")
    if every:
        return [{"key": str(c.get("key")), "name": str(c.get("name") or c.get("key")), "start": c.get("start")}
                for c in every]
    return [{"key": EMPTY, "name": EMPTY, "start": "the empty graph"},
            {"key": GIVEN, "name": GIVEN, "start": (chains or {}).get("given_start") or given_start}]


def census_rungs(measurements: list[dict], chain: str) -> list[dict]:
    from graph_scale_dynamics.measurements.analysis import select_best_runs
    from graph_scale_dynamics.scaleflow.flow import _census_summary
    rows = [m for m in measurements or [] if isinstance(m.get("metrics"), dict)
            and not ((((m.get("metrics") or {}).get("health") or {}).get("sampler") or {}).get("sampler_audit"))]
    by_n: dict[int, list] = {}
    for row in select_best_runs(rows):
        own = of_chain(row["metrics"].get("census"), chain)
        if isinstance(own, dict):
            by_n.setdefault(int(row["n"]), []).append({"census": {EMPTY: own}})
    return [{"n": n, "census": _census_summary(by_n[n])} for n in sorted(by_n)]


def every_chain(measurements: list[dict], chains: dict | None, given_start: str | None = None) -> dict:
    out = []
    for chain in listed(chains, given_start):
        out.append({**chain, "structure": law_structure(measurements, chain=chain["key"]),
                    "census": census_rungs(measurements, chain["key"])})
    return {"contract": CONTRACT, "chains": out}


CURVES_CONTRACT = "every-chain-curves-1"
CURVES = (("return_probability", "t", "p0"), ("volume_growth", "radii", "mean_ball"),
          ("walk_displacement", "times", "mean_square_displacement"), ("box_covering", "radii", "box_counts"))
CURVE_POINTS = 120
CURVES_KEY = "chains"


def _thinned(xs: list, ys: list) -> dict:
    pairs = [(x, y) for x, y in zip(xs or [], ys or [], strict=False)
             if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool)
             and not isinstance(y, bool) and x == x and y == y]
    if len(pairs) > CURVE_POINTS:
        step = len(pairs) / float(CURVE_POINTS)
        kept = sorted({min(len(pairs) - 1, int(round(i * step))) for i in range(CURVE_POINTS)} | {len(pairs) - 1})
        pairs = [pairs[i] for i in kept]
    return {"x": [p[0] for p in pairs], "y": [p[1] for p in pairs]}


def chain_curves(curves: dict | None, chains: list[dict]) -> dict:
    out = {}
    for chain in chains:
        key = chain["key"]
        kept = (curves or {}).get(CURVES_KEY) or {}
        own = curves if key == EMPTY else kept.get(key)
        if not isinstance(own, dict):
            continue
        drawn = {}
        for kind, x, y in CURVES:
            block = own.get(kind)
            if isinstance(block, dict) and block.get(x) and block.get(y):
                drawn[kind] = _thinned(block[x], block[y])
            elif isinstance(block, dict) and block.get("refusal"):
                drawn[kind] = {"x": [], "y": [], "refused": str(block["refusal"])}
        if drawn:
            out[key] = drawn
    return out


def curves_at(measurements: list[dict], n: int, chains: list[dict], load) -> dict:
    from graph_scale_dynamics.measurements.analysis import select_best_runs
    rows = [m for m in select_best_runs([m for m in measurements or [] if isinstance(m.get("metrics"), dict)])
            if int(m["n"]) == int(n)]
    seeds = []
    for row in sorted(rows, key=lambda r: (r.get("seed") is None, r.get("seed"))):
        if not row.get("curves_artifact"):
            continue
        try:
            kept = load(row["curves_artifact"])
        except (OSError, ValueError, KeyError) as exc:
            seeds.append({"seed": row.get("seed"), "error": f"{type(exc).__name__}: {exc}"})
            continue
        seeds.append({"seed": row.get("seed"), "chains": chain_curves(kept, chains)})
    return {"contract": CURVES_CONTRACT, "n": int(n), "chains": chains, "seeds": seeds,
            "kinds": [kind for kind, _x, _y in CURVES]}
