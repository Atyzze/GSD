from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from graph_scale_dynamics.operations import law_code as LC

CONTRACT = "gsd-zone-now-1"
PUSHED, ZONE, ZONE_SEEDS, DEPTH, DEX, BLIND, OTHER = "the N-push", "zone", "zone seeds", "depth", "Dex laws", "blind", "other"
ROLES = (PUSHED, ZONE, ZONE_SEEDS, DEPTH, DEX, BLIND, OTHER)
WINDOW_HOURS = 6
RECENT_SECONDS = 3600.0
RUNNING = "running"
QUEUED = "queued"
BEING_READ = "being read"
DECIDER = "waiting for the decider"
NEXT_DUE = "its next size due"
HELD = "held"
DECIDED = "decided"
FAILED = "failed"
NOT_STARTED = "not started"
READ = "read"
STAGES = (RUNNING, QUEUED, BEING_READ, DECIDER, NEXT_DUE, HELD, DECIDED, FAILED, NOT_STARTED)
JUDGED = ("a neighbour is alike when it reads the law's own kind at N={read_n:,} (ring, frozen, moved, made and "
          "the rest, read from its probes); a neighbour the decider stops by a rule before N={read_n:,} reads "
          "another kind. The zone stands when at least {share:.0%} of ring {radius} is alike; it is then read "
          "outward ring by ring, or halved along a line toward each neighbour of another kind")


def when(text) -> datetime | None:
    if not text:
        return None
    try:
        found = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=timezone.utc)


def seconds_since(text, now: datetime) -> float | None:
    found = when(text)
    return None if found is None else round(max(0.0, (now - found).total_seconds()), 1)


def _stamp(at: datetime) -> str:
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _medians(repo, since: str, campaigns: list[str] | None) -> dict[str, float]:
    where = ""
    args: tuple = (since,)
    if campaigns is not None:
        if not campaigns:
            return {}
        where = f" AND j.campaign_id IN ({','.join('?' for _ in campaigns)})"
        args = (since, *campaigns)
    rows = repo.conn.execute(
        "SELECT j.n AS n, percentile_cont(0.5) WITHIN GROUP (ORDER BY a.wall_seconds) AS m, COUNT(*) AS c "
        "FROM attempts a JOIN jobs j ON j.job_id=a.job_id WHERE a.finished_utc>=? AND a.wall_seconds IS NOT NULL "
        f"AND a.exit_code=0 AND j.kind='simulate'{where} GROUP BY j.n", args).fetchall()
    return {str(int(row["n"])): round(float(row["m"]), 1) for row in rows if row["m"] is not None}


def typical(repo, zone_campaigns, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = _stamp(now - timedelta(hours=WINDOW_HOURS))
    zone = sorted({str(c) for c in zone_campaigns or [] if c})
    return {"zone": _medians(repo, since, zone), "fleet": _medians(repo, since, None), "at": _stamp(now),
            "hours": WINDOW_HOURS}


def roles_of(repo, state: dict) -> dict[str, str]:
    from graph_scale_dynamics.operations import focus as F
    study = str(state.get("study"))
    out = {}
    for campaign in repo.all_campaigns():
        design = (campaign.get("spec") or {}).get("study_design") or {}
        if str(design.get("study")) != study:
            continue
        kind = design.get("kind")
        if kind == F.KIND:
            part = (design.get("focus") or {}).get("part")
            role = {F.NEIGHBOURS: ZONE, F.SEEDS: ZONE_SEEDS, F.DEPTH: DEPTH, "E": ZONE, "P": PUSHED}.get(part, OTHER)
        else:
            role = {"seed": DEX, "blind": BLIND}.get(kind, OTHER)
        out[str(campaign["campaign_id"])] = role
    return out


def _running(repo) -> list[dict]:
    return [dict(row) for row in repo.conn.execute(
        "SELECT j.campaign_id, j.candidate_id, j.n, j.seed, j.updated_utc, "
        "(SELECT MAX(a.started_utc) FROM attempts a WHERE a.job_id=j.job_id AND a.finished_utc IS NULL) "
        "AS started_utc FROM jobs j WHERE j.status='leased' AND j.kind='simulate'").fetchall()]


def part_of(state: dict, role: str, campaign: str, law: str) -> str:
    from graph_scale_dynamics.operations import focus as F
    current = state.get("current") or {}
    campaigns = {str(c) for c in (state.get("campaigns") or {}).values()}
    if role == ZONE and campaign == str((state.get("campaigns") or {}).get("E") or ""):
        return "a step of the zone's search, read to N=4,096"
    if role == ZONE:
        point = (current.get("points") or {}).get(law) if campaign in campaigns else None
        if not point:
            return "an earlier law's zone"
        if point.get("how") == "neighbour":
            return f"ring {float(point['radius']):g}"
        if point.get("how") == F.KNOCKOUT:
            return f"{point.get('term')} off"
        return "on a line to a boundary"
    if role == ZONE_SEEDS:
        return "the law in focus, on more seeds" if law == current.get("law") else "an earlier law, on more seeds"
    if role == PUSHED:
        now = (state.get("depth_now") or {}).get("law")
        return "the first pushed law, its ladder again from 64" if law == now else "a pushed law, its runs kept"
    if role == DEPTH:
        now = (state.get("depth_now") or {}).get("law")
        return "the depth worker's law" if law == now else "an earlier depth law"
    if role == DEX:
        return "a Dex law, read again here"
    if role == BLIND:
        return "drawn blind"
    return "outside the study's parts"


def _labels(repo, pairs) -> dict[tuple[str, str], str]:
    known: dict = {}
    graphs: dict[str, dict[str, int]] = {}
    out = {}
    for campaign, law in pairs:
        if campaign not in graphs:
            graphs[campaign] = LC.graphs(repo, campaign)
        out[(campaign, law)] = LC.code(LC.study_of(repo, campaign, known), campaign, graphs[campaign].get(law), law)
    return out


def _tables(repo, campaign: str, laws: list[str]) -> tuple[dict, dict, dict]:
    if not laws:
        return {}, {}, {}
    marks = ",".join("?" for _ in laws)
    jobs: dict[str, dict[int, dict]] = {}
    for row in repo.conn.execute(
            "SELECT candidate_id, n, status, COUNT(*) AS c, MIN(created_utc) AS first, MAX(updated_utc) AS last "
            f"FROM jobs WHERE campaign_id=? AND kind='simulate' AND candidate_id IN ({marks}) "
            "GROUP BY candidate_id, n, status", (campaign, *laws)).fetchall():
        cell = jobs.setdefault(str(row["candidate_id"]), {}).setdefault(int(row["n"]), {})
        cell[str(row["status"])] = {"count": int(row["c"]), "first": row["first"], "last": row["last"]}
    reading: dict[str, dict[int, dict]] = {}
    for row in repo.conn.execute(
            "SELECT candidate_id, n, COUNT(*) AS c, MIN(created_utc) AS first FROM analysis_queue "
            f"WHERE campaign_id=? AND status IN ('queued','leased') AND candidate_id IN ({marks}) "
            "GROUP BY candidate_id, n", (campaign, *laws)).fetchall():
        reading.setdefault(str(row["candidate_id"]), {})[int(row["n"])] = {"count": int(row["c"]),
                                                                           "first": row["first"]}
    decided = {str(row["candidate_id"]): dict(row) for row in repo.conn.execute(
        "SELECT candidate_id, action, rule, at_n, next_n, created_utc FROM engine_decisions_latest "
        f"WHERE campaign_id=? AND candidate_id IN ({marks})", (campaign, *laws)).fetchall()}
    return jobs, reading, decided


def _count(cell: dict, status: str) -> int:
    return int((cell.get(status) or {}).get("count") or 0)


def planned_of(spec: dict | None, role: str) -> tuple[list[int], int]:
    from graph_scale_dynamics.operations import dex_check
    spec = spec or {}
    if role == DEX:
        sizes, _level, seeds = dex_check.level_of(spec)
        return sizes, seeds
    policy = ((spec.get("engine") or {}).get("policy") or {})
    return [int(n) for n in spec.get("ladder") or []], int(spec.get("default_seeds") or policy.get("seeds") or 3)


def law_rows(repo, rows: list[dict], medians_of) -> list[dict]:
    by: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        by.setdefault((row["campaign"], row["law"]), []).append(row)
    out = []
    for campaign in sorted({c for c, _l in by}):
        laws = sorted(l for c, l in by if c == campaign)
        jobs, _reading, _decided = _tables(repo, campaign, laws)
        spec = (repo.campaign(campaign) or {}).get("spec")
        for law in laws:
            running = by[(campaign, law)]
            role = running[0]["role"]
            sizes, seeds = planned_of(spec, role)
            sizes = sorted(set(sizes) | {int(r["n"]) for r in running})
            cells = jobs.get(law) or {}
            planned = len(sizes) * seeds
            done = sum(min(seeds, _count(cells.get(n) or {}, "done")) for n in sizes)
            medians = medians_of(role)
            under_way = sum(min(0.95, float(r["seconds"]) / float(medians[str(r["n"])]))
                            for r in running if r.get("seconds") is not None and medians.get(str(r["n"])))
            now = sorted({int(r["n"]) for r in running})
            starts = [r.get("started_utc") for r in running if r.get("started_utc")]
            out.append({"role": role, "part": running[0]["part"], "campaign": campaign, "law": law,
                        "label": running[0].get("label"), "home": running[0].get("home") or campaign, "sizes": sizes, "seeds": seeds, "planned": planned,
                        "done": done, "running": len(running),
                        "queued": sum(_count(cells.get(n) or {}, "queued") for n in sizes),
                        "now": [{"n": n, "seeds": sorted(int(r["seed"]) for r in running if int(r["n"]) == n)}
                                for n in now],
                        "seconds": max((r["seconds"] or 0.0) for r in running), "started_utc": min(starts) if starts else None,
                        "progress": round(min(1.0, (done + under_way) / planned), 4) if planned else None})
    out.sort(key=lambda r: (ROLES.index(r["role"]), -(r["progress"] or 0.0), str(r["label"] or r["law"])))
    return out


def where(jobs: dict[int, dict], reading: dict[int, dict], decision: dict | None, started: dict[int, str],
          seeds: int) -> dict:
    leased = sorted(n for n, cell in jobs.items() if _count(cell, "leased"))
    if leased:
        n = leased[-1]
        cell = jobs[n]
        return {"stage": RUNNING, "n": n, "since": started.get(n) or (cell.get("leased") or {}).get("last"),
                "done": _count(cell, "done"), "running": _count(cell, "leased"), "queued": _count(cell, "queued"),
                "seeds": seeds}
    queued = sorted(n for n, cell in jobs.items() if _count(cell, "queued"))
    if queued:
        n = queued[-1]
        cell = jobs[n]
        return {"stage": QUEUED, "n": n, "since": (cell.get("queued") or {}).get("first"),
                "done": _count(cell, "done"), "queued": _count(cell, "queued"), "seeds": seeds}
    if reading:
        n = max(reading)
        return {"stage": BEING_READ, "n": n, "since": reading[n]["first"], "analyses": reading[n]["count"]}
    finished = sorted(n for n, cell in jobs.items() if _count(cell, "done"))
    if decision is not None and (not finished or decision.get("at_n") is not None
                                 and int(decision["at_n"]) >= finished[-1]):
        action = str(decision.get("action") or "")
        stage = {"hold": HELD, "run_next": NEXT_DUE}.get(action, DECIDED)
        at = decision.get("next_n") if stage == NEXT_DUE else decision.get("at_n")
        return {"stage": stage, "n": None if at is None else int(at), "since": decision.get("created_utc"),
                "rule": decision.get("rule"), "action": action}
    failed = sorted(n for n, cell in jobs.items() if _count(cell, "failed"))
    if finished:
        n = finished[-1]
        return {"stage": DECIDER, "n": n, "since": (jobs[n].get("done") or {}).get("last")}
    if failed:
        n = failed[-1]
        return {"stage": FAILED, "n": n, "since": (jobs[n].get("failed") or {}).get("last")}
    return {"stage": NOT_STARTED, "n": None, "since": None}


def reached(jobs: dict[int, dict], seeds: int) -> int | None:
    whole = [n for n, cell in jobs.items() if _count(cell, "done") >= seeds and not _count(cell, "leased")
             and not _count(cell, "queued")]
    return max(whole) if whole else None


def _point_words(point: dict) -> dict:
    from graph_scale_dynamics.operations import focus as F
    if point.get("how") == "neighbour":
        return {"part": "neighbour", "radius": float(point["radius"])}
    if point.get("how") == F.KNOCKOUT:
        return {"part": "term off", "term": point.get("term")}
    return {"part": "line", "partner": point.get("partner"), "at": point.get("at")}


def _expected(own: dict, n: int) -> str | None:
    from graph_scale_dynamics.operations import focus as F
    return F.expected({int(k): v for k, v in (own or {}).items()}, int(n))


def _left(jobs: dict[int, dict], ladder: list[int], read_n: int, seeds: int, medians: dict, elapsed: dict) -> tuple:
    seconds, unknown = 0.0, False
    top = reached(jobs, seeds)
    for n in ladder:
        if n > read_n or (top is not None and n <= top):
            continue
        cell = jobs.get(n) or {}
        typical_n = medians.get(str(n))
        if typical_n is None:
            unknown = True
            continue
        whole = max(0, seeds - _count(cell, "done") - _count(cell, "leased"))
        seconds += whole * typical_n
        seconds += sum(max(0.0, typical_n - e) for e in elapsed.get(n, []))
    return seconds, unknown


def _zone_points(repo, state: dict, current: dict, running: list[dict], medians: dict, now: datetime) -> dict:
    from graph_scale_dynamics.operations import focus as F
    campaign = str(state["campaigns"][F.NEIGHBOURS])
    spec = (repo.campaign(campaign) or {}).get("spec") or {}
    seeds = int(spec.get("default_seeds") or state.get("seeds") or 3)
    read_n = int(state["plan"]["neighbourhood"]["read_n"])
    ladder = sorted(int(n) for n in spec.get("ladder") or [] if int(n) <= read_n)
    laws = list((current.get("points") or {}))
    jobs, reading, decided = _tables(repo, campaign, laws)
    labels = _labels(repo, [(campaign, law) for law in laws])
    started: dict[str, dict[int, str]] = {}
    elapsed: dict[str, dict[int, list]] = {}
    for row in running:
        if str(row["campaign_id"]) != campaign:
            continue
        law, n = str(row["candidate_id"]), int(row["n"])
        at = row.get("started_utc") or row.get("updated_utc")
        known = started.setdefault(law, {})
        if at and (n not in known or str(at) < str(known[n])):
            known[n] = at
        elapsed.setdefault(law, {}).setdefault(n, []).append(seconds_since(at, now) or 0.0)
    kind = current.get("kind")
    own = current.get("law_kinds") or (current.get("depth") or {}).get("own") or {}
    verdicts, read_at, so_far = current.get("read") or {}, current.get("read_at") or {}, current.get("so_far") or {}
    points, left, unknown = [], 0.0, False
    for law in laws:
        point = current["points"][law]
        seen = verdicts.get(law)
        entry = {"law": law, "label": labels.get((campaign, law)), **_point_words(point),
                 "reached": reached(jobs.get(law) or {}, seeds), "verdict": seen,
                 "alike": None if seen is None or kind is None else seen == kind, "read_at": read_at.get(law)}
        found = so_far.get(law) or {}
        if found:
            last = max(found, key=lambda k: int(k))
            like = _expected(own, int(last))
            entry["so_far"] = {"n": int(last), "kind": found[last],
                               "law_reads": like, "alike": None if like is None else found[last] == like}
        if seen is None:
            entry["where"] = where(jobs.get(law) or {}, reading.get(law) or {}, decided.get(law),
                                   started.get(law) or {}, seeds)
            entry["where"]["seconds"] = seconds_since(entry["where"].get("since"), now)
            if entry["where"]["stage"] != DECIDED:
                more, missing = _left(jobs.get(law) or {}, ladder, read_n, seeds, medians, elapsed.get(law) or {})
                left += more
                unknown = unknown or missing
        else:
            entry["where"] = {"stage": READ, "n": read_n, "since": read_at.get(law),
                              "seconds": seconds_since(read_at.get(law), now)}
        points.append(entry)
    probes = sum(cell["count"] for law in laws if law not in verdicts for cell in (reading.get(law) or {}).values())
    return {"campaign": campaign, "seeds": seeds, "ladder": ladder, "points": points,
            "left_seconds": round(left, 1), "left_unknown": unknown, "probes_waiting": int(probes)}


def rings_of(points: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in points:
        key = f"{p['radius']:g}" if p.get("part") == "neighbour" else p.get("part")
        row = out.setdefault(key, {"laws": 0, **{s: 0 for s in (READ, *STAGES)}, "alike_so_far": 0,
                                   "other_so_far": 0})
        row["laws"] += 1
        row[p["where"]["stage"]] = row.get(p["where"]["stage"], 0) + 1
        if p.get("verdict") is None and p.get("so_far"):
            row["alike_so_far" if p["so_far"].get("alike") else "other_so_far"] += 1
    return out


def pace(current: dict, points: list[dict], now: datetime) -> dict:
    stamps = sorted(s for s in (seconds_since(p.get("read_at"), now) for p in points) if s is not None)
    read = sum(1 for p in points if p.get("verdict") is not None)
    return {"on_it_seconds": seconds_since(current.get("began_utc"), now), "began_utc": current.get("began_utc"),
            "read": read, "of": len(points), "read_last_hour": sum(1 for s in stamps if s <= RECENT_SECONDS),
            "last_read_seconds": stamps[0] if stamps else None}


def order(repo) -> dict:
    from graph_scale_dynamics.scheduling import work_groups
    return dict(work_groups.now_on([dict(row) for row in repo.worker_allocation()]), names=list(work_groups.TIER_NAMES))


def reading(repo, state: dict | None, *, now: datetime | None = None) -> dict | None:
    if not state or not state.get("campaigns"):
        return None
    now = now or datetime.now(timezone.utc)
    roles = roles_of(repo, state)
    running = _running(repo)
    found = state.get("typical") or {}
    fleet = dict(found.get("fleet") or {})
    zone_medians = dict(fleet, **(found.get("zone") or {}))
    labels = _labels(repo, sorted({(str(r["campaign_id"]), str(r["candidate_id"])) for r in running}))
    from graph_scale_dynamics.operations import push
    rows = []
    for row in running:
        campaign, law = str(row["campaign_id"]), str(row["candidate_id"])
        role = roles.get(campaign, OTHER)
        at = row.get("started_utc") or row.get("updated_utc")
        medians = zone_medians if role in (PUSHED, ZONE, ZONE_SEEDS, DEPTH) else fleet
        home = push.home_of(state, law) if role == PUSHED else None
        rows.append({"role": role, "part": part_of(state, role, campaign, law), "campaign": campaign, "law": law,
                     "label": (home or {}).get("label") or labels.get((campaign, law)),
                     "home": (home or {}).get("campaign") or campaign, "n": int(row["n"]), "seed": int(row["seed"]),
                     "started_utc": at, "seconds": seconds_since(at, now), "typical": medians.get(str(int(row["n"])))})
    rows.sort(key=lambda r: (ROLES.index(r["role"]), -(r["seconds"] or 0.0)))
    laws = law_rows(repo, rows, lambda role: zone_medians if role in (PUSHED, ZONE, ZONE_SEEDS, DEPTH) else fleet)
    workers = Counter(r["role"] for r in rows)
    found_analyses = repo.conn.execute(
        "SELECT SUM(CASE WHEN status='leased' THEN 1 ELSE 0 END) AS running, "
        "SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) AS queued FROM analysis_queue "
        "WHERE status IN ('queued','leased')").fetchone()
    analyses = dict(found_analyses) if found_analyses is not None else {}
    out = {"contract": CONTRACT, "at": _stamp(now), "running": rows, "laws": laws,
           "workers": {role: int(workers.get(role, 0)) for role in ROLES},
           "analyses": {"running": int(analyses.get("running") or 0), "queued": int(analyses.get("queued") or 0)},
           "order": order(repo), "typical": found, "zone": None, "zone_first": state.get("zone_first")}
    current = state.get("current")
    if current and current.get("points"):
        zone = _zone_points(repo, state, current, running, zone_medians, now)
        busy = workers.get(ZONE, 0)
        p = state["plan"]["neighbourhood"]
        zone.update(rings=rings_of(zone["points"]), pace=pace(current, zone["points"], now),
                    eta_seconds=round(zone["left_seconds"] / busy, 1) if busy and zone["left_seconds"] else None,
                    judged=JUDGED.format(read_n=int(p["read_n"]), share=float(p["confirm_share"]),
                                         radius=f"{float(p['confirm_radius']):g}"),
                    needs_at=current.get("needs_at") or {}, law=current.get("law"), label=current.get("label"),
                    kind=current.get("kind"))
        out["zone"] = zone
    return out


def safe(repo, state: dict | None) -> dict | None:
    try:
        return reading(repo, state)
    except Exception as exc:  # noqa: BLE001
        rollback = getattr(getattr(repo, "conn", None), "rollback_if_open", None)
        if callable(rollback):
            rollback()
        return {"contract": CONTRACT, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}


__all__ = ["BEING_READ", "BLIND", "CONTRACT", "DECIDED", "DECIDER", "DEPTH", "DEX", "FAILED", "HELD", "JUDGED",
           "NEXT_DUE", "NOT_STARTED", "OTHER", "QUEUED", "READ", "PUSHED", "ROLES", "RUNNING", "STAGES", "ZONE",
           "ZONE_SEEDS", "law_rows", "order", "pace", "part_of", "planned_of", "reached", "reading", "rings_of",
           "roles_of", "safe", "seconds_since", "typical", "when", "where"]
