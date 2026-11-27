from __future__ import annotations

from graph_scale_dynamics.domain.model import utc_now

CONTRACT = "gsd-push-1"
KEY = "pushed"
TOP = 100
GIB = 1024 ** 3


CEILING = 1_048_576


def ceiling_of(state: dict | None, law: str) -> int:
    entry = next((e for e in entries(state) if str(e["law"]) == str(law)), None) or {}
    return max(CEILING, int(entry.get("to") or CEILING))


def entries(state: dict | None) -> list[dict]:
    return [dict(e) for e in (state or {}).get(KEY) or [] if e.get("law")]


def home_of(state: dict | None, law: str) -> dict | None:
    for entry in entries(state) + [dict(e) for e in (state or {}).get("pushed_done") or [] if e.get("law")]:
        if str(entry["law"]) == str(law) and entry.get("of"):
            return {"campaign": str(entry["of"]), "label": entry.get("label") or str(law)[:12]}
    held = ((state or {}).get("contenders") or {}).get(str(law)) or {}
    return {"campaign": str(held["of"]), "label": held.get("label") or str(law)[:12]} if held.get("of") else None


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


def move(repo, law: str, to: int) -> dict:
    from graph_scale_dynamics.operations import focus, modes
    state = focus._loaded(repo)
    held = state.get(KEY) or []
    entry = next((e for e in held if str(e.get("law") or "").startswith(str(law or "").strip() or "-")), None)
    if entry is None:
        raise ValueError(f"{law!r} is not in the push list")
    held.remove(entry)
    held.insert(max(0, min(int(to), len(held))), entry)
    state["events"].append({"at": utc_now(), "push_moved": entry.get("label"), "to": held.index(entry) + 1})
    modes.keep(repo, state)
    focus.save(repo, state)
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
    from graph_scale_dynamics.operations import focus, modes
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
        state["events"].append({"at": utc_now(), "pushed": name})
    elif not on and there is not None:
        held.remove(there)
        if law not in state.setdefault(LET_GO, []):
            state[LET_GO].append(law)
        state["events"].append({"at": utc_now(), "unpushed": there.get("label")})
    modes.keep(repo, state)
    focus.save(repo, state)
    return {"pushed": laws(state)}


def past(repo, law: str, *, campaign: str | None = None) -> dict:
    from graph_scale_dynamics.operations import focus, modes, push_ladder
    state = focus._loaded(repo)
    if not str(law or "").strip():
        raise ValueError("name the law to push past its ceiling")
    law, campaign = _found(repo, state, str(law).strip(), campaign)
    held = state.setdefault(KEY, [])
    there = next((e for e in held if e.get("law") == law), None)
    if there is None:
        name = focus.label(repo, campaign, law)
        add(state, law, campaign, name)
        there = next(e for e in held if e.get("law") == law)
    camp = (state.get("campaigns") or {}).get(push_ladder.PUSH)
    ladder = sorted(int(n) for n in ((repo.campaign(str(camp)) or {}).get("spec") or {}).get("ladder") or []) if camp else []
    now = max(CEILING, int(there.get("to") or CEILING))
    there["to"] = next((n for n in ladder if n > now), now * 4)
    state["events"].append({"at": utc_now(), "pushed_past": there.get("label"), "to": there["to"]})
    modes.keep(repo, state)
    focus.save(repo, state)
    return {"pushed": laws(state), "to": there["to"]}


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


def reading(repo, state: dict | None, *, limit: int = TOP) -> dict:
    from graph_scale_dynamics.operations import dex, focus, modes
    if not state:
        return {"contract": CONTRACT, "pushed": [], "now": None, "top": [], "law": None}
    study = str(state.get("study") or "")
    campaigns = dex.study_campaigns(repo, study)
    ranked = deepest(repo, campaigns)
    pushed = entries(state)
    now = state.get("depth_now") or None
    held = home_of(state, now["law"]) if now and now.get("law") else None
    if held:
        now = dict(now, campaign=held["campaign"], label=held["label"], pushed_in=now.get("campaign"))
    by = {r["law"]: r for r in ranked}
    for entry in pushed:
        entry["deepest"] = (by.get(entry["law"]) or {}).get("deepest")
        entry["ceiling"] = ceiling_of(state, entry["law"])
    marked, running = set(laws(state)), (now or {}).get("law")
    top = []
    for row in ranked[:int(limit)]:
        home = home_of(state, row["law"]) if row["law"] in marked or row["law"] == running else None
        top.append(dict(row, campaign=home["campaign"] if home else row["campaign"],
                        label=home["label"] if home else focus.label(repo, row["campaign"], row["law"]),
                        pushed=row["law"] in marked, running=row["law"] == running))
    law = running or (pushed[0]["law"] if pushed else None)
    detail = None
    if law:
        from graph_scale_dynamics.operations import push_ladder
        found = sizes(repo, law)
        home = home_of(state, law)
        of = (home or {}).get("campaign") or (by.get(law) or {}).get("campaign")
        camp = (state.get("campaigns") or {}).get(push_ladder.PUSH)
        label = (home or {}).get("label") or (focus.label(repo, of, law) if of else law[:12])
        detail = {"law": law, "campaign": of, "label": label, "sizes": found,
                  "pushed": law in marked, "running": law == running, "deepest": (by.get(law) or {}).get("deepest"),
                  "ceiling": ceiling_of(state, law),
                  "ladder": push_ladder.forecast(repo, str(camp), law, ceiling=ceiling_of(state, law)) if camp else None}
    return {"contract": CONTRACT, "pushed": pushed, "now": now, "top": top, "law": detail,
            "laws_read": len(ranked), "slot": slot(repo, state), "done": list(state.get("pushed_done") or [])[-20:],
            "mode": modes.here(repo)}


def for_the_bundle(repo, state: dict | None) -> dict | None:
    if not state:
        return None
    try:
        found = reading(repo, state)
    except Exception as exc:  # noqa: BLE001
        rollback = getattr(getattr(repo, "conn", None), "rollback_if_open", None)
        if callable(rollback):
            rollback()
        return {"contract": CONTRACT, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    return {key: value for key, value in found.items() if key != "top"}


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
    from graph_scale_dynamics.operations import push_ladder
    campaign = str((state.get("campaigns") or {}).get(push_ladder.PUSH) or "")
    names = {law: e.get("label") for law, e in (state.get("contenders") or {}).items()} | {
        str(e["law"]): e.get("label") for e in entries(state)}
    homes = {law: (home_of(state, law) or {}).get("campaign") for law in set(names) | set(listed(state))}
    running = [{"law": str(r["candidate_id"]), "label": names.get(str(r["candidate_id"])),
                "of": homes.get(str(r["candidate_id"])), "n": int(r["n"]),
                "seed": int(r["seed"]), "since": r["updated_utc"], "owner": r["lease_owner"],
                **_memory_of(repo, r["lease_owner"], str(r["job_id"]))}
               for r in repo.conn.execute(
                   "SELECT job_id, candidate_id, n, seed, updated_utc, lease_owner FROM jobs WHERE campaign_id=? AND "
                   "kind='simulate' AND status='leased' ORDER BY n, seed", (campaign,)).fetchall()]
    queued = {str(r["candidate_id"]): int(r["c"]) for r in repo.conn.execute(
        "SELECT candidate_id, COUNT(*) AS c FROM jobs WHERE campaign_id=? AND kind='simulate' AND status='queued' "
        "GROUP BY candidate_id", (campaign,)).fetchall()}
    begun = {str(r["candidate_id"]) for r in repo.conn.execute(
        "SELECT DISTINCT candidate_id FROM jobs WHERE campaign_id=? AND kind='simulate'", (campaign,)).fetchall()}
    on = listed(state)
    return {"campaign": campaign or None, "running": running,
            "order": [{"law": law, "label": names.get(law), "queued": queued.get(law, 0)} for law in on[:1]],
            "waiting": [{"law": law, "label": names.get(law), "of": homes.get(law)} for law in on[1:] if law in begun]}


__all__ = ["ADOPTED", "CEILING", "CONTRACT", "KEY", "LET_GO", "OWN_LINE", "TOP", "add", "adopt_central", "adopt_now", "ahead",
           "ceiling_of", "central", "deepest", "ended", "entries", "for_the_bundle", "front", "laws", "listed", "move", "past", "reading",
           "run_seconds", "sizes", "slot", "toggle", "home_of"]
