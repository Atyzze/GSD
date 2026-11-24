from __future__ import annotations

import json
import statistics
from functools import lru_cache
from pathlib import Path

CONTRACT = "gsd-catalogue-1"
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


def kind(chains: dict[str, dict], given: dict | None = None, twin_points: int = 0) -> str:
    given = given or rule()
    if twin_points >= given["twin_settled_at_least"]:
        return "grown"
    grown = {name: c for name, c in chains.items()
             if c.get("mean_degree") is not None and c["mean_degree"] > given["empty_at_most"]}
    open_chains = {name: c for name, c in grown.items() if not c.get("full")}
    read = {name: c for name, c in open_chains.items() if c.get("d") is not None}
    together = agreeing(read, float(given["agree_within"]))
    if together:
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
