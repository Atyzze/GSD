from __future__ import annotations

from graph_scale_dynamics.domain.model import utc_now

CONTRACT = "gsd-push-1"
KEY = "pushed"
TOP = 100
GIB = 1024 ** 3


def entries(state: dict | None) -> list[dict]:
    return [dict(e) for e in (state or {}).get(KEY) or [] if e.get("law")]


def laws(state: dict | None) -> list[str]:
    return [str(e["law"]) for e in entries(state)]


def central(state: dict | None) -> list[str]:
    return [str(e["law"]) for e in (state or {}).get("central") or [] if e.get("law")]


def front(state: dict | None, line: list[str], held) -> list[str]:
    first = [law for law in laws(state) + central(state) if law in held]
    return first + [law for law in line if law not in first]


def _found(repo, state: dict, law: str, campaign: str | None) -> tuple[str, str]:
    from graph_scale_dynamics.operations import focus
    if campaign:
        row = repo.conn.execute("SELECT candidate_id FROM campaign_candidates WHERE campaign_id=? AND candidate_id LIKE ?",
                                (str(campaign), f"{law}%")).fetchall()
        if len(row) == 1:
            return str(row[0]["candidate_id"]), str(campaign)
        raise ValueError(f"campaign {campaign} holds {len(row)} laws starting {law!r}: give the whole id")
    found = focus._chosen(repo, state, law)
    return str(found["candidate_id"]), str(found["campaign"])


def toggle(repo, law: str, *, campaign: str | None = None, on: bool = True) -> dict:
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import focus
    state = focus._loaded(repo)
    if not str(law or "").strip():
        raise ValueError("name the law to push")
    law, campaign = _found(repo, state, str(law).strip(), campaign)
    held = state.setdefault(KEY, [])
    there = next((e for e in held if e.get("law") == law), None)
    if on and there is None:
        name = focus.label(repo, campaign, law)
        held.append({"law": law, "of": campaign, "label": name, "since": utc_now()})
        state.setdefault("contenders", {}).setdefault(law, {"of": campaign, "label": name, "joined_utc": utc_now(),
                                                            "pushed": True})
        control.set_workers(repo, state["campaigns"][focus.DEPTH], focus.DEPTH_WORKERS,
                            reason="a law is pushed to the N limit: the depth worker holds one worker")
        state["events"].append({"at": utc_now(), "pushed": name})
    elif not on and there is not None:
        held.remove(there)
        state["events"].append({"at": utc_now(), "unpushed": there.get("label")})
    focus.save(repo, state)
    return {"pushed": laws(state)}


def deepest(repo, campaigns: list[str]) -> list[dict]:
    if not campaigns:
        return []
    marks = ",".join("?" for _ in campaigns)
    out: dict[str, dict] = {}
    for row in repo.conn.execute(
            "SELECT candidate_id, campaign_id, MAX(n) AS deepest, COUNT(*) AS runs FROM jobs WHERE kind='simulate' "
            f"AND status='done' AND campaign_id IN ({marks}) GROUP BY candidate_id, campaign_id",
            tuple(str(c) for c in campaigns)).fetchall():
        law, n = str(row["candidate_id"]), int(row["deepest"])
        held = out.setdefault(law, {"law": law, "deepest": n, "campaign": str(row["campaign_id"]), "runs": 0})
        held["runs"] += int(row["runs"])
        if n > held["deepest"]:
            held.update(deepest=n, campaign=str(row["campaign_id"]))
    return sorted(out.values(), key=lambda r: (-r["deepest"], -r["runs"], r["law"]))


def sizes(repo, law: str) -> list[dict]:
    rows = repo.conn.execute(
        "SELECT j.n AS n, COUNT(*) AS runs, MAX(a.peak_rss_bytes) AS peak, AVG(a.wall_seconds) AS seconds, "
        "MAX(a.peak_edge_count) AS edges FROM jobs j JOIN attempts a ON a.job_id=j.job_id WHERE j.candidate_id=? "
        "AND j.kind='simulate' AND a.exit_code=0 GROUP BY j.n ORDER BY j.n", (str(law),)).fetchall()
    return [{"n": int(r["n"]), "runs": int(r["runs"]), "peak_bytes": int(r["peak"]) if r["peak"] else None,
             "seconds": round(float(r["seconds"]), 1) if r["seconds"] is not None else None,
             "edges": int(r["edges"]) if r["edges"] else None} for r in rows]


def forecast(found: list[dict], ladder: list[int], room: dict) -> dict:
    from graph_scale_dynamics.operations import depth_reach
    peaks = {int(r["n"]): int(r["peak_bytes"]) for r in found if r.get("peak_bytes")}
    reach = int(room.get("reach_bytes") or 0)
    ahead, limit = [], None
    top = max(peaks) if peaks else None
    for n in sorted(int(m) for m in ladder):
        if top is None or n <= top:
            continue
        priced = depth_reach.price(peaks, n)
        if priced is None:
            break
        fits = priced["needs_bytes"] <= reach
        ahead.append({"n": n, "needs_bytes": priced["needs_bytes"], "growth": priced["growth"], "fits": fits})
        if not fits:
            limit = {"n": n, "needs_bytes": priced["needs_bytes"], "short_bytes": priced["needs_bytes"] - reach}
            break
        peaks[n] = priced["needs_bytes"]
    return {"reach_bytes": reach, "total_bytes": room.get("total_bytes"), "share": room.get("share"),
            "ahead": ahead, "limit": limit, "reached": top,
            "words": ("no run has a memory reading yet" if top is None else
                      f"every size of its ladder fits within {reach / GIB:.1f} GiB" if limit is None else
                      f"N={limit['n']:,} would need {limit['needs_bytes'] / GIB:.1f} GiB, "
                      f"{limit['short_bytes'] / GIB:.1f} GiB more than the {reach / GIB:.1f} GiB the depth worker may "
                      "use: it stops below it")}


def reading(repo, state: dict | None, *, limit: int = TOP) -> dict:
    from graph_scale_dynamics.operations import depth_reach, dex, focus
    if not state:
        return {"contract": CONTRACT, "pushed": [], "now": None, "top": [], "law": None}
    study = str(state.get("study") or "")
    campaigns = dex.study_campaigns(repo, study)
    ranked = deepest(repo, campaigns)
    pushed = entries(state)
    now = state.get("depth_now") or None
    by = {r["law"]: r for r in ranked}
    for entry in pushed:
        entry["deepest"] = (by.get(entry["law"]) or {}).get("deepest")
    marked, running = set(laws(state)), (now or {}).get("law")
    top = []
    for row in ranked[:int(limit)]:
        top.append(dict(row, label=focus.label(repo, row["campaign"], row["law"]), pushed=row["law"] in marked,
                        running=row["law"] == running))
    law = running or (pushed[0]["law"] if pushed else None)
    detail = None
    if law:
        depth_campaign = str(state["campaigns"][focus.DEPTH])
        spec = (repo.campaign(depth_campaign) or {}).get("spec") or {}
        found = sizes(repo, law)
        of = (by.get(law) or {}).get("campaign") or next((e["of"] for e in pushed if e["law"] == law), depth_campaign)
        detail = {"law": law, "campaign": of, "label": focus.label(repo, of, law), "sizes": found,
                  "pushed": law in marked, "running": law == running,
                  "deepest": (by.get(law) or {}).get("deepest"),
                  "forecast": forecast(found, [int(n) for n in spec.get("ladder") or []],
                                       depth_reach.room_for(repo, depth_campaign))}
    return {"contract": CONTRACT, "pushed": pushed, "now": now, "top": top, "law": detail,
            "laws_read": len(ranked)}


__all__ = ["CONTRACT", "KEY", "TOP", "central", "deepest", "entries", "forecast", "front", "laws", "reading", "sizes", "toggle"]
