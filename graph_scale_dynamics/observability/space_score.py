from __future__ import annotations

import math
import statistics

CONTRACT = "gsd-space-score-2"
FROM_N = 1024
MARGINS = {"dimension": 0.15, "per_node": 0.02, "curvature": 0.02, "piece": 0.02}
FULL_ENDS = ("completed", "ceiling", "frozen")
CHAINS = ("empty", "given")
DIMENSION_PROBES = ("d_s", "d_V", "d_B")
LOCAL = (("mean_degree", "mean degree"), ("triangles_per_node", "triangles a node"),
         ("squares_per_node", "squares a node"), ("kappa", "curvature"))
PROPERTIES = (("dimension", "dimension"), ("agree", "the probes agree"), ("walk", "d_w is 2"),
              ("reach", "reach grows as N^(1/d)"), ("local", "local structure"), ("piece", "one piece"))
STAGES = (("full", "the runs are full readings"), ("space", "a chain is a space"),
          ("closing", "the other chain closes part of the gap"), ("met", "the chains meet"))
FEELS_BANDS = ((1.0001, "none"), (3.0, "up to x3"), (30.0, "x3 to x30"), (1000.0, "x30 to x1,000"),
               (math.inf, "past x1,000"))
FEELS_FROM, FEELS_TO = 64, 65536


def _num(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return None


def _mean(block) -> float | None:
    return _num(block.get("mean")) if isinstance(block, dict) else None


EXACT = "_exact_distance"


def _short(value: float | None) -> float | None:
    return None if value is None else float(f"{value:.3g}")


def _per_node_distance(a: float, b: float) -> float:
    return abs(a - b) / (MARGINS["per_node"] * max(abs(a), abs(b), 1.0))


def _probe(block) -> float | None:
    if not isinstance(block, dict):
        return None
    seeds, of = block.get("seeds"), block.get("of")
    if isinstance(seeds, int) and isinstance(of, int) and of > 0 and 2 * seeds <= of:
        return None
    return _mean(block)


def _probe_median(side: dict) -> float | None:
    read = [v for v in (_probe(side.get(p)) for p in DIMENSION_PROBES) if v is not None]
    return statistics.median(read) if read else None


def _judged(rungs: list[dict]) -> list[dict]:
    return [r for r in rungs if int(r.get("n") or 0) >= FROM_N]


def chain_dimension(rungs: list[dict], chain: str) -> int | None:
    medians = [m for m in (_probe_median(r.get(chain) or {}) for r in _judged(rungs)) if m is not None]
    return max(2, int(math.floor(statistics.median(medians) + 0.5))) if medians else None


def _local(side: dict, before: dict) -> dict | None:
    worst = None
    for key, name in LOCAL:
        a, b = _mean(side.get(key)), _mean(before.get(key))
        if a is None or b is None:
            continue
        distance = abs(a - b) / MARGINS["curvature"] if key == "kappa" else _per_node_distance(a, b)
        if worst is None or distance > worst["distance"]:
            worst = {"distance": distance, "worst": name, "reading": _short(a), "before": _short(b)}
    return worst


def chain_reading(rungs: list[dict], chain: str) -> dict:
    d = chain_dimension(rungs, chain)
    out, before, exact = [], None, []
    for rung in _judged(rungs):
        side = rung.get(chain) or {}
        n = int(rung["n"])
        props: dict = {}
        median = _probe_median(side)
        if median is not None and d is not None:
            props["dimension"] = {"distance": abs(median - d) / MARGINS["dimension"], "reading": _short(median),
                                  "target": d}
        read = [v for v in (_probe(side.get(p)) for p in DIMENSION_PROBES) if v is not None]
        if len(read) >= 2:
            props["agree"] = {"distance": (max(read) - min(read)) / (2 * MARGINS["dimension"]),
                              "reading": _short(max(read) - min(read))}
        walk = _probe(side.get("d_w"))
        if walk is not None:
            props["walk"] = {"distance": abs(walk - 2.0) / MARGINS["dimension"], "reading": _short(walk), "target": 2}
        if before is not None:
            reach, reach_before = _mean(side.get("reach")), _mean(before[1].get("reach"))
            if reach and reach_before and d is not None:
                exponent = math.log(reach / reach_before) / math.log(n / before[0])
                props["reach"] = {"distance": abs(exponent - 1.0 / d) * d * d / MARGINS["dimension"],
                                  "reading": _short(exponent), "target": _short(1.0 / d), "from_n": before[0]}
            local = _local(side, before[1])
            if local is not None:
                props["local"] = {**local, "from_n": before[0]}
        giant = _mean(side.get("giant_fraction"))
        if giant is not None:
            props["piece"] = {"distance": max(0.0, 1.0 - giant) / MARGINS["piece"], "reading": _short(giant)}
        worst = max(props.items(), key=lambda kv: kv[1]["distance"]) if props else None
        exact.append(worst[1]["distance"] if worst else None)
        for prop in props.values():
            prop["distance"] = _short(prop["distance"])
        out.append({"n": n, "distance": worst[1]["distance"] if worst else None, "worst": worst[0] if worst else None,
                    "properties": props})
        before = (n, side)
    judged = [r for r in out if r["distance"] is not None]
    space = (len(out) >= 2 and all("dimension" in r["properties"] and e is not None and e <= 1.0
                                   for r, e in zip(out, exact)))
    return {"d": d, "space": space, "worst": max((r["distance"] for r in judged), default=None), "rungs": out}


def _margin(key: str, x: float, y: float) -> float:
    if key in (*DIMENSION_PROBES, "d_w"):
        return MARGINS["dimension"]
    if key == "kappa":
        return MARGINS["curvature"]
    if key == "giant_fraction":
        return MARGINS["piece"]
    if key in ("energy_per_node", "reach"):
        return MARGINS["per_node"] * max(abs(x), abs(y))
    return MARGINS["per_node"] * max(abs(x), abs(y), 1.0)


COMPARED = (*DIMENSION_PROBES, "d_w", "mean_degree", "triangles_per_node", "squares_per_node", "kappa",
            "energy_per_node", "reach", "giant_fraction")


def _gap(rung: dict, other: str = "given") -> dict:
    a, b = rung.get("empty") or {}, rung.get(other) or {}
    gaps: dict = {}
    probes = (*DIMENSION_PROBES, "d_w")
    for key in COMPARED:
        read = _probe if key in probes else _mean
        x, y = read(a.get(key)), read(b.get(key))
        if x is None or y is None:
            continue
        noise = 2.0 * math.hypot(_num((a.get(key) or {}).get("se")) or 0.0, _num((b.get(key) or {}).get("se")) or 0.0)
        gaps[key] = abs(x - y) / max(_margin(key, x, y), noise, 1e-9)
    worst = max(gaps.items(), key=lambda kv: kv[1]) if gaps else None
    return {"n": int(rung["n"]), "distance": _short(worst[1]) if worst else None, "worst": worst[0] if worst else None,
            "quantities": {k: _short(v) for k, v in gaps.items()}, EXACT: worst[1] if worst else None}


def coupling_spread(terms: list[dict], low: int = FEELS_FROM, high: int = FEELS_TO) -> dict:
    from graph_scale_dynamics.dsl.dsl import coefficient
    worst, pair = 1.0, None
    for i, a in enumerate(terms):
        for b in terms[i + 1:]:
            ends = [coefficient(a, n) / coefficient(b, n) for n in (low, high) if coefficient(b, n)]
            if len(ends) != 2 or not ends[0]:
                continue
            factor = abs(ends[1] / ends[0])
            factor = max(factor, 1 / factor) if factor else math.inf
            if factor > worst:
                worst, pair = factor, [f"{a['op']}[{a['coeff']['scale']}]", f"{b['op']}[{b['coeff']['scale']}]"]
    return {"factor": worst, "between": pair}


def feels_band(factor: float | None) -> str | None:
    if factor is None or not math.isfinite(factor):
        return None
    shown = round(float(factor), 1)
    return next(name for edge, name in FEELS_BANDS if shown <= edge)


def feels_n(terms: list[dict], zero_temperature: bool) -> dict:
    knows = any((t.get("coeff") or {}).get("scale") != "one" for t in terms)
    if not zero_temperature:
        return {"band": "felt at a finite temperature" if knows else "none", "knows_n": knows}
    spread = coupling_spread(terms)
    factor = spread["factor"]
    return {"band": feels_band(factor), "knows_n": knows,
            "factor": round(factor, 1) if math.isfinite(factor) else None, "between": spread["between"],
            "from_n": FEELS_FROM, "to_n": FEELS_TO}


def _full(rungs: list[dict]) -> dict:
    cut = []
    for rung in rungs:
        ends = rung.get("ends") or {}
        bad = {k: v for k, v in ends.items() if k not in FULL_ENDS}
        if bad or not ends:
            cut.append({"n": int(rung["n"]), "ends": bad or {"not recorded": rung.get("seeds")}})
    return {"passed": bool(rungs) and not cut, "cut": cut}


def _closes(gaps: list[dict]) -> bool:
    return len(gaps) >= 2 and (gaps[-1][EXACT] <= 1.0 or gaps[-1][EXACT] < gaps[0][EXACT])


def _meets(gaps: list[dict]) -> bool:
    return len(gaps) >= 2 and all(g[EXACT] <= 1.0 for g in gaps)


def _shown(gaps: list[dict]) -> list[dict]:
    return [{k: v for k, v in g.items() if k != EXACT} for g in gaps]


def space_score(chains: dict, spec: dict | None = None) -> dict:
    rungs = sorted((chains or {}).get("rungs") or [], key=lambda r: int(r.get("n") or 0))
    names = [str(c.get("key")) for c in ((chains or {}).get("every_chain") or [])[2:] if isinstance(c, dict)]
    if names:
        rungs = [{**r, **{name: block for name, block in (r.get("more_given") or {}).items() if name in names}}
                 for r in rungs]
    readings = {chain: chain_reading(rungs, chain) for chain in (*CHAINS, *names)}
    gaps = [g for g in (_gap(r) for r in _judged(rungs)) if g["distance"] is not None]
    more_gaps = {name: [g for g in (_gap(r, name) for r in _judged(rungs)) if g["distance"] is not None]
                 for name in names}
    full = _full(rungs)
    spaces = [chain for chain in readings if readings[chain]["space"]]
    closing = _closes(gaps) and all(_closes(series) for series in more_gaps.values())
    met = _meets(gaps) and all(_meets(series) for series in more_gaps.values())
    passed = {"full": full["passed"], "space": bool(spaces), "closing": closing, "met": met}
    stage = 0
    for key, _name in STAGES:
        if not passed[key]:
            break
        stage += 1
    dynamics = (spec or {}).get("dynamics") or {}
    zero_temperature = bool(dynamics.get("zero_temperature", (chains or {}).get("zero_temperature", False)))
    facts = {"zero_temperature": zero_temperature, "beta": _num(dynamics.get("beta")),
             "given_start": (chains or {}).get("given_start"),
             "given_probes_read": bool((chains or {}).get("given_probes_read"))}
    terms = (spec or {}).get("terms")
    if isinstance(terms, list) and all(isinstance(t, dict) and isinstance(t.get("coeff"), dict) for t in terms):
        facts["feels_n"] = feels_n(terms, zero_temperature)
    out = {"contract": CONTRACT, "from_n": FROM_N, "margins": dict(MARGINS),
           "judged": [int(r["n"]) for r in _judged(rungs)], "stage": stage, "of": len(STAGES),
           "stages": [{"key": key, "name": name, "passed": passed[key]} for key, name in STAGES],
           "spaces": spaces, "full": full, "chains": readings, "gaps": _shown(gaps), "facts": facts}
    if names:
        out["more_gaps"] = {name: _shown(series) for name, series in more_gaps.items()}
    return out
