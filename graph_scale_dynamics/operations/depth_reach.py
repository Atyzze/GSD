from __future__ import annotations

import json
import math

from graph_scale_dynamics.decisions import memory_ceiling as MC

CONTRACT = "gsd-depth-reach-1"
GROWTH_LEAST, GROWTH_MOST = 1.0, 2.0
SAFETY = 1.1


def peaks(repo, campaign_id: str, law: str) -> dict[int, int]:
    found: dict[int, int] = {}
    for row in repo.conn.execute(
            "SELECT j.n n, MAX(a.peak_rss_bytes) peak FROM jobs j JOIN attempts a ON a.job_id=j.job_id "
            "WHERE j.campaign_id=? AND j.candidate_id=? AND a.peak_rss_bytes IS NOT NULL AND a.peak_rss_bytes>0 "
            "GROUP BY j.n", (str(campaign_id), str(law))).fetchall():
        found[int(row["n"])] = max(found.get(int(row["n"]), 0), int(row["peak"]))
    return found


def price(found: dict[int, int], next_n: int) -> dict | None:
    sizes = sorted(int(n) for n, peak in found.items() if int(peak) > 0 and int(n) < int(next_n))
    if not sizes:
        return None
    top, growth, below = sizes[-1], GROWTH_LEAST, None
    if len(sizes) >= 2:
        below = sizes[-2]
        ratio = float(found[top]) / float(found[below])
        growth = math.log(ratio) / math.log(float(top) / float(below)) if ratio > 0 else GROWTH_LEAST
        growth = min(GROWTH_MOST, max(GROWTH_LEAST, growth))
    needs = int(math.ceil(float(found[top]) * (float(next_n) / float(top)) ** growth * SAFETY))
    return {"reached": top, "next_n": int(next_n), "needs_bytes": needs, "growth": round(growth, 3),
            "from": f"N={below:,} and N={top:,}" if below is not None else f"N={top:,}"}


def next_size(ladder, top: int) -> int | None:
    return next((int(n) for n in sorted(int(m) for m in ladder or []) if int(n) > int(top)), None)


def judge(found: dict[int, int], ladder, room: dict) -> dict | None:
    top = max((int(n) for n, peak in found.items() if int(peak) > 0), default=None)
    following = next_size(ladder, top) if top is not None else None
    if following is None:
        return None
    priced = price(found, following)
    if priced is None or priced["needs_bytes"] <= int(room.get("reach_bytes") or 0):
        return None
    return dict(priced, reach_bytes=int(room.get("reach_bytes") or 0), free_bytes=int(room.get("floor_bytes") or 0))


def room_now(repo) -> dict:
    from graph_scale_dynamics.scheduling import memory_hold
    return memory_hold.reach(repo.conn)


def keep(repo, campaign_id: str, laws, ladder, room: dict | None = None, now: str | None = None) -> dict[str, dict]:
    from graph_scale_dynamics.domain.model import utc_now
    value = MC.flag_value(repo.get_flag(MC.FLAG, ""))
    made = {str(c): dict(found) for c, found in (value.get("laws") or {}).items()}
    mine = made.setdefault(str(campaign_id), {})
    room = room_now(repo) if room is None else room
    added = {}
    for law in laws:
        if str(law) in mine:
            continue
        entry = judge(peaks(repo, campaign_id, law), ladder, room)
        if entry is not None:
            entry["at"] = now or utc_now()
            mine[str(law)] = entry
            added[str(law)] = entry
    if added:
        repo.set_flag(MC.FLAG, json.dumps(MC.flag(made), sort_keys=True, separators=(",", ":")))
    return added


def ceilings(repo, campaign_id: str) -> dict[str, dict]:
    return MC.entries_of(repo.get_flag(MC.FLAG, ""), str(campaign_id))


__all__ = ["CONTRACT", "SAFETY", "ceilings", "judge", "keep", "next_size", "peaks", "price", "room_now"]
