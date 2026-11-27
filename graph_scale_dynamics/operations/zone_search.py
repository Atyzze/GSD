from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from graph_scale_dynamics.domain.model import utc_now
from graph_scale_dynamics.observability import likeness as L

CONTRACT = "gsd-zone-search-1"
ZONE_CONTRACT = "gsd-zone-1"
EDGES = "E"
JUDGE_N = 4096
FIRST_STEP = 0.1
STEPS_OUT = 5
HALVINGS = 3
FARTHEST_DOWN = 0.95
MEMBERS, STEPPING, CONFIRMING, DONE = "members", "edges", "confirming", "done"
ALIKE, OTHER = "alike", "other"


def reading(repo, campaign_id: str, law: str, n: int) -> dict | None:
    from graph_scale_dynamics.operations import focus
    found = focus.verdict(repo, str(campaign_id), str(law), int(n))
    if found is None:
        return None
    if str(found).startswith("stopped"):
        return {"kind": str(found), "curves": {}}
    return {"kind": str(found), "curves": L.curves(L.rows_of(repo, campaign_id, law), int(n))}


def judged(centre: dict | None, other: dict | None) -> tuple[str | None, str]:
    found = L.alike(centre, other)
    return (None if found["alike"] is None else ALIKE if found["alike"] else OTHER), found["why"]


def edges_campaign(repo, state: dict, *, tree=None) -> str:
    from graph_scale_dynamics import PROJECT_ROOT
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import focus
    if state["campaigns"].get(EDGES):
        return str(state["campaigns"][EDGES])
    tree = Path(tree) if tree is not None else Path(PROJECT_ROOT)
    study = str(state["study"])
    anchor = next(iter(focus.own_campaigns(repo, study)))
    design, _index = focus._design_for(repo, study, anchor, tree)
    spec = focus.campaign_specs(repo, study, anchor, state["plan"], tree)[focus.NEIGHBOURS]
    spec = focus._laddered(deepcopy(spec), design, [], int(design["ladder"]["seeds"]))
    spec["study_design"] = dict(spec["study_design"], focus=dict(spec["study_design"]["focus"], part=EDGES))
    spec["name"] = f"study {study}: its zones' edges, each step read to N={JUDGE_N:,} (group N)"
    spec["description"] = spec["name"]
    made = control.create_campaign(repo, spec, search_seed=focus._seed(study, EDGES),
                                   reason=f"study {study}'s focus: the zone's search, its steps judged at {JUDGE_N:,}")
    state["campaigns"][EDGES] = str(made["campaign_id"])
    return str(made["campaign_id"])


def _key(at: float) -> str:
    return f"{float(at):.6g}"


def stepped(spec: dict, path: tuple, sign: int, at: float) -> dict | None:
    from graph_scale_dynamics.research import perturb as P
    was = P.value_of(spec, path)
    now = float(f"{was * (1.0 + sign * float(at)):.12g}")
    if path[-1] in P.SHARES and not 0.0 < now < 1.0:
        return None
    child = deepcopy(spec)
    P._set(child, path, now)
    return child


def begin(repo, state: dict, current: dict, spec: dict) -> dict:
    from graph_scale_dynamics.operations import focus
    from graph_scale_dynamics.research import neighbourhood as N
    from graph_scale_dynamics.research import perturb as P
    zone = (state.get("zone_chosen") or {}).get("chosen") or {}
    near = set(zone.get("near_laws") or [])
    members = {}
    for law in zone.get("members") or []:
        if law == current["law"]:
            continue
        other = focus._spec_of(repo, current["of"], law)
        found = N.distance(spec, other) if other else None
        members[law] = {"campaign": current["of"], "distance": None if found is None else round(float(found), 6),
                        "near": law in near, "verdict": None, "why": None}
    lines = {}
    for path in P.parameters(spec):
        for sign in (1, -1):
            lines[f"{P.label(path)} {'+' if sign > 0 else '-'}"] = {
                "param": P.label(path), "path": list(path), "sign": sign, "from": P.value_of(spec, path),
                "steps": {}, "lo": 0.0, "hi": None, "halvings": 0, "done": False, "why": None}
    search = {"contract": CONTRACT, "judge_n": JUDGE_N, "confirm_n": int(state["plan"]["neighbourhood"]["read_n"]),
              "radius": float(state["plan"]["neighbourhood"]["confirm_radius"]),
              "share": float(state["plan"]["neighbourhood"]["confirm_share"]), "stage": MEMBERS,
              "members": members, "lines": lines, "off": {}, "edges": {}, "central": None, "centre": None,
              "began_utc": utc_now()}
    current["search"] = search
    state["events"].append({"at": utc_now(), "law": current.get("label"), "search": "begun",
                            "members": len(members), "lines": len(lines)})
    return search


def next_at(line: dict) -> float | None:
    if line.get("done"):
        return None
    if line.get("hi") is None:
        taken = [float(s["at"]) for s in line["steps"].values() if s.get("verdict") is not None]
        at = FIRST_STEP if not taken else max(taken) * 2.0
        if line["sign"] < 0:
            at = min(at, FARTHEST_DOWN)
        return round(at, 6)
    return round((float(line["lo"]) + float(line["hi"])) / 2.0, 6)


def _step_line(repo, state: dict, current: dict, line: dict, centre: dict, campaign: str) -> int:
    from graph_scale_dynamics.operations import focus
    from graph_scale_dynamics.research import neighbourhood as N
    while not line.get("done"):
        at = next_at(line)
        held = line["steps"].get(_key(at))
        if held is None:
            spec = focus._spec_of(repo, current["of"], current["law"])
            child = stepped(spec, tuple(line["path"]), int(line["sign"]), at)
            problem = "a share cannot leave 0 to 1" if child is None else N.valid(
                child, complexity_budget=int(state["complexity_budget"]), whitelist=state["whitelist"])
            if problem is not None:
                line.update(done=True, why=f"no law at {at:g}: {problem}")
                return 0
            law = focus._insert(repo, campaign, child)
            line["steps"][_key(at)] = {"at": at, "law": law, "verdict": None, "why": None}
            return 1
        if held.get("verdict") is None:
            found = reading(repo, campaign, held["law"], JUDGE_N)
            verdict, why = judged(centre, found)
            if verdict is None:
                return 0
            held.update(verdict=verdict, why=why)
        if line.get("hi") is None:
            if held["verdict"] == ALIKE:
                line["lo"] = at
                last = len(line["steps"]) >= STEPS_OUT or (line["sign"] < 0 and at >= FARTHEST_DOWN)
                if last:
                    line.update(done=True, why=f"alike to {at:g} of its value, the farthest step: no edge this side")
            else:
                line["hi"] = at
        else:
            if held["verdict"] == ALIKE:
                line["lo"] = at
            else:
                line["hi"] = at
            line["halvings"] = int(line["halvings"]) + 1
            if line["halvings"] >= HALVINGS:
                line.update(done=True, why=f"its edge between {line['lo']:g} and {line['hi']:g} of its value")
    return 0


def _members(repo, search: dict, centre: dict) -> None:
    for law, member in search["members"].items():
        if member.get("verdict") is not None:
            continue
        verdict, why = judged(centre, reading(repo, member["campaign"], law, JUDGE_N))
        if verdict is not None:
            member.update(verdict=verdict, why=why)


def _off(repo, state: dict, current: dict, search: dict, centre: dict, campaign: str) -> int:
    from graph_scale_dynamics.operations import focus
    added = 0
    if not search["off"]:
        found, refused = focus.knockouts(state, focus._spec_of(repo, current["of"], current["law"]))
        for point in found:
            search["off"][point["term"]] = {"law": focus._insert(repo, campaign, point["spec"]), "verdict": None,
                                            "why": None}
            added += 1
        for point in refused:
            search["off"][point["term"]] = {"law": None, "verdict": "refused", "why": point["why"]}
    for entry in search["off"].values():
        if entry.get("verdict") is None and entry.get("law"):
            verdict, why = judged(centre, reading(repo, campaign, entry["law"], JUDGE_N))
            if verdict is not None:
                entry.update(verdict=verdict, why=why)
    return added


def _confirm(repo, state: dict, current: dict, search: dict) -> int:
    from graph_scale_dynamics.operations import focus
    added = 0
    zone_campaign = str(state["campaigns"][focus.NEIGHBOURS])
    spec = focus._spec_of(repo, current["of"], current["law"])
    for key, line in search["lines"].items():
        if line.get("hi") is None or key in search["edges"]:
            continue
        sides = {}
        for side in ("lo", "hi"):
            child = stepped(spec, tuple(line["path"]), int(line["sign"]), float(line[side])) if line[side] else spec
            sides[side] = focus._insert(repo, zone_campaign, child) if child is not None else None
            added += 1
        search["edges"][key] = {"param": line["param"], "sign": line["sign"], "lo": line["lo"], "hi": line["hi"],
                                "lo_law": sides["lo"], "hi_law": sides["hi"], "held": None, "why": None}
    n = int(search["confirm_n"])
    centre = reading(repo, state["campaigns"][focus.SEEDS], current["law"], n)
    if centre is None:
        return added
    search["centre_at_confirm"] = {"kind": centre["kind"], "curves": sorted(L.locked(centre["curves"]))}
    for edge in search["edges"].values():
        if edge.get("held") is not None:
            continue
        inside = judged(centre, reading(repo, zone_campaign, edge["lo_law"], n)) if edge["lo_law"] else (None, "")
        outside = judged(centre, reading(repo, zone_campaign, edge["hi_law"], n)) if edge["hi_law"] else (None, "")
        if inside[0] is None or outside[0] is None:
            continue
        edge["held"] = inside[0] == ALIKE and outside[0] == OTHER
        edge["why"] = f"inside: {inside[1]}; outside: {outside[1]}"
    return added


def central_spec(spec: dict, lines: dict) -> dict:
    from graph_scale_dynamics.research import perturb as P
    child = deepcopy(spec)
    for path in P.parameters(spec):
        label = P.label(path)
        up = lines.get(f"{label} +") or {}
        down = lines.get(f"{label} -") or {}
        was = P.value_of(spec, path)
        high = was * (1.0 + float(up.get("lo") or 0.0))
        low = was * (1.0 - float(down.get("lo") or 0.0))
        P._set(child, path, float(f"{(high + low) / 2.0:.12g}"))
    return child


def _central(repo, state: dict, current: dict, search: dict) -> None:
    from graph_scale_dynamics.operations import focus
    spec = focus._spec_of(repo, current["of"], current["law"])
    child = central_spec(spec, search["lines"])
    zone_campaign = str(state["campaigns"][focus.NEIGHBOURS])
    law = current["law"] if child == spec else focus._insert(repo, zone_campaign, child)
    of = current["of"] if law == current["law"] else zone_campaign
    name = focus.label(repo, of, law)
    search["central"] = {"law": law, "of": of, "label": name, "at": utc_now()}
    from graph_scale_dynamics.operations import push
    push.add(state, law, of, name, by=f"zone {current.get('label')}")
    state["contenders"][law]["central"] = True


def advance(repo, state: dict, current: dict) -> int:
    from graph_scale_dynamics.operations import focus
    search = current["search"]
    centre = reading(repo, current["of"], current["law"], JUDGE_N)
    if centre is None:
        return 0
    current["kind"], current["kind_from"] = centre["kind"], focus.OWN_CAMPAIGN
    search["centre"] = {"kind": centre["kind"], "curves": sorted(L.locked(centre["curves"]))}
    _members(repo, search, centre)
    near = [m for m in search["members"].values() if m["near"]]
    added = 0
    if search["stage"] == MEMBERS:
        if any(m.get("verdict") is None for m in near):
            return 0
        alike = sum(1 for m in near if m["verdict"] == ALIKE)
        search["stands"] = {"alike": alike, "of": len(near), "share": search["share"]}
        if near and alike / len(near) < search["share"]:
            focus._end(state, current, focus.UNCONFIRMED,
                       f"{alike} of its {len(near)} laws within {search['radius']:g} read alike at N={JUDGE_N:,}; "
                       f"{search['share']:.0%} must")
            return 0
        search["stage"] = STEPPING
        state["events"].append({"at": utc_now(), "law": current.get("label"), "search": "its laws stand",
                                "alike": alike, "of": len(near)})
    campaign = edges_campaign(repo, state)
    if search["stage"] == STEPPING:
        added += _off(repo, state, current, search, centre, campaign)
        for line in search["lines"].values():
            added += _step_line(repo, state, current, line, centre, campaign)
        if all(line.get("done") for line in search["lines"].values()) and all(
                e.get("verdict") is not None for e in search["off"].values()):
            search["stage"] = CONFIRMING
            state["events"].append({"at": utc_now(), "law": current.get("label"), "search": "edges found",
                                    "edges": sum(1 for line in search["lines"].values() if line.get("hi") is not None)})
    if search["stage"] == CONFIRMING:
        added += _confirm(repo, state, current, search)
        if all(e.get("held") is not None for e in search["edges"].values()) and (
                search.get("centre_at_confirm") or not search["edges"]):
            _central(repo, state, current, search)
            search["benchmark"] = benchmark(repo, state, current)
            search["stage"] = DONE
            edges = list(search["edges"].values())
            focus._end(state, current, focus.MAPPED,
                       f"{sum(1 for m in search['members'].values() if m['verdict'] == ALIKE)} of its "
                       f"{len(search['members'])} laws alike; {len(edges)} edges found by stepping and halving, "
                       f"{sum(1 for e in edges if e['held'])} held at N={int(search['confirm_n']):,}; its central "
                       f"law {search['central']['label']} pushed")
    return added


def members_specs(repo, state: dict, current: dict) -> list[dict]:
    from graph_scale_dynamics.operations import focus
    search = current.get("search") or {}
    out = [focus._spec_of(repo, current["of"], current["law"])]
    out += [focus._spec_of(repo, m["campaign"], law) for law, m in (search.get("members") or {}).items()
            if m.get("verdict") == ALIKE]
    campaign = (state.get("campaigns") or {}).get(EDGES)
    for line in (search.get("lines") or {}).values():
        out += [focus._spec_of(repo, campaign, s["law"]) for s in line["steps"].values()
                if s.get("verdict") == ALIKE and campaign]
    return [spec for spec in out if spec]


def _cost(repo, pairs: list[tuple[str, str]]) -> dict:
    out = {"runs": 0, "core_hours": 0.0, "first": None, "last": None}
    for campaign, law in pairs:
        if not campaign or not law:
            continue
        row = repo.conn.execute(
            "SELECT COUNT(*) AS runs, SUM(COALESCE(a.user_cpu_seconds,0)+COALESCE(a.system_cpu_seconds,0)) AS cpu, "
            "MIN(a.started_utc) AS first, MAX(a.finished_utc) AS last FROM jobs j JOIN attempts a ON a.job_id=j.job_id "
            "WHERE j.campaign_id=? AND j.candidate_id=? AND j.kind='simulate' AND a.exit_code=0",
            (str(campaign), str(law))).fetchone()
        out["runs"] += int(row["runs"] or 0)
        out["core_hours"] += float(row["cpu"] or 0.0) / 3600.0
        for key, pick in (("first", min), ("last", max)):
            if row[key]:
                out[key] = row[key] if out[key] is None else pick(out[key], row[key])
    out["core_hours"] = round(out["core_hours"], 3)
    return out


def _hours(first, last) -> float | None:
    from graph_scale_dynamics.operations import zone_live
    a, b = zone_live.when(first), zone_live.when(last)
    return None if a is None or b is None else round((b - a).total_seconds() / 3600.0, 2)


def benchmark(repo, state: dict, current: dict) -> dict:
    from graph_scale_dynamics.operations import focus
    search = current["search"]
    edges_at = str((state.get("campaigns") or {}).get(EDGES) or "")
    zone_campaign = str(state["campaigns"][focus.NEIGHBOURS])
    rows, every = [], []
    for key, line in search["lines"].items():
        pairs = [(edges_at, s["law"]) for s in line["steps"].values()]
        edge = search["edges"].get(key) or {}
        pairs += [(zone_campaign, edge.get("lo_law")), (zone_campaign, edge.get("hi_law"))]
        found = _cost(repo, pairs)
        every += pairs
        rows.append({"line": key, "points": len(line["steps"]), "runs": found["runs"],
                     "core_hours": found["core_hours"], "hours": _hours(found["first"], found["last"]),
                     "edge": [line["lo"], line["hi"]] if line.get("hi") is not None else None,
                     "held": edge.get("held")})
    every += [(edges_at, e.get("law")) for e in search["off"].values()]
    total = _cost(repo, every)
    members = search["members"]
    seeds = int(state.get("seeds") or 3)
    rungs = sum(1 for n in (64, 256, 1024, 4096, 16384) if n <= int(search["confirm_n"]))
    ring = sum(int(count) for _radius, count in state["plan"]["neighbourhood"]["radii"])
    return {"lines": rows, "total": dict(total, hours=_hours(total["first"], total["last"])),
            "members": {"laws": len(members), "alike": sum(1 for m in members.values() if m["verdict"] == ALIKE)},
            "ring_method": {"neighbours": ring, "runs": ring * seeds * rungs,
                            "words": f"the ring method's rings alone are {ring} neighbours on {seeds} seeds at {rungs} "
                                     f"sizes to N={int(search['confirm_n']):,}: about {ring * seeds * rungs:,} runs, "
                                     f"before its outward rings and boundary lines"},
            "calls": {"edges": len(search["edges"]),
                      "held": sum(1 for e in search["edges"].values() if e.get("held"))}}


def needs(state: dict, current: dict) -> list[dict]:
    search = current["search"]
    near = [m for m in search["members"].values() if m["near"]]
    judged_near = [m for m in near if m.get("verdict") is not None]
    alike = sum(1 for m in judged_near if m["verdict"] == ALIKE)
    lines = list(search["lines"].values())
    edges = list(search["edges"].values())
    return [
        {"what": "its kind", "done": search.get("centre") is not None,
         "said": (f"{search['centre']['kind']} at N={JUDGE_N:,}, {len(search['centre']['curves'])} curves locked in"
                  if search.get("centre") else f"not read at N={JUDGE_N:,} yet")},
        {"what": "its laws", "done": search["stage"] != MEMBERS,
         "said": f"{len(judged_near)} of its {len(near)} laws within {search['radius']:g} judged, {alike} alike; "
                 f"{search['share']:.0%} must be"},
        {"what": "every edge", "done": all(line.get("done") for line in lines),
         "said": f"{sum(1 for line in lines if line.get('done'))} of {len(lines)} lines done, "
                 f"{sum(1 for line in lines if line.get('hi') is not None)} edges found"},
        {"what": f"its edges at {int(search['confirm_n']):,}", "done": search["stage"] == DONE,
         "said": f"{sum(1 for e in edges if e.get('held') is not None)} of {len(edges)} read, "
                 f"{sum(1 for e in edges if e.get('held'))} held"},
        {"what": "its central law", "done": search.get("central") is not None,
         "said": search["central"]["label"] if search.get("central") else "made once every edge is read"}]


def box(search: dict) -> dict:
    out: dict[str, dict] = {}
    for line in (search.get("lines") or {}).values():
        entry = out.setdefault(line["param"], {"path": list(line["path"]), "from": line["from"], "down": 0.0, "up": 0.0})
        entry["up" if int(line["sign"]) > 0 else "down"] = float(line.get("lo") or 0.0)
    return out


def signature_of(spec: dict) -> list:
    from graph_scale_dynamics.research import neighbourhood as N
    return json.loads(json.dumps(N.signature(spec)))


def within(zone: dict, spec: dict | None) -> bool:
    from graph_scale_dynamics.research import perturb as P
    if not spec or zone.get("stage") != "mapped" or signature_of(spec) != zone.get("signature"):
        return False
    for edge in (zone.get("box") or {}).values():
        try:
            value, was = float(P.value_of(spec, tuple(edge["path"]))), float(edge["from"])
        except (KeyError, IndexError, TypeError, ValueError):
            return False
        change = (value - was) / was if was else (0.0 if value == 0.0 else float("inf"))
        if not -float(edge["down"]) - 1e-9 <= change <= float(edge["up"]) + 1e-9:
            return False
    return True


def zone_of(repo, current: dict) -> dict:
    from graph_scale_dynamics.operations import focus
    search = current["search"]
    edges = search.get("edges") or {}
    members = search.get("members") or {}
    return {"contract": ZONE_CONTRACT, "centre": current["law"], "of": current["of"], "label": current.get("label"),
            "stage": current.get("stage"), "why": current.get("why"), "kind": (search.get("centre") or {}).get("kind"),
            "curves": (search.get("centre") or {}).get("curves"),
            "signature": signature_of(focus._spec_of(repo, current["of"], current["law"])),
            "members": sorted(law for law, m in members.items() if m.get("verdict") == ALIKE),
            "near": sorted(law for law, m in members.items() if m.get("near")), "box": box(search),
            "edges": {key: {k: e.get(k) for k in ("param", "sign", "lo", "hi", "held")} for key, e in edges.items()},
            "held_to": int(search["confirm_n"]) if edges and all(e.get("held") for e in edges.values()) else None,
            "central": search.get("central"), "cost": (search.get("benchmark") or {}).get("total"),
            "ended_utc": utc_now()}


def zones(state: dict | None) -> list[dict]:
    out = list((state or {}).get("zones") or [])
    seen = {(z.get("centre"), z.get("ended_utc")) for z in out}
    for region in (state or {}).get("regions") or []:
        for zone in region.get("zones") or []:
            if (zone.get("centre"), zone.get("ended_utc")) not in seen:
                out.append(zone)
                seen.add((zone.get("centre"), zone.get("ended_utc")))
    return out


def passed_over(found: list[dict], specs: dict[str, dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for zone in found:
        out[str(zone["centre"])] = f"the centre of {zone.get('region') or zone.get('label')}"
        if zone.get("stage") != "mapped":
            out.update({str(law): f"near {zone.get('label')}, not a zone at its radius" for law in zone.get("near") or []
                        if str(law) not in out})
    mapped = [zone for zone in found if zone.get("stage") == "mapped"]
    for law, spec in specs.items():
        if law in out:
            continue
        zone = next((z for z in mapped if within(z, spec)), None)
        if zone is not None:
            out[law] = f"inside {zone.get('region') or zone.get('label')}"
    return out


def ended(repo, state: dict, current: dict, region: dict | None) -> dict:
    from graph_scale_dynamics.operations import dex_check
    zone = zone_of(repo, current)
    if region is not None:
        zone["region"] = region["name"]
        region.setdefault("zones", []).append(zone)
    state.setdefault("zones", []).append(zone)
    state["events"].append({"at": utc_now(), "law": current.get("label"), "zone": zone["stage"],
                            "region": zone.get("region")})
    dex_check.next_zone(repo, state)
    return zone


def summary(current: dict) -> dict | None:
    search = current.get("search")
    if not search:
        return None
    kept = ("stage", "judge_n", "confirm_n", "radius", "stands", "central", "centre", "edges", "benchmark", "off")
    return {**{key: search.get(key) for key in kept},
            "members": {law: {"near": m["near"], "verdict": m["verdict"]} for law, m in search["members"].items()},
            "lines": {k: {"param": v["param"], "sign": v["sign"], "lo": v["lo"], "hi": v["hi"], "done": v["done"],
                          "why": v.get("why"), "points": len(v["steps"]),
                          "steps": {at: {"at": x["at"], "verdict": x.get("verdict"), "why": x.get("why")}
                                    for at, x in v["steps"].items()}}
                      for k, v in search["lines"].items()}}


__all__ = ["ALIKE", "CONTRACT", "EDGES", "JUDGE_N", "OTHER", "ZONE_CONTRACT", "advance", "begin", "benchmark", "box",
           "central_spec", "edges_campaign", "ended", "judged", "members_specs", "needs", "next_at", "passed_over",
           "reading", "signature_of", "stepped", "summary", "within", "zone_of", "zones"]
