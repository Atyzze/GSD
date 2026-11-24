from __future__ import annotations

import json
import math
import statistics
from functools import lru_cache
from pathlib import Path

CONTRACT = "gsd-catalogue-2"
SOURCE = Path(__file__).resolve().parents[1] / "resources" / "catalogue" / "catalogue.json"
PROBES = ("d_s", "d_V", "d_B", "d_w")


@lru_cache(maxsize=1)
def catalogue() -> dict:
    return json.loads(SOURCE.read_text(encoding="utf-8"))


def rule() -> dict:
    return catalogue()["rule"]


def kinds() -> list[str]:
    return [entry["id"] for entry in catalogue()["categories"]]


def names() -> dict[str, str]:
    return {entry["id"]: entry["name"] for entry in catalogue()["categories"]}


def d_of(row: dict | None) -> float | None:
    read = [row.get(p) for p in PROBES if row and row.get(p) is not None]
    return statistics.median(read) if read else None


def alike(a: dict, b: dict, within: float) -> bool:
    if a.get("d") is None or b.get("d") is None or not a.get("mean_degree") or not b.get("mean_degree"):
        return False
    return (abs(a["d"] - b["d"]) <= within * abs(b["d"])
            and abs(a["mean_degree"] - b["mean_degree"]) <= within * abs(b["mean_degree"]))


def agreeing(chains: dict[str, dict], within: float) -> list[str]:
    return sorted(name for name, chain in chains.items()
                  if any(other != name and alike(chain, mate, within) for other, mate in chains.items()))


def still(name: str, chain: dict, given: dict | None = None) -> bool:
    given = given or rule()
    degree = given["lattice_degrees"].get(name)
    if not degree or chain.get("full") or chain.get("mean_degree") is None or chain.get("moved") is None:
        return False
    return (abs(chain["mean_degree"] / degree - 1) <= given["degree_within"]
            and chain["moved"] <= given["still_at_most"])


def frozen(name: str, chain: dict, given: dict | None = None) -> bool:
    given = given or rule()
    return still(name, chain, given) and chain["moved"] <= given["frozen_at_most"]


def random_reach(n: int, degree, given: dict | None = None) -> float | None:
    found = (given or rule())["small_world"]
    if not isinstance(degree, (int, float)) or degree < found["degree_at_least"] or int(n) < 2:
        return None
    return math.log(int(n) / 2.0) / math.log(float(degree)) + float(found["random_reach_offset"])


def small_world(now: dict | None, before: dict | None, n: int, given: dict | None = None) -> bool:
    given = given or rule()
    found = given["small_world"]
    if int(n) < found["from_n"] or not now or not before:
        return False
    for chain, size in ((before, int(n) // 4), (now, int(n))):
        reach, expected = chain.get("reach"), random_reach(size, chain.get("mean_degree"), given)
        if reach is None or expected is None or reach > found["reach_at_most"] * expected:
            return False
    a, b = before.get("d"), now.get("d")
    return a is not None and b is not None and a > 0 and (b - a) / a >= found["rise_at_least"]


def judged_at(chain: dict | None) -> bool:
    return bool(chain) and chain.get("d") is not None and chain.get("reach") is not None


def kind(chains: dict[str, dict], given: dict | None = None, twin_points: int = 0, *,
         before: dict[str, dict] | None = None, n: int | None = None) -> str:
    given = given or rule()
    if twin_points >= given["twin_settled_at_least"]:
        return "grown"
    grown = {name: c for name, c in chains.items()
             if c.get("mean_degree") is not None and c["mean_degree"] > given["empty_at_most"]}
    open_chains = {name: c for name, c in grown.items() if not c.get("full")}
    read = {name: c for name, c in open_chains.items() if c.get("d") is not None}
    together = agreeing(read, float(given["agree_within"]))
    if together:
        judged = [name for name in together if judged_at((before or {}).get(name))]
        if n is not None and judged and all(small_world(read[name], before[name], n, given) for name in judged):
            return "small_world"
        return "made" if statistics.median(read[name]["d"] for name in together) >= given["ring_below"] else "ring"
    if not any(c.get("mean_degree") is not None for c in chains.values()):
        return "unread"
    if not grown:
        return "empty"
    if not open_chains:
        return "full"
    degrees = given["lattice_degrees"]
    lattice = {name: c for name, c in open_chains.items() if name in degrees}
    at_own = {name: c for name, c in lattice.items()
              if abs(c["mean_degree"] / degrees[name] - 1) <= given["degree_within"]}
    quiet = [name for name, c in at_own.items() if still(name, c, given)]
    if quiet:
        return "frozen" if all(frozen(name, at_own[name], given) for name in quiet) else "still"
    if at_own:
        return "rewired"
    if lattice:
        return "moved"
    if all(c.get("giant") is not None and c["giant"] < given["broken_below"] for c in open_chains.values()):
        return "broken"
    return "apart" if read else "unread"


SETTLE_FROM = 4096


def value_settles(chains: dict, twins: list[str], relative: dict) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for name, rows in chains.items():
        if name not in twins:
            continue
        sizes = sorted(n for n in rows if n >= SETTLE_FROM)
        for probe in PROBES:
            run = 0
            for a, b in zip(sizes, sizes[1:], strict=False):
                va, vb = rows[a].get(probe), rows[b].get(probe)
                margin = (relative.get(probe) or {}).get(str(b))
                ok = va is not None and vb is not None and vb != 0 and margin is not None and abs(vb - va) <= margin * abs(vb)
                run = run + 1 if ok else 0
                if run:
                    out.setdefault(b, {})[f"{name}:{probe}"] = run + 1
    return out


def kinds_of(views: dict[int, dict[str, dict]], values: dict[str, dict[int, dict]], relative: dict,
             given: dict | None = None) -> dict[int, str]:
    given = given or rule()
    settles = value_settles(values, given["twin_starts"], relative)
    return {n: kind(views[n], given, max((settles.get(n) or {}).values(), default=0), before=views.get(n // 4), n=n)
            for n in sorted(views)}
