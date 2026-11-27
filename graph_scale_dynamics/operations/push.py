from __future__ import annotations

from graph_scale_dynamics.domain.model import utc_now
from graph_scale_dynamics.scheduling import worker_count

CONTRACT = "gsd-push-1"
KEY = "pushed"
ORDER_FLAG = worker_count.DEPTH_ORDER_FLAG
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


OWN_LINE = "the depth worker's own line"
LET_GO = "let_go"
ADOPTED = "push_list_adopted"


def add(state: dict, law: str, of: str, label: str | None, *, by: str | None = None, first: bool = False) -> bool:
    held = state.setdefault(KEY, [])
    if any(e.get("law") == law for e in held):
        return False
    entry = {"law": law, "of": of, "label": label, "since": utc_now(), **({"by": by} if by else {})}
    held.insert(0, entry) if first else held.append(entry)
    if law in (state.get(LET_GO) or []):
        state[LET_GO].remove(law)
    state.setdefault("contenders", {}).setdefault(law, {"of": of, "label": label, "joined_utc": utc_now(),
                                                        "pushed": True})
    return True


def adopt_central(state: dict) -> int:
    taken = 0
    for entry in state.pop("central", None) or []:
        if entry.get("law"):
            taken += add(state, str(entry["law"]), str(entry.get("of")), entry.get("label"),
                         by=f"zone {entry.get('zone') or ''}".strip())
    return taken


def adopt_now(state: dict) -> bool:
    now = state.get("depth_now") or {}
    law = now.get("law")
    if not law or law in laws(state) or law in (state.get(LET_GO) or []):
        return False
    entry = (state.get("contenders") or {}).get(law) or {}
    return add(state, str(law), str(entry.get("of") or now.get("campaign")), now.get("label"), by=OWN_LINE, first=True)


def listed(state: dict | None, done=()) -> list[str]:
    held = (state or {}).get("contenders") or {}
    return [law for law in laws(state) + central(state) if law not in done and law in held]


def ahead(state: dict, done) -> str | None:
    return next(iter(listed(state, done)), None)


def ended(state: dict, law: str, end: dict) -> dict | None:
    held = state.get(KEY) or []
    entry = next((e for e in held if e.get("law") == law), None)
    if entry is None:
        return None
    held.remove(entry)
    gone = dict(entry, **{k: end.get(k) for k in ("action", "rule", "at_n", "ended_utc")})
    state.setdefault("pushed_done", []).append(gone)
    state["events"].append({"at": utc_now(), "pushed_ended": entry.get("label"), "rule": end.get("rule"),
                            "at_n": end.get("at_n")})
    return gone


def order_of(state: dict | None) -> dict:
    from graph_scale_dynamics.operations import focus
    state = state or {}
    now = (state.get("depth_now") or {}).get("law")
    on = listed(state, state.get("depth_done") or {})
    first = on[0] if on else now
    later = [law for law in [now] + list(state.get("depth_waiting") or []) if law and law != first and law in on]
    campaign = (state.get("campaigns") or {}).get(focus.DEPTH)
    return {"campaign": None if campaign is None else str(campaign), "host": bool(on),
            "laws": ([first] if first else []) + list(dict.fromkeys(later))}


def holds_host(repo) -> dict | None:
    found = order_here(repo)
    return found if found is not None and found.get("host") else None


def keep_order(repo, state: dict | None) -> dict:
    import json
    found = order_of(state)
    text = json.dumps(found, sort_keys=True) if found["campaign"] and found["laws"] else ""
    if (repo.get_flag(ORDER_FLAG, "") or "") != text:
        repo.set_flag(ORDER_FLAG, text)
    return found


def order_here(repo) -> dict | None:
    import json
    getter = getattr(repo, "get_flag", None)
    if not callable(getter):
        return None
    try:
        found = json.loads(getter(ORDER_FLAG, "") or "null")
    except (TypeError, ValueError):
        return None
    return found if isinstance(found, dict) and found.get("campaign") and found.get("laws") else None


def move(repo, law: str, to: int) -> dict:
    from graph_scale_dynamics.operations import focus
    state = focus._loaded(repo)
    held = state.get(KEY) or []
    entry = next((e for e in held if str(e.get("law") or "").startswith(str(law or "").strip() or "-")), None)
    if entry is None:
        raise ValueError(f"{law!r} is not in the push list")
    held.remove(entry)
    held.insert(max(0, min(int(to), len(held))), entry)
    state["events"].append({"at": utc_now(), "push_moved": entry.get("label"), "to": held.index(entry) + 1})
    focus.save(repo, state)
    keep_order(repo, state)
    return {"pushed": laws(state)}


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
        add(state, law, campaign, name)
        if (state.get("depth_done") or {}).get(law, {}).get("left"):
            state["depth_done"].pop(law)
        control.set_workers(repo, state["campaigns"][focus.DEPTH], focus.DEPTH_WORKERS,
                            reason="a law is pushed to the N limit: the depth slot holds one worker")
        state["events"].append({"at": utc_now(), "pushed": name})
    elif not on and there is not None:
        held.remove(there)
        if law not in state.setdefault(LET_GO, []):
            state[LET_GO].append(law)
        state["events"].append({"at": utc_now(), "unpushed": there.get("label")})
    focus.save(repo, state)
    keep_order(repo, state)
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


TIME_LEAST, TIME_MOST = 1.0, 3.0


def run_seconds(found: list[dict], n: int) -> dict | None:
    import math
    times = sorted((int(r["n"]), float(r["seconds"])) for r in found if r.get("seconds") and int(r["n"]) < int(n))
    if not times:
        return None
    top, at_top = times[-1]
    growth = TIME_LEAST
    if len(times) >= 2 and times[-2][1] > 0:
        below, at_below = times[-2]
        growth = min(TIME_MOST, max(TIME_LEAST, math.log(at_top / at_below) / math.log(top / below)))
    return {"seconds": round(at_top * (int(n) / top) ** growth, 1), "growth": round(growth, 3)}


def forecast(found: list[dict], ladder: list[int], room: dict, seeds: int = 3, now: float | None = None) -> dict:
    import math
    import time
    from graph_scale_dynamics.operations import depth_reach
    peaks = {int(r["n"]): int(r["peak_bytes"]) for r in found if r.get("peak_bytes")}
    timed = [dict(r) for r in found]
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
        row = {"n": n, "needs_bytes": priced["needs_bytes"], "growth": priced["growth"], "fits": fits}
        took = run_seconds(timed, n)
        if fits:
            row["at_once"] = max(1, min(int(seeds), reach // max(1, priced["needs_bytes"])))
            if took is not None:
                row.update(seconds=took["seconds"], time_growth=took["growth"],
                           hours=round(math.ceil(int(seeds) / row["at_once"]) * took["seconds"] / 3600, 2))
                timed.append({"n": n, "seconds": took["seconds"]})
        ahead.append(row)
        if not fits:
            limit = {"n": n, "needs_bytes": priced["needs_bytes"], "short_bytes": priced["needs_bytes"] - reach}
            break
        peaks[n] = priced["needs_bytes"]
    fitting = [row for row in ahead if row["fits"]]
    single = next((row["n"] for row in fitting if row["at_once"] == 1), None)
    hours = sum(row.get("hours") or 0 for row in fitting) if fitting and all("hours" in r for r in fitting) else None
    clock = time.time() if now is None else float(now)
    final = {"n": fitting[-1]["n"], "one_at_a_time_from": single, "hours": None if hours is None else round(hours, 1),
             "ends_utc": None if hours is None else time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                   time.gmtime(clock + hours * 3600))} if fitting else None
    words = ("no run has a memory reading yet" if top is None else
             f"every size of its ladder fits within {reach / GIB:.1f} GiB" if limit is None else
             f"N={limit['n']:,} would need {limit['needs_bytes'] / GIB:.1f} GiB, "
             f"{limit['short_bytes'] / GIB:.1f} GiB more than the {reach / GIB:.1f} GiB the depth worker may "
             "use: it stops below it")
    if final is not None:
        words += (f"; its last size N={final['n']:,}" + (f", one seed at a time from N={single:,}" if single else "")
                  + (f", about {final['hours']:g} h of runs from here, ending near {final['ends_utc'][11:16]} UTC"
                     if final["hours"] is not None else ""))
    return {"reach_bytes": reach, "total_bytes": room.get("total_bytes"), "share": room.get("share"),
            "host": bool(room.get("host")), "seeds": int(seeds), "ahead": ahead, "limit": limit, "reached": top,
            "final": final, "words": words}


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
                                       depth_reach.room_for(repo, depth_campaign),
                                       seeds=int(spec.get("default_seeds") or 3))}
    return {"contract": CONTRACT, "pushed": pushed, "now": now, "top": top, "law": detail,
            "laws_read": len(ranked), "slot": slot(repo, state), "done": list(state.get("pushed_done") or [])[-20:]}


def _memory_of(repo, owner: str | None, job_id: str) -> dict:
    import json
    row = repo.conn.execute("SELECT detail_json FROM service_heartbeats WHERE service=?", (str(owner or ""),)).fetchone()
    try:
        detail = json.loads(row["detail_json"] or "{}") if row is not None else {}
    except (TypeError, ValueError):
        detail = {}
    if str(detail.get("job") or "") != job_id:
        return {}
    return {"memory_now": detail.get("pss_now"), "memory_peak": detail.get("pss") or detail.get("rss"),
            "elapsed": detail.get("elapsed")}


def slot(repo, state: dict) -> dict:
    from graph_scale_dynamics.operations import focus
    campaign = str((state.get("campaigns") or {}).get(focus.DEPTH) or "")
    names = {str(e["law"]): e.get("label") for e in entries(state)} | {
        law: e.get("label") for law, e in (state.get("contenders") or {}).items()}
    running = [{"law": str(r["candidate_id"]), "label": names.get(str(r["candidate_id"])), "n": int(r["n"]),
                "seed": int(r["seed"]), "since": r["updated_utc"], "owner": r["lease_owner"],
                **_memory_of(repo, r["lease_owner"], str(r["job_id"]))}
               for r in repo.conn.execute(
                   "SELECT job_id, candidate_id, n, seed, updated_utc, lease_owner FROM jobs WHERE campaign_id=? AND "
                   "kind='simulate' AND status='leased' ORDER BY updated_utc", (campaign,)).fetchall()]
    queued = {str(r["candidate_id"]): int(r["c"]) for r in repo.conn.execute(
        "SELECT candidate_id, COUNT(*) AS c FROM jobs WHERE campaign_id=? AND kind='simulate' AND status='queued' "
        "GROUP BY candidate_id", (campaign,)).fetchall()}
    order = order_of(state)
    return {"campaign": campaign or None, "running": running,
            "order": [{"law": law, "label": names.get(law), "queued": queued.get(law, 0)} for law in order["laws"]],
            "waiting": [{"law": law, "label": names.get(law)} for law in state.get("depth_waiting") or []]}


__all__ = ["ADOPTED", "CONTRACT", "KEY", "LET_GO", "ORDER_FLAG", "OWN_LINE", "TOP", "add", "adopt_central", "adopt_now",
           "ahead", "central", "deepest", "ended", "entries", "forecast", "front", "keep_order", "laws", "listed",
           "holds_host", "move", "order_here", "order_of", "reading", "run_seconds", "sizes", "slot", "toggle"]
