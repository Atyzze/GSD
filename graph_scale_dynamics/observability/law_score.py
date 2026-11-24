from __future__ import annotations

import functools
import json
import math
import statistics
from pathlib import Path

from graph_scale_dynamics.observability import starts_reading as F
from graph_scale_dynamics.observability import space_score as S

CONTRACT = "gsd-law-score-8"
LADDER = (1024, 4096, 16384, 65536, 262144, 1048576, 4194304)
RELIED_FROM = 4096
STEP_AT_LEAST = 3.0
PROBES = ("d_s", "d_V", "d_B", "d_w")
EINSTEIN = "einstein"
ITEMS = PROBES + (EINSTEIN,)
PAIR_POINTS = len(PROBES) + 1
PER_ITEM = 3
POINTS = len(ITEMS) * PER_ITEM
CHANGED, KEPT, FROZEN = 0.6, 0.3, 0.0
FROZEN_SCORE = 1
WEIGHTS = (("empty", 1.0), ("random", 1.0), ("lattice", CHANGED), ("kept", KEPT), ("frozen", FROZEN))
PIECE_AT_LEAST = 4096
CONNECTED_AT_LEAST = 0.5
ITEM_WORDS = {1: "reads at two sizes", 2: "settles", 3: "settles again"}
WHO = {"empty": "the chain from empty", "random": "the random start", "lattice": "a lattice start, changed",
       "kept": "a lattice start, kept", "frozen": "a lattice start, frozen"}
KEEPS = ("holds",)
FROZEN_FATE = "unmoved"
MARGINS_FILE = Path(__file__).resolve().parents[1] / "resources" / "calibration" / "score_margins.json"
MARGINS_CONTRACT = "gsd-score-margins-1"
BAND = "all four agree by the Einstein relation"


def _num(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return None


@functools.lru_cache(maxsize=1)
def margins() -> dict:
    document = json.loads(MARGINS_FILE.read_text(encoding="utf-8"))
    if document.get("contract") != MARGINS_CONTRACT:
        raise ValueError(f"{MARGINS_FILE} is not {MARGINS_CONTRACT}")
    return document


def depth(n: int) -> float:
    if int(n) < LADDER[0]:
        return 0.0
    steps = math.log(int(n) / LADDER[0], 4.0) + 1.0
    return min(1.0, steps / len(LADDER))


def level(n: int) -> int:
    levels = [size for size in LADDER if size > RELIED_FROM]
    return min(levels, key=lambda size: (abs(math.log(int(n) / size)), size))


def margin(probe: str, n: int, table: dict | None = None) -> float | None:
    by_level = ((table or margins()).get("relative") or {}).get(probe) or {}
    value = by_level.get(str(level(n)))
    return None if value is None else float(value)


def tau(table: dict | None = None) -> float:
    return float((table or margins())["tau"])


def pairs(sizes) -> list[tuple[int, int]]:
    read = sorted({int(n) for n in sizes if int(n) >= RELIED_FROM})
    chosen: list[int] = []
    for n in read:
        if not chosen or n >= STEP_AT_LEAST * chosen[-1]:
            chosen.append(n)
    return list(zip(chosen, chosen[1:], strict=False))


def reading(block) -> float | None:
    return S._probe(block)


def counted(side) -> dict:
    if isinstance(side, dict) and isinstance(side.get("counted"), dict):
        return side["counted"]
    return side if isinstance(side, dict) else {}


def reach_rule(table: dict | None = None) -> dict:
    return dict((table or margins())["reach"])


def _spread(block) -> float:
    se = _num((block or {}).get("se")) if isinstance(block, dict) else None
    return se if se is not None and se > 0 else 0.0


def _d_at(side: dict | None) -> float | None:
    read = [value for value in (reading((side or {}).get(probe)) for probe in PROBES) if value is not None]
    return statistics.median(read) if read else None


def scale_at(before: dict, now: dict, a: int, b: int, table: dict | None = None) -> dict:
    rule = reach_rule(table)
    r_a, r_b = reading((before or {}).get("reach")), reading((now or {}).get("reach"))
    d = _d_at(now)
    if r_a is None or r_b is None or r_a <= 0 or r_b <= 0 or d is None or d <= 0 or int(b) <= int(a):
        return {"holds": False, "reach": [r_a, r_b], "d": None if d is None else round(d, 4), "growth_d": None,
                "why": "no reach or no d at both sizes"}
    expected = math.log(int(b) / int(a)) / d
    grown = math.log(r_b / r_a)
    allowed = (float(rule["q"]) * expected + float(rule["half_step"]) * (1.0 / r_a + 1.0 / r_b)
               + float(rule["z"]) * math.hypot(_spread(before.get("reach")) / r_a, _spread(now.get("reach")) / r_b))
    off = abs(grown - expected)
    return {"holds": off <= allowed, "reach": [round(r_a, 4), round(r_b, 4)], "d": round(d, 4),
            "growth_d": round(math.log(int(b) / int(a)) / grown, 4) if grown > 0 else None,
            "off": round(off, 4), "allowed": round(allowed, 4)}


def scale_kept(sides: dict, a: int, b: int, table: dict | None = None, *, next_breaks: bool = True) -> dict:
    found = scale_at(sides[a], sides[b], a, b, table)
    after = next((c for x, c in pairs(sides) if x == int(b)), None) if next_breaks else None
    if after is None or not found["holds"]:
        return found
    later = scale_at(sides[b], sides[after], b, after, table)
    if later["holds"] or "why" in later:
        return found
    return dict(found, holds=False, broken_after={"n": int(after), "growth_d": later.get("growth_d"),
                                                  "d": later.get("d")})


def step(a: float, b: float) -> float:
    middle = 0.5 * (abs(a) + abs(b))
    return abs(b - a) / middle if middle > 0 else math.inf


def residual(values: dict) -> float | None:
    d_s, d_V, d_B, d_w = (values.get(p) for p in PROBES)
    if None in (d_s, d_V, d_B, d_w) or d_w <= 0 or d_s <= 0:
        return None
    return max(abs(d_s - 2.0 * d_V / d_w), abs(d_s - 2.0 * d_B / d_w)) / d_s


def points_at(before: dict, now: dict, n: int, table: dict | None = None) -> dict:
    steps, settled, values = {}, [], {}
    for probe in PROBES:
        a, b = reading((before or {}).get(probe)), reading((now or {}).get(probe))
        values[probe] = b
        if a is None or b is None:
            continue
        found, allowed = step(a, b), margin(probe, n, table)
        steps[probe] = {"step": round(found, 4), "margin": allowed, "from": round(a, 4), "to": round(b, 4)}
        if allowed is not None and found <= allowed:
            settled.append(probe)
    off = residual(values) if len(settled) == len(PROBES) else None
    agree = off is not None and off <= tau(table)
    return {"settled": settled, "steps": steps, "residual": None if off is None else round(off, 4),
            "tau": tau(table), "einstein": agree, "points": len(settled) + (1 if agree else 0)}


def piece_holds(side: dict | None, n: int) -> bool:
    if int(n) < RELIED_FROM:
        return False
    giant = reading((side or {}).get("giant_fraction"))
    return giant is None or (giant * int(n) >= PIECE_AT_LEAST * (1.0 - 1e-9)
                             and giant >= CONNECTED_AT_LEAST * (1.0 - 1e-9))


def agrees(side: dict | None, table: dict | None = None) -> bool | None:
    off = residual({probe: reading((side or {}).get(probe)) for probe in PROBES})
    return None if off is None else off <= tau(table)


def items_along(sides: dict, table: dict | None = None, *, beyond: dict | None = None,
                next_breaks: bool = True) -> dict:
    best = {item: {"points": 0, "to_n": None} for item in ITEMS}
    before: dict = {}
    whole = dict(beyond or sides)
    for a, b in pairs(sides):
        found = points_at(sides[a], sides[b], b, table)
        scaled = scale_kept(whole, a, b, table, next_breaks=next_breaks)["holds"]
        now: dict = {}
        for probe in PROBES:
            if probe not in found["steps"]:
                now[probe] = False
                continue
            settled = scaled and probe in found["settled"]
            got = 3 if settled and before.get(probe) else 2 if settled else 1
            now[probe] = settled
            if got > best[probe]["points"]:
                best[probe] = {"points": got, "to_n": b, "from_n": a}
        at_a, at_b = agrees(sides[a], table), agrees(sides[b], table)
        if at_a is not None and at_b is not None:
            held = bool(at_a and at_b and scaled)
            got = 3 if held and before.get(EINSTEIN) else 2 if held else 1
            now[EINSTEIN] = held
            if got > best[EINSTEIN]["points"]:
                best[EINSTEIN] = {"points": got, "to_n": b, "from_n": a}
        else:
            now[EINSTEIN] = False
        before = now
    return best


def who(chain: dict) -> str:
    if chain.get("key") == "empty":
        return "empty"
    family = str(chain.get("family") or "")
    if family in F.LATTICES:
        return "lattice"
    if not family or "random" in family or "erdos" in family.lower():
        return "random"
    return "lattice"


def given_family(campaign_spec: dict | None, law: str, law_spec=None) -> str | None:
    sampling = (campaign_spec or {}).get("sampling_contract") or {}
    declared = (sampling.get("given_start_by_law") or {}).get(str(law)) or sampling.get("given_start")
    if isinstance(declared, dict) and declared.get("family"):
        return str(declared["family"])
    if not (sampling.get("given_starts") or sampling.get("given_start_rule")):
        return None
    try:
        from graph_scale_dynamics.scheduling.job_creation import resolve_given_start
        start = resolve_given_start(campaign_spec or {}, 4096, str(law), law_spec() if callable(law_spec) else law_spec)
    except Exception:  # noqa: BLE001
        return None
    return str(start["family"]) if isinstance(start, dict) and start.get("family") else None


def _merged(rung: dict) -> dict:
    return {**rung, **dict(rung.get("more_given") or {})}


def _why(items: dict, total: int, start: str, fate: str | None, scale: dict | None = None,
         pair: tuple | None = None) -> str:
    if not total:
        return ("no item reads at two sizes from 4,096 on a piece of 4,096 nodes or more and half the graph, "
                "on seeds whose chain stopped changing")
    said = f"{total} of {POINTS}: " + ", ".join(
        f"{item.replace('einstein', 'the Einstein relation')} {ITEM_WORDS[entry['points']]}"
        for item, entry in items.items() if entry["points"])
    if start == "kept":
        said += f"; the lattice start {fate or 'not read'}, so it counts {KEPT}"
    elif start == "frozen":
        said += f"; frozen: no edge changed, so it scores {FROZEN_SCORE}, the lowest score there is"
    elif start == "lattice":
        said += f"; the lattice start {fate}, so it counts {CHANGED}"
    if scale is not None and not scale.get("holds") and pair is not None:
        grown, after = scale.get("growth_d"), scale.get("broken_after")
        if after:
            later = (f"grows as d {after['growth_d']:g}, not the d {after['d']:g} it reads"
                     if after.get("growth_d") is not None and after.get("d") is not None else "does not grow")
            said += f"; from {pair[1]:,} to {after['n']:,} its reach {later}, so what settled to {pair[1]:,} was on its way"
        else:
            said += (f"; from {pair[0]:,} to {pair[1]:,} its reach grows as d {grown:g}, not the d {scale['d']:g} it reads"
                     if grown is not None and scale.get("d") is not None
                     else f"; from {pair[0]:,} to {pair[1]:,} its reach does not grow")
    return said


def _kind(start: str, fate: str | None) -> str:
    if start != "lattice":
        return start
    if fate == FROZEN_FATE:
        return "frozen"
    return "kept" if fate is None or fate in KEEPS else "lattice"


def score(chains: dict, five: dict | None = None, *, starts: list | None = None,
          references: dict | None = None, first_given: str | None = None, structure: bool = False,
          table: dict | None = None, next_breaks: bool = True) -> dict:
    listed = F.chain_list(chains, starts)
    for chain in listed:
        if chain["key"] == "given" and not chain.get("family") and first_given:
            chain["family"] = first_given
    if any(who(chain) == "lattice" for chain in listed):
        given = next((c for c in listed if c["key"] == "given"), None)
        unread = (given is not None and given.get("family") in F.LATTICES
                  and not any(c.get("name") == given["name"] and c.get("start") for c in (five or {}).get("chains") or []))
        if five is None or unread:
            refs = F.table_references() if references is None else references
            named = list(starts or []) + ([{"name": given["name"], "family": given["family"]}] if unread else [])
            five = F.law_reading(chains, named or starts, refs, structure=structure)
    rungs = [_merged(r) for r in sorted((chains or {}).get("rungs") or [], key=lambda r: int(r.get("n") or 0))]
    by_n = {int(r["n"]): r for r in rungs}
    fates_at = {int(r["n"]): (r.get("fates") or {}) for r in (five or {}).get("rungs") or []}
    sizes: dict[int, dict] = {}
    parts = {kind: {"weight": weight, "to_n": None, "chain": None, "points": 0.0, "of": 0}
             for kind, weight in WEIGHTS}
    for chain in listed:
        sides = {n: counted(rung[chain["key"]]) for n, rung in by_n.items()
                 if rung.get(chain["key"]) and piece_holds(counted(rung[chain["key"]]), n)}
        start = who(chain)
        steps = pairs(sides)
        for index, (a, b) in enumerate(steps):
            upto = {n: sides[n] for n in sides if n <= b}
            items = items_along(upto, table, beyond=sides, next_breaks=next_breaks)
            total = sum(entry["points"] for entry in items.values())
            earned = max((int(entry["to_n"]) for entry in items.values() if entry["points"]), default=b)
            found = points_at(sides[a], sides[b], b, table)
            scale = scale_kept(sides, a, b, table, next_breaks=next_breaks)
            fate = (fates_at.get(b, {}).get(chain["name"]) or {}).get("fate") if start == "lattice" else None
            kind = _kind(start, fate)
            weight = dict(WEIGHTS)[kind]
            value = ((float(FROZEN_SCORE) if total else 0.0) if kind == "frozen"
                     else round(100.0 * weight * depth(earned) * total / POINTS, 2))
            entry = {"key": chain["key"], "start": start, "kind": kind, "from_n": a,
                     "settled": found["settled"] if scale["holds"] else [], "scale": scale,
                     "steps": found["steps"], "residual": found["residual"], "tau": found["tau"],
                     "einstein": bool(items[EINSTEIN]["points"] >= 2),
                     "items": {item: e["points"] for item, e in items.items()}, "points": total, "value": value,
                     "how": _why(items, total, kind, fate, scale, (a, b))}
            if fate is not None:
                entry["fate"] = fate
            sizes.setdefault(b, {"n": b, "chains": {}})["chains"][chain["name"]] = entry
            part = parts[kind]
            if (value, earned) > (part["points"], part["to_n"] or 0):
                parts[kind] = {"weight": weight, "to_n": earned, "chain": chain["name"],
                               "depth": round(depth(earned), 4), "points": value, "of": total, "items": entry["items"]}
    best = max(parts, key=lambda kind: (parts[kind]["points"], parts[kind]["to_n"] or 0, dict(WEIGHTS)[kind]))
    top = parts[best]
    value = int(round(top["points"]))
    top_n = max(by_n, default=None)
    at_top = by_n.get(int(top["to_n"])) or {} if value > 0 else {}
    side = next((counted(at_top[c["key"]]) for c in listed if c["name"] == top["chain"] and at_top.get(c["key"])),
                None)
    return {"contract": CONTRACT, "score": value, "of": 100, "d": dimension_read(side),
            "mean_degree": degree_read(side),
            "by": best if value > 0 else None, "chain": top["chain"] if value > 0 else None,
            "to_n": top["to_n"] if value > 0 else None, "points": top["of"] if value > 0 else 0,
            "points_of": POINTS, "items": top.get("items") if value > 0 else None,
            "einstein": bool(value > 0 and (top.get("items") or {}).get(EINSTEIN, 0) >= 2),
            "parts": parts, "sizes": [sizes[n] for n in sorted(sizes)], "top_n": top_n,
            "relied_from": RELIED_FROM, "piece_at_least": PIECE_AT_LEAST, "connected_at_least": CONNECTED_AT_LEAST,
            "ladder": list(LADDER),
            "weights": dict(WEIGHTS), "who": dict(WHO), "band": BAND, "tau": tau(table)}


RING_BELOW = 1.5


def dimension_read(side: dict | None) -> float | None:
    read = [value for value in (reading((side or {}).get(probe)) for probe in PROBES) if value is not None]
    return round(statistics.median(read), 2) if read else None


def degree_read(side: dict | None) -> float | None:
    value = reading((side or {}).get("mean_degree"))
    return None if value is None else round(float(value), 2)


def is_ring(d) -> bool:
    return isinstance(d, (int, float)) and not isinstance(d, bool) and float(d) < RING_BELOW


def compact(found: dict) -> dict:
    parts = {kind: {"value": part.get("points"), "of": part.get("of"), "items": part.get("items"),
                    "to_n": part.get("to_n"), "chain": part.get("chain")}
             for kind, part in (found.get("parts") or {}).items() if part.get("to_n")}
    return {"score": found["score"], "by": found["by"], "chain": found["chain"], "to_n": found["to_n"],
            "d": found.get("d"), "mean_degree": found.get("mean_degree"), "top_n": found.get("top_n"),
            "points": found.get("points", 0), "points_of": POINTS,
            "items": found.get("items"), "einstein": bool(found.get("einstein")), "parts": parts}


TWINS = ("empty", "random")


def settled_items(items: dict | None) -> tuple[int, bool]:
    items = items or {}
    return sum(1 for probe in PROBES if int(items.get(probe) or 0) >= 2), int(items.get(EINSTEIN) or 0) >= 2


def best_items(found: dict | None, *, lattices: bool = True) -> dict | None:
    parts = (found or {}).get("parts") or {}
    kinds = [kind for kind in parts if lattices or kind in TWINS]
    if not kinds:
        return None
    best = max(kinds, key=lambda kind: (float(parts[kind].get("value") or 0.0), int(parts[kind].get("to_n") or 0)))
    return parts[best].get("items") if float(parts[best].get("value") or 0.0) > 0 else None


def zero(top_n: int | None = None) -> dict:
    return {"score": 0, "by": None, "chain": None, "to_n": None, "d": None, "mean_degree": None, "top_n": top_n, "points": 0, "points_of": POINTS,
            "items": None, "einstein": False, "parts": {}}
