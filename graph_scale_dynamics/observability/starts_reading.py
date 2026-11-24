from __future__ import annotations

import math
from functools import lru_cache

from graph_scale_dynamics.measurements import starts as the_starts
from graph_scale_dynamics.observability import space_score as S

CONTRACT = "gsd-starts-reading-2"
FROM_N = S.FROM_N
MET = 1.0
MIN_SEEDS, NOISE_SIGMAS = 2, 3.0
REACH_SHARE = 0.05
COUNTS = ("triangles_per_node", "squares_per_node")
COMPARED = tuple(key for key in S.COMPARED if key not in ("energy_per_node", "d_w"))
KEPT_AT_LEAST, KEPT_HOLDS, KEPT_AT_MOST = 0.5, 0.8, 2.0
DEGREE_WITHIN = 0.10
MEASURABLE = 16
DENSE_SHARE = 0.5
UNMOVED_WITHIN = 1e-6
UNMOVED_ON = ("mean_degree", "triangles_per_node", "squares_per_node", "giant_fraction", "kappa", "reach")
LATTICES = {start.family: (start.name, start.dimension) for start in the_starts.known_lattices()}
NAMED = {name: family for family, (name, _d) in LATTICES.items()}
FATES = ("holds", "unmoved", "changed", "partly", "stretched", "melted", "fell_apart", "dense")
NO_REFERENCE = "no reference for this start at this size"
STRUCTURE_WITHIN = 0.05
STRUCTURE_ON = ("mean_degree", "squares_per_node", "triangles_per_node")
STRUCTURE_MOVED = "its reach kept, its mean degree, squares or triangles a node moved from its start's"
CLASSES = (("one_space", "every start ends in one shape"), ("grows", "a start without a shape reaches one"),
           ("converts", "a lattice falls into another's shape"), ("selects", "one lattice holds, the others do not"),
           ("holds", "the lattices hold their shapes"), ("forgets", "every start ends alike, no shape"),
           ("remembers", "the starts end apart, no shape held"),
           ("not_read", "not read: fewer than two chains at a size from 1,024"))
CLASS_NAMES = dict(CLASSES)


def _num(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return None


def _short(value: float | None) -> float | None:
    return None if value is None else float(f"{value:.3g}")


def rule() -> dict:
    return {"from_n": FROM_N, "met": MET, "min_seeds": MIN_SEEDS, "noise_sigmas": NOISE_SIGMAS,
            "reach_share": REACH_SHARE, "compared": list(COMPARED), "tolerances": dict(S.MARGINS),
            "kept_at_least": KEPT_AT_LEAST, "kept_holds": KEPT_HOLDS, "kept_at_most": KEPT_AT_MOST,
            "degree_within": DEGREE_WITHIN, "measurable": MEASURABLE, "dense_share": DENSE_SHARE,
            "unmoved_within": UNMOVED_WITHIN, "unmoved_on": list(UNMOVED_ON), "fates": list(FATES),
            "counts": list(COUNTS), "counting_noise": "Poisson, sqrt(x n / seeds + y n / seeds) / n",
            "apart_when": "gap > tolerance + noise_sigmas * combined standard error",
            "classes": [key for key, _name in CLASSES], "law_class": "at its largest size read by two chains or more"}


def _seeds(block: dict) -> int:
    seeds = block.get("seeds")
    return int(seeds) if isinstance(seeds, int) and not isinstance(seeds, bool) else 1


def _probe_as_a_chain_s(cell: dict, probe: str) -> dict:
    channel = (cell.get("channels") or {}).get(probe) or {}
    value = _num(channel.get("value")) if channel.get("valid") else None
    return {"value": value, "withheld": None, "refusal": None if value is not None else channel.get("refusal"),
            "read": True}


def reference_of(cells: list[dict], starts: list[dict]) -> dict | None:
    from graph_scale_dynamics import calibration
    from graph_scale_dynamics.observability import two_chains as T
    if len(cells) < MIN_SEEDS or len(starts) < MIN_SEEDS:
        return None
    start = {probe: T._probe_summary([_probe_as_a_chain_s(cell, probe) for cell in cells], len(cells))
             for probe in T.PROBES}
    for key in calibration.counted_on_a_start():
        start[key] = T._summary([_num(block.get(key)) for block in starts], len(starts))
    start["reach"] = T._summary([_num(cell.get("half_volume_radius")) for cell in cells], len(cells))
    start["energy_per_node"] = T._summary([None] * len(cells), len(cells))
    start["ended_at_cap"] = {"seeds": 0, "of": len(cells)}
    wirings = [block.get("random_wiring") or {} for block in starts]
    reaches = [reach for reach in (_num(wiring.get("reach")) for wiring in wirings) if reach is not None]
    degrees = [degree for degree in (_num(wiring.get("mean_degree")) for wiring in wirings) if degree is not None]
    return {"start": start, "random_reach": round(sum(reaches) / len(reaches), 6) if reaches else None,
            "random_reaches": reaches,
            "random_degree": round(sum(degrees) / len(degrees), 6) if degrees else None,
            "seeds": {"probes": len(cells), "start": len(starts)}}


def references_from(table: dict | None) -> dict:
    from graph_scale_dynamics import calibration
    out: dict = {}
    for (family, n), read in calibration.cells_of_the_lattice_starts(table).items():
        found = reference_of(read["cells"], read["starts"])
        if found is not None:
            out.setdefault(family, {})[n] = found
    return out


@lru_cache(maxsize=1)
def table_references() -> dict:
    from graph_scale_dynamics import calibration
    return references_from(calibration.table_in_force())


def tolerance(key: str, x: float, y: float) -> float:
    if key == "reach":
        return REACH_SHARE * max(abs(x), abs(y))
    return S._margin(key, x, y)


def counting_noise(x: float, y: float, n: int, seeds_x: int, seeds_y: int) -> float:
    n = max(1, int(n))
    return math.sqrt(max(0.0, x) * n / max(1, seeds_x) + max(0.0, y) * n / max(1, seeds_y)) / n


def pair_distance(a: dict, b: dict, n: int | None = None, *, exact: bool = False) -> dict:
    gaps: dict = {}
    for key in COMPARED:
        one, two = a.get(key) or {}, b.get(key) or {}
        x, y = _num(one.get("mean")), _num(two.get("mean"))
        if x is None or y is None or _seeds(one) < MIN_SEEDS or _seeds(two) < MIN_SEEDS:
            continue
        spread = math.hypot(_num(one.get("se")) or 0.0, _num(two.get("se")) or 0.0)
        if key in COUNTS and n:
            spread = max(spread, counting_noise(x, y, n, _seeds(one), _seeds(two)))
        gaps[key] = abs(x - y) / max(tolerance(key, x, y) + NOISE_SIGMAS * spread, 1e-9)
    if not gaps:
        return {"distance": None, "worst": None}
    worst = max(gaps.items(), key=lambda kv: kv[1])
    return {"distance": worst[1] if exact else _short(worst[1]), "worst": worst[0]}


def _met(distances: dict, a: str, b: str) -> bool:
    d = distances.get(pair_key(a, b))
    return d is not None and d <= MET


def _partitions_that_meet(items: list, distances: dict, at_most: list):
    if not items:
        yield []
        return
    first, rest = items[0], items[1:]
    for smaller in _partitions_that_meet(rest, distances, at_most):
        if len(smaller) > at_most[0]:
            continue
        for index in range(len(smaller)):
            if all(_met(distances, first, other) for other in smaller[index]):
                yield smaller[:index] + [[first] + smaller[index]] + smaller[index + 1:]
        if len(smaller) < at_most[0]:
            yield [[first]] + smaller


def groups(names: list[str], distances: dict) -> list[list[str]]:
    listed = list(names)
    if len(listed) > 1 and all(_met(distances, a, b) for i, a in enumerate(listed) for b in listed[i + 1:]):
        return [listed]
    order = {name: i for i, name in enumerate(listed)}
    best, best_key, fewest = None, None, [len(listed)]
    for partition in _partitions_that_meet(listed, distances, fewest):
        total = 0.0
        for group in partition:
            for i, a in enumerate(group):
                for b in group[i + 1:]:
                    total += distances[pair_key(a, b)]
        ordered = sorted((sorted(g, key=order.get) for g in partition), key=lambda g: order[g[0]])
        key = (len(ordered), round(total, 9), [[order[n] for n in g] for g in ordered])
        if best_key is None or key < best_key:
            best, best_key = ordered, key
        fewest[0] = min(fewest[0], len(ordered))
    return best or [[name] for name in names]


def pair_key(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


def _ended_share(side: dict) -> float | None:
    block = side.get("ended_at_cap") or {}
    seeds, of = block.get("seeds"), block.get("of")
    if not isinstance(seeds, int) or not isinstance(of, int) or of <= 0:
        return None
    return seeds / of


def _same(x, y) -> bool:
    x, y = _num(x), _num(y)
    return x is not None and y is not None and abs(x - y) <= UNMOVED_WITHIN * max(1.0, abs(x), abs(y))


def unmoved(side: dict, start: dict) -> bool:
    compared = [key for key in UNMOVED_ON if _num((start.get(key) or {}).get("mean")) is not None]
    return bool(compared) and all(_same((side.get(key) or {}).get("mean"), (start.get(key) or {}).get("mean"))
                                  for key in compared)


def structure_off(side: dict, start: dict) -> float | None:
    found = [_num((side.get(key) or {}).get("mean")) for key in STRUCTURE_ON]
    exact = [_num((start.get(key) or {}).get("mean")) for key in STRUCTURE_ON]
    if None in found or None in exact or not exact[0]:
        return None
    return max(abs(found[0] - exact[0]) / exact[0], abs(found[1] - exact[1]) / max(exact[1], 1.0),
               abs(found[2] - exact[2]) / max(exact[2], 1.0))


def lattice_fate(side: dict, family: str, n: int, references: dict | None = None, *,
                 structure: bool = False) -> dict:
    from graph_scale_dynamics.research.reach import kept as kept_share
    refs = table_references() if references is None else references
    ref = (refs.get(family) or {}).get(int(n))
    if not ref:
        return {"fate": None, "why": NO_REFERENCE}
    start = ref.get("start") or {}
    reach = _num((side.get("reach") or {}).get("mean"))
    share = kept_share(reach, _num(ref.get("random_reach")), _num((start.get("reach") or {}).get("mean")))
    degree, start_degree = _num((side.get("mean_degree") or {}).get("mean")), _num((start.get("mean_degree") or {}).get("mean"))
    moved = (abs(degree - start_degree) / start_degree) if degree is not None and start_degree else None
    out = {"kept": None if share is None else round(share, 3), "degree": _short(degree), "start_degree": _short(start_degree),
           "degree_moved": _short(moved), "like_start": pair_distance(side, start, n)}
    ended = _ended_share(side)
    if ended is not None and ended >= DENSE_SHARE:
        return dict(out, fate="dense", ended_at_cap=_short(ended))
    giant = _num((side.get("giant_fraction") or {}).get("mean"))
    if giant is not None and giant * int(n) < MEASURABLE:
        return dict(out, fate="fell_apart")
    if share is None:
        return dict(out, fate=None, why="no reach to read")
    if share < KEPT_AT_LEAST:
        fate = "melted"
    elif share < KEPT_HOLDS:
        fate = "partly"
    elif share > KEPT_AT_MOST:
        fate = "stretched"
    elif moved is not None and moved > DEGREE_WITHIN:
        fate = "changed"
    elif unmoved(side, start):
        fate = "unmoved"
    else:
        fate = "holds"
    if structure and fate == "holds":
        off = structure_off(side, start)
        out["structure_off"] = _short(off)
        if off is not None and off > STRUCTURE_WITHIN:
            return dict(out, fate="changed", why=STRUCTURE_MOVED)
    return dict(out, fate=fate)


def chain_list(chains: dict, starts: list | None = None) -> list[dict]:
    listed = list((chains or {}).get("every_chain") or [])
    families = {str(s.get("name")): s.get("family") for s in starts or [] if isinstance(s, dict)}
    first = listed[1] if len(listed) > 1 else {}
    given_name = str((chains or {}).get("given_name") or first.get("name") or "given")
    out = [{"key": "empty", "name": "empty", "family": None},
           {"key": "given", "name": given_name, "family": first.get("start") or families.get(given_name)}]
    more = [str(c.get("key")) for c in listed[2:] if isinstance(c, dict)]
    if not more:
        seen: list = []
        for rung in (chains or {}).get("rungs") or []:
            for name in (rung.get("more_given") or {}):
                if name not in seen:
                    seen.append(name)
        more = seen
    starts_of = {str(c.get("key")): c.get("start") for c in listed[2:] if isinstance(c, dict)}
    for name in more:
        out.append({"key": name, "name": name, "family": starts_of.get(name) or families.get(name)})
    for chain in out:
        if chain["family"] is None and chain["name"] in NAMED:
            chain["family"] = NAMED[chain["name"]]
    return out


def _side(rung: dict, key: str) -> dict:
    if key in ("empty", "given"):
        return rung.get(key) or {}
    return (rung.get("more_given") or {}).get(key) or {}


def _read(side: dict) -> bool:
    return any(_num((side.get(key) or {}).get("mean")) is not None for key in COMPARED)


def _lowest(rung: dict, chains: list[dict], found: list[list[str]]) -> dict | None:
    energy = {c["name"]: (_num((_side(rung, c["key"]).get("energy_per_node") or {}).get("mean")),
                          _num((_side(rung, c["key"]).get("energy_per_node") or {}).get("se")) or 0.0)
              for c in chains}
    read = {name: v for name, v in energy.items() if v[0] is not None}
    if not read:
        return None
    lowest = min(read, key=lambda name: read[name][0])
    group = next((g for g in found if lowest in g), [lowest])
    others = [v for name, v in read.items() if name not in group]
    if not others:
        return {"group": group, "apart": None}
    nearest = min(others, key=lambda v: v[0])
    margin = max(0.02 * max(abs(read[lowest][0]), abs(nearest[0])), 2.0 * math.hypot(read[lowest][1], nearest[1]), 1e-9)
    return {"group": group, "apart": bool(nearest[0] - read[lowest][0] > margin)}


def rung_class(found: list[list[str]], fates: dict, lattices: set, generics: set) -> str:
    read = [name for group in found for name in group]
    if len(read) < 2:
        return "not_read"
    holding = {name for name in lattices if fates.get(name) == "holds"}
    group_of = {name: i for i, group in enumerate(found) for name in group}
    held_groups = {group_of[name] for name in holding if name in group_of}
    if len(found) == 1 and holding:
        return "one_space"
    if any(group_of.get(name) in held_groups for name in generics):
        return "grows"
    if any(group_of.get(name) in held_groups for name in lattices - holding):
        return "converts"
    if len(holding) == 1:
        return "selects"
    if len(holding) >= 2:
        return "holds"
    return "forgets" if len(found) == 1 else "remembers"


def rung_reading(rung: dict, chains: list[dict], references: dict | None = None, *, structure: bool = False) -> dict:
    n = int(rung["n"])
    read = [c for c in chains if _read(_side(rung, c["key"]))]
    names = [c["name"] for c in read]
    distances, worst, exact = {}, {}, {}
    for i, a in enumerate(read):
        for b in read[i + 1:]:
            pair = pair_distance(_side(rung, a["key"]), _side(rung, b["key"]), n, exact=True)
            key = pair_key(a["name"], b["name"])
            exact[key], worst[key] = pair["distance"], pair["worst"]
            distances[key] = None if pair["distance"] is None else _short(pair["distance"])
    found = groups(names, exact) if names else []
    fates, lattices = {}, set()
    for chain in read:
        if chain["family"] in LATTICES:
            lattices.add(chain["name"])
            fates[chain["name"]] = lattice_fate(_side(rung, chain["key"]), chain["family"], n, references,
                                                structure=structure)
    generics = {c["name"] for c in read} - lattices
    label = rung_class(found, {name: f.get("fate") for name, f in fates.items()}, lattices, generics)
    spread = [d for d in distances.values() if d is not None]
    return {"n": n, "chains": names, "distances": distances, "worst": worst, "groups": found,
            "fates": fates, "class": label, "spread": _short(max(spread)) if spread else None,
            "lowest_energy": _lowest(rung, read, found),
            "unreferenced": sorted(name for name, f in fates.items() if f.get("why") == NO_REFERENCE)}


def _trend(rungs: list[dict]) -> dict | None:
    if len(rungs) < 2:
        return None
    first, last = rungs[0], rungs[-1]
    both = [k for k, d in first["distances"].items() if d is not None and last["distances"].get(k) is not None]
    if not both:
        return None
    joined = sorted(k for k in both if first["distances"][k] > MET >= last["distances"][k])
    parted = sorted(k for k in both if first["distances"][k] <= MET < last["distances"][k])
    apart = [k for k in both if first["distances"][k] > MET and last["distances"][k] > MET]
    way = ("regrouping" if joined and parted else "merging" if joined else "splitting" if parted else "steady")
    return {"way": way, "joined": joined, "parted": parted, "apart": len(apart),
            "closing": sorted(k for k in apart if last["distances"][k] < first["distances"][k]),
            "groups": [len(r["groups"]) for r in rungs], "spread": [r["spread"] for r in rungs],
            "from_n": first["n"], "to_n": last["n"]}


def law_reading(chains: dict, starts: list | None = None, references: dict | None = None, *,
                structure: bool = False) -> dict:
    listed = chain_list(chains, starts)
    rungs = [rung_reading(r, listed, references, structure=structure)
             for r in sorted((chains or {}).get("rungs") or [], key=lambda r: int(r.get("n") or 0))
             if int(r.get("n") or 0) >= FROM_N]
    read = [r for r in rungs if r["class"] != "not_read"]
    at = read[-1] if read else None
    top = rungs[-1] if rungs else None
    label = at["class"] if at else "not_read"
    refs = table_references() if references is None else references
    unreferenced = list((at or {}).get("unreferenced") or [])
    return {"contract": CONTRACT, "from_n": FROM_N, "met_within": MET,
            "chains": [{"name": c["name"], "start": c["family"],
                        "lattice": (LATTICES.get(c["family"]) or (None, None))[1]} for c in listed],
            "rungs": rungs, "class": label, "class_name": CLASS_NAMES[label], "names": dict(CLASS_NAMES),
            "classes_by_n": {str(r["n"]): r["class"] for r in rungs}, "trend": _trend(read),
            "at_n": at["n"] if at else None, "top_n": top["n"] if top else None,
            "top_dense": bool(top is not None and at is not None and top["n"] != at["n"]),
            "references": bool(refs) and not unreferenced,
            **({"hold_structure": STRUCTURE_WITHIN} if structure else {}),
            **({"unreferenced": {"n": at["n"], "lattices": unreferenced}} if unreferenced else {})}


def compact(reading: dict) -> dict:
    at = next((r for r in reading.get("rungs") or [] if r["n"] == reading.get("at_n")), None)
    out = {"class": reading["class"], "at_n": reading.get("at_n"), "top_n": reading.get("top_n"),
           "top_dense": bool(reading.get("top_dense")),
           "by_n": {str(r["n"]): [r["class"], r["groups"]] for r in reading.get("rungs") or []}}
    if at:
        out["fates"] = {name: [f.get("fate"), f.get("kept")] for name, f in at["fates"].items()}
        out["lowest"] = at.get("lowest_energy")
    if reading.get("trend"):
        out["trend"] = reading["trend"]["way"]
    out["references"] = bool(reading.get("references"))
    if reading.get("unreferenced"):
        out["unreferenced"] = reading["unreferenced"]
    if reading.get("hold_structure"):
        out["hold_structure"] = reading["hold_structure"]
    return out


def hold_structure(campaign_spec: dict | None) -> bool:
    return bool(((campaign_spec or {}).get("sampling_contract") or {}).get("hold_structure"))
