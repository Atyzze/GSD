from __future__ import annotations

import math
import time
from copy import deepcopy
from pathlib import Path

from graph_scale_dynamics.domain.model import utc_now

CONTRACT = "gsd-push-ladder-2"
CEILING_RULE = "ceiling"
PUSHED_SLACK = 1.1
PUSH = "P"
SEEDS = 3
EVERY_SECONDS = 5.0
NOW = "depth_now"
_LAST: dict[str, float] = {}


def campaign(repo, state: dict, *, tree=None) -> str:
    from graph_scale_dynamics import PROJECT_ROOT
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import focus
    if state["campaigns"].get(PUSH):
        return str(state["campaigns"][PUSH])
    tree = Path(tree) if tree is not None else Path(PROJECT_ROOT)
    study = str(state["study"])
    anchor = next(iter(focus.own_campaigns(repo, study)))
    spec = deepcopy(focus.campaign_specs(repo, study, anchor, state["plan"], tree)[focus.DEPTH])
    spec["study_design"] = dict(spec["study_design"], focus=dict(spec["study_design"]["focus"], part=PUSH))
    spec["name"] = f"study {study}: the laws pushed to the N limit, each its ladder again from 64 on every worker"
    spec["description"] = spec["name"]
    made = control.create_campaign(repo, spec, search_seed=focus._seed(study, PUSH),
                                   reason=f"study {study}'s push list: a law's ladder run on every worker")
    state["campaigns"][PUSH] = str(made["campaign_id"])
    return str(made["campaign_id"])


def is_push(spec: dict | None) -> bool:
    return (((spec or {}).get("study_design") or {}).get("focus") or {}).get("part") == PUSH


def workers(repo) -> int:
    from graph_scale_dynamics.scheduling import worker_count
    getter = getattr(repo, "get_flag", None)
    if not callable(getter):
        return 1
    most = worker_count.most_of(getter(worker_count.MOST_FLAG, ""), 1)
    wanted = worker_count.wanted(getter(worker_count.FLAG, ""), most)
    if wanted:
        return int(wanted)
    raw = str(getter("compute_total_slots", "") or "")
    return max(1, int(raw)) if raw.isdigit() else 1


def reach(repo) -> int:
    from graph_scale_dynamics.operations import depth_reach
    return int(depth_reach.room_now(repo).get("reach_bytes") or 0)


def plan(priced: dict | None, reach_bytes: int, workers_now: int) -> dict:
    if priced is not None and not priced["fits"]:
        return {"fits": False, "at_once": 0, "seeds": 0, "passes": 0}
    fit = int(workers_now) if priced is None else min(int(workers_now), int(priced["at_once"]))
    at_once = max(1, min(SEEDS, fit))
    return {"fits": True, "at_once": at_once, "seeds": SEEDS, "passes": math.ceil(SEEDS / at_once)}


def rungs(repo, campaign_id: str, law: str) -> dict[int, dict]:
    from statistics import median
    out: dict[int, dict] = {}
    for row in repo.conn.execute(
            "SELECT n, status, COUNT(*) AS c FROM jobs WHERE campaign_id=? AND candidate_id=? AND kind='simulate' "
            "AND status<>'cancelled' GROUP BY n, status", (str(campaign_id), str(law))).fetchall():
        held = out.setdefault(int(row["n"]), {"queued": 0, "leased": 0, "done": 0, "failed": 0, "seeds": 0})
        key = str(row["status"]) if str(row["status"]) in held else "failed"
        held[key] += int(row["c"])
        held["seeds"] += int(row["c"])
    runs = _runs(repo, campaign_id, law)
    for n, held in out.items():
        mine = [r for r in runs.values() if r["n"] == n]
        whole = [p for r in mine for p in r["whole"]]
        cut = [p for r in mine for p in r["cut"]]
        walls = [r["wall"] for r in mine if r["done"] and r["wall"] > 0]
        spans = [span for r in mine for span in r["spans"]]
        held.update(peak_bytes=max(whole) if whole else None, typical_bytes=int(median(whole)) if whole else None,
                    cut_bytes=max(cut) if cut else None,
                    seconds=round(sum(walls) / len(walls), 1) if walls else None, **_ran(spans))
    for n, live in running(repo, campaign_id, law).items():
        if n in out:
            out[n].update(live)
    return out


def _runs(repo, campaign_id: str, law: str) -> dict[str, dict]:
    runs: dict[str, dict] = {}
    for row in repo.conn.execute(
            "SELECT j.job_id AS job, j.n AS n, a.exit_code AS code, a.peak_rss_bytes AS peak, a.wall_seconds AS wall, "
            "a.started_utc AS began, a.finished_utc AS ended FROM jobs j JOIN attempts a ON a.job_id=j.job_id "
            "WHERE j.campaign_id=? AND j.candidate_id=? AND j.kind='simulate'", (str(campaign_id), str(law))).fetchall():
        run = runs.setdefault(str(row["job"]), {"n": int(row["n"]), "whole": [], "cut": [], "wall": 0.0, "done": False,
                                                "spans": []})
        if row["began"] and row["ended"]:
            run["spans"].append((str(row["began"]), str(row["ended"])))
        whole = row["code"] is not None and int(row["code"]) == 0
        if row["peak"]:
            run["whole" if whole else "cut"].append(int(row["peak"]))
        run["wall"] += float(row["wall"] or 0.0)
        run["done"] = run["done"] or whole
    return runs


def _ran(spans: list[tuple[str, str]]) -> dict:
    if not spans:
        return {"began_utc": None, "ended_utc": None, "most_at_once": None}
    events = sorted([(began, 1) for began, _ in spans] + [(ended, -1) for _, ended in spans],
                    key=lambda e: (e[0], e[1]))
    now = most = 0
    for _at, step in events:
        now += step
        most = max(most, now)
    return {"began_utc": min(b for b, _ in spans), "ended_utc": max(e for _, e in spans), "most_at_once": most}


def _seconds_between(began: str | None, ended: str | None) -> float | None:
    from datetime import datetime
    if not began or not ended:
        return None
    def read(stamp: str):
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    return max(0.0, (read(ended) - read(began)).total_seconds())


def trim(repo, campaign_id: str, law: str) -> int:
    from graph_scale_dynamics.domain.model import utc_now
    cut = 0
    for n in {int(r["n"]) for r in repo.conn.execute(
            "SELECT n FROM jobs WHERE campaign_id=? AND candidate_id=? AND kind='simulate' AND status='queued'",
            (str(campaign_id), str(law))).fetchall()}:
        jobs = repo.conn.execute(
            "SELECT job_id, status FROM jobs WHERE campaign_id=? AND candidate_id=? AND kind='simulate' AND n=? "
            "AND status IN ('queued','leased','done') ORDER BY CASE status WHEN 'done' THEN 0 WHEN 'leased' THEN 1 "
            "ELSE 2 END, seed", (str(campaign_id), str(law), int(n))).fetchall()
        extra = [str(row["job_id"]) for row in jobs[SEEDS:] if str(row["status"]) == "queued"]
        for job_id in extra:
            cut += repo.conn.execute("UPDATE jobs SET status='cancelled', updated_utc=? WHERE job_id=? AND "
                                     "status='queued'", (utc_now(), job_id)).rowcount or 0
    return cut


def running(repo, campaign_id: str, law: str) -> dict[int, dict]:
    from graph_scale_dynamics.operations import push
    out: dict[int, dict] = {}
    for row in repo.conn.execute(
            "SELECT job_id, n, lease_owner, memory_reservation_bytes FROM jobs WHERE campaign_id=? AND "
            "candidate_id=? AND kind='simulate' AND status='leased'", (str(campaign_id), str(law))).fetchall():
        held = out.setdefault(int(row["n"]), {"running": 0, "held_bytes": 0, "live_bytes": None})
        held["running"] += 1
        held["held_bytes"] += int(row["memory_reservation_bytes"] or 0)
        seen = push._memory_of(repo, row["lease_owner"], str(row["job_id"])).get("memory_peak")
        if seen:
            held["live_bytes"] = max(int(seen), int(held["live_bytes"] or 0))
    return out


def _ladder(repo, campaign_id: str) -> list[int]:
    spec = (repo.campaign(str(campaign_id)) or {}).get("spec") or {}
    return sorted(int(n) for n in spec.get("ladder") or [])


def asked(repo, campaign_id: str, law: str, n: int) -> int | None:
    import json
    from graph_scale_dynamics.scheduling import memory
    own = pushed_ask(repo, campaign_id, law, n)
    if own is not None:
        return own
    row = repo.conn.execute(
        "SELECT spec_json FROM jobs WHERE campaign_id=? AND candidate_id=? AND kind='simulate' ORDER BY n DESC "
        "LIMIT 1", (str(campaign_id), str(law))).fetchone()
    spec = (json.loads(row["spec_json"]) if row is not None and row["spec_json"]
            else (repo.campaign(str(campaign_id)) or {}).get("spec") or {})
    return int(memory.predicted_claim_peak_bytes(repo.conn, kind="simulation", campaign_id=str(campaign_id),
                                                 candidate_id=str(law), n=int(n), spec=spec))


def pushed_ask(repo, campaign_id: str, law: str, n: int, *, job_id: str | None = None) -> int | None:
    from statistics import median

    from graph_scale_dynamics.operations import depth_reach
    from graph_scale_dynamics.scheduling import memory
    runs = _runs(repo, campaign_id, law)
    whole: dict[int, list[int]] = {}
    for run in runs.values():
        whole.setdefault(run["n"], []).extend(run["whole"])
    typical = {m: int(median(v)) for m, v in whole.items() if v}
    grown = depth_reach.price(typical, int(n))
    expected = typical.get(int(n)) or (int(grown["needs_bytes"] / depth_reach.SAFETY) if grown else 0)
    mine = (runs.get(str(job_id)) or {}) if job_id else {}
    expected = max(int(expected or 0), *(int(p) for p in (mine.get("whole") or []) + (mine.get("cut") or [])), 0)
    if not expected:
        return None
    seen = memory.runaway_seen_bytes(repo.conn, "simulation", str(campaign_id), str(law), int(n))
    return max(int(math.ceil(float(expected) * PUSHED_SLACK)),
               int(math.ceil(float(seen) * memory.RUNAWAY_SEEN_SLACK)) if seen else 0)


def claim_bytes(repo, job: dict) -> int | None:
    job["pushed"] = pushed(repo, job["campaign_id"])
    if not job["pushed"]:
        return None
    return pushed_ask(repo, str(job["campaign_id"]), str(job["candidate_id"]), int(job["n"]),
                      job_id=str(job["job_id"]))


def pushed(repo, campaign_id: str) -> bool:
    found = getattr(repo, "campaign", None)
    return callable(found) and is_push((found(str(campaign_id)) or {}).get("spec") or {})


def typical_peaks(found: dict[int, dict]) -> dict[int, int]:
    return {m: int(r["typical_bytes"]) for m, r in found.items() if r.get("typical_bytes")}


def price(repo, campaign_id: str, law: str, found: dict[int, dict], n: int, reach_bytes: int, *,
          typical: dict[int, int] | None = None) -> dict:
    from graph_scale_dynamics.operations import depth_reach
    typical = typical_peaks(found) if typical is None else typical
    here = found.get(int(n)) or {}
    grown = depth_reach.price(typical, int(n))
    grown_bytes = None if grown is None else int(grown["needs_bytes"])
    own = here.get("typical_bytes")
    expected = int(own) if own else max(int(grown_bytes / depth_reach.SAFETY) if grown_bytes else 0,
                                        int(here.get("live_bytes") or 0), int(here.get("cut_bytes") or 0)) or None
    asks = asked(repo, campaign_id, law, int(n))
    first = max(int(asks or 0), int(grown_bytes or 0)) or expected
    hold = int(math.ceil(float(expected) * PUSHED_SLACK)) if expected else first
    fits = grown_bytes is None or grown_bytes <= int(reach_bytes)
    if not first:
        at_once = None
    elif first > int(reach_bytes):
        at_once = 1
    else:
        at_once = 1 + (int(reach_bytes) - int(first)) // max(1, int(hold or first))
    return {"n": int(n), "fits": bool(fits), "at_once": at_once, "needs_bytes": first, "asked_bytes": asks,
            "grown_bytes": grown_bytes, "expected_bytes": expected, "hold_bytes": hold,
            "waits": bool(first and first > int(reach_bytes))}


def _plan_of(priced: dict | None, reach_bytes: int, workers_now: int) -> dict:
    if priced is not None and priced["at_once"] is None:
        priced = None
    return plan(priced, reach_bytes, workers_now)


class _Said:
    def __init__(self):
        self.lines: list[tuple[str, dict]] = []

    def write(self, what: str, **detail) -> None:
        self.lines.append((what, detail))


def _store(repo, campaign_id: str):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    return DecisionStore(repo, _Said(), repo.campaign(str(campaign_id)) or {"campaign_id": str(campaign_id)})


def _queue(repo, campaign_id: str, law: str, n: int, seeds: int) -> int:
    from graph_scale_dynamics.scheduling.limits import work_budget
    store = _store(repo, campaign_id)
    return int(store.enqueue_seeds(str(campaign_id), str(law), int(n), seeds=int(seeds),
                                   work_budget=int(work_budget(store.spec, int(n))), queue_order=0) or 0)


def _held(repo, campaign_id: str, law: str, spec: dict) -> None:
    from graph_scale_dynamics.domain.model import CandidateState
    from graph_scale_dynamics.dsl import dsl
    if repo.candidate(str(law), str(campaign_id)) is None:
        normalized = dsl.normalize(spec)
        repo.insert_candidate(dsl.fingerprint(normalized), str(campaign_id), normalized,
                              normalized["dynamics"]["kind"], dsl.complexity(normalized), CandidateState.EXTENDING.value)


def step(repo, state: dict) -> dict | None:
    from graph_scale_dynamics.operations import focus, push
    first = push.ahead(state, {})
    if first is None:
        state[NOW] = None
        return None
    camp = campaign(repo, state)
    entry = state["contenders"][first]
    _held(repo, camp, first, focus._spec_of(repo, entry["of"], first))
    now = state.get(NOW) or {}
    if now.get("law") != first:
        state[NOW] = now = {"law": first, "label": entry.get("label"), "campaign": camp, "since": utc_now()}
    trimmed = trim(repo, camp, first)
    if trimmed:
        state.setdefault("events", []).append({"at": utc_now(), "law": entry.get("label"), "trimmed": trimmed,
                                               "why": f"{SEEDS} seeds a rung: {trimmed} queued seed(s) let go"})
    found = rungs(repo, camp, first)
    whole = _ladder(repo, camp)
    ceiling = push.ceiling_of(state, first)
    ladder = [n for n in whole if n <= ceiling]
    top = max(found) if found else None
    if top is None:
        chosen = plan(None, reach(repo), workers(repo))
        _queue(repo, camp, first, ladder[0], chosen["seeds"])
        return {"law": first, "queued": ladder[0], **chosen}
    if found[top]["done"] < 1:
        if found[top]["queued"] or found[top]["leased"]:
            return None
        return _end(state, first, entry, "failed", max((n for n, r in found.items() if r["done"]), default=None),
                    f"every seed of N={top:,} failed")
    following = next((n for n in ladder if n > top), None)
    room = reach(repo)
    priced = None if following is None else price(repo, camp, first, found, following, room)
    chosen = _plan_of(priced, room, workers(repo)) if following is not None else {"fits": False}
    if chosen["fits"]:
        _queue(repo, camp, first, following, chosen["seeds"])
        return {"law": first, "queued": following, "needs_bytes": (priced or {}).get("needs_bytes"),
                "asked_bytes": (priced or {}).get("asked_bytes"), **chosen}
    if any(r["queued"] or r["leased"] for r in found.values()):
        return None
    deepest = max((n for n, r in found.items() if r["done"]), default=top)
    need = int((priced or {}).get("grown_bytes") or 0)
    capped = following is None and any(n > ceiling for n in whole)
    why = (f"its ceiling, N={deepest:,}: a law goes higher only when pushed past it" if capped else
           f"the top of its ladder, N={deepest:,}" if following is None else
           f"not one seed of N={following:,} fits: it needs {need / 1024 ** 3:.1f} GiB, the host admits "
           f"{room / 1024 ** 3:.1f} GiB")
    rule = "memory" if following is not None else CEILING_RULE if capped else "ladder"
    return _end(state, first, entry, rule, deepest, why)


def _end(state: dict, law: str, entry: dict, rule: str, deepest: int | None, why: str) -> dict:
    from graph_scale_dynamics.operations import push
    push.ended(state, law, {"action": "settled", "rule": rule, "at_n": deepest, "ended_utc": utc_now()})
    state.setdefault("events", []).append({"at": utc_now(), "push_ended": entry.get("label"), "at_n": deepest,
                                           "why": why})
    state[NOW] = None
    return {"law": law, "ended": why}


def forecast(repo, campaign_id: str, law: str, *, workers_now: int | None = None, reach_bytes: int | None = None,
             now: float | None = None, ceiling: int | None = None) -> dict:
    from graph_scale_dynamics.operations import depth_reach, push
    cores = int(workers_now if workers_now is not None else workers(repo))
    room = int(reach_bytes if reach_bytes is not None else reach(repo))
    found = rungs(repo, campaign_id, law)
    typical = typical_peaks(found)
    times = [{"n": n, "seconds": r["seconds"]} for n, r in sorted(found.items()) if r.get("seconds")]
    clock = time.time() if now is None else float(now)
    at, rows, limit, under_way = clock, [], None, None
    whole = _ladder(repo, campaign_id)
    for n in whole:
        if ceiling is not None and n > int(ceiling):
            break
        r = found.get(n)
        if r and r["done"] and not (r["queued"] or r["leased"]):
            took = _seconds_between(r.get("began_utc"), r.get("ended_utc"))
            most = r.get("most_at_once")
            rows.append({"n": n, "state": "done", "seeds": r["seeds"], "done": r["done"], "failed": r["failed"],
                         "peak_bytes": r.get("peak_bytes"), "typical_bytes": r.get("typical_bytes"),
                         "seconds": r.get("seconds"), "at_once": most,
                         "passes": math.ceil(r["seeds"] / most) if most else None,
                         "hours": None if took is None else round(took / 3600, 3),
                         "starts_utc": r.get("began_utc"), "ends_utc": r.get("ended_utc")})
            continue
        priced = price(repo, campaign_id, law, found, n, room, typical=typical)
        chosen = _plan_of(priced, room, cores)
        if not chosen["fits"]:
            limit = {"n": n, "needs_bytes": priced["grown_bytes"], "asked_bytes": priced["asked_bytes"],
                     "reach_bytes": room}
            break
        seeds = r["seeds"] if r else chosen["seeds"]
        left = (r["queued"] + r["leased"]) if r else seeds
        steady = max(1, min(chosen["at_once"], seeds))
        runs_now = int((r or {}).get("running") or 0)
        if runs_now:
            free = int(_headroom(repo) or 0)
            more = free // max(1, int(priced["needs_bytes"] or 1))
            at_once = max(1, min(left, runs_now + more))
            passes_left = 1 + math.ceil(max(0, left - at_once) / steady)
            under_way = {"n": n, "running": runs_now, "held_bytes": int(r.get("held_bytes") or 0),
                         "live_bytes": r.get("live_bytes"), "asked_bytes": priced["needs_bytes"],
                         "headroom_bytes": free, "more": int(min(more, max(0, left - runs_now)))}
        else:
            at_once = steady
            passes_left = math.ceil(left / at_once)
        took = r.get("seconds") if r and r.get("seconds") else (push.run_seconds(times, n) or {}).get("seconds")
        hours = None if took is None else passes_left * float(took) / 3600
        row = {"n": n, "state": "running" if r else "ahead", "seeds": seeds, "left": left,
               "at_once": at_once, "passes": math.ceil(seeds / at_once),
               "needs_bytes": priced["needs_bytes"], "asked_bytes": priced["asked_bytes"],
               "grown_bytes": priced["grown_bytes"], "expected_bytes": priced["expected_bytes"],
               "hold_bytes": priced["hold_bytes"], "waits": priced["waits"],
               "seconds": took, "hours": None if hours is None else round(hours, 3),
               "starts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at))}
        if r is not None:
            row.update(running=runs_now, held_bytes=int(r.get("held_bytes") or 0), live_bytes=r.get("live_bytes"),
                       cut_bytes=r.get("cut_bytes"))
        if hours is not None:
            at += hours * 3600
            row["ends_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at))
            if r is None:
                times.append({"n": n, "seconds": took})
        rows.append(row)
        if n not in typical and priced["grown_bytes"]:
            typical[n] = int(priced["grown_bytes"] / depth_reach.SAFETY)
    ahead = [row for row in rows if row["state"] != "done"]

    def first(test) -> dict | None:
        found_row = next((row for row in ahead if test(row)), None)
        return None if found_row is None else {"n": found_row["n"], "at_utc": found_row["starts_utc"],
                                               "at_once": found_row["at_once"], "seeds": found_row["seeds"]}
    marks = {"fewer": first(lambda row: row["at_once"] < min(cores, row["seeds"])),
             "two_passes": first(lambda row: row["passes"] >= 2),
             "one_worker": first(lambda row: row["at_once"] == 1 < row["seeds"])}
    timed = all(row.get("hours") is not None for row in ahead)
    end = None if not ahead or not timed else {"n": ahead[-1]["n"], "ends_utc": ahead[-1].get("ends_utc"),
                                               "hours": round((at - clock) / 3600, 2)}
    return {"contract": CONTRACT, "law": law, "campaign": str(campaign_id), "workers": cores, "reach_bytes": room,
            "rungs": rows, "limit": limit, "marks": marks, "end": end, "under_way": under_way,
            "ceiling": _past(repo, campaign_id, law, found, whole, ceiling, room, typical, times),
            "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock))}


def _past(repo, campaign_id: str, law: str, found: dict, whole: list[int], ceiling: int | None, room: int,
          typical: dict[int, int], times: list[dict]) -> dict | None:
    from graph_scale_dynamics.operations import push
    if ceiling is None:
        return None
    following = next((n for n in whole if n > int(ceiling)), None)
    out = {"n": int(ceiling), "next": following}
    if following is not None and not (found.get(following) or {}).get("seeds"):
        priced = price(repo, campaign_id, law, found, following, room, typical=typical)
        out.update(next_bytes=priced["needs_bytes"], next_fits=priced["fits"], next_at_once=priced["at_once"],
                   next_seconds=(push.run_seconds(times, following) or {}).get("seconds"))
    return out


def _headroom(repo) -> int | None:
    from graph_scale_dynamics.scheduling import memory
    return int(memory.admission_headroom(repo.conn).get("headroom_bytes") or 0)


def tick(repo, *, now: float | None = None, force: bool = False) -> dict | None:
    from graph_scale_dynamics.operations import focus, modes
    state = focus.load(repo)
    if state is None or state.get("stopped"):
        return None
    clock = time.monotonic() if now is None else float(now)
    if not force and clock - _LAST.get(str(state["study"]), -1e18) < EVERY_SECONDS:
        return None
    _LAST[str(state["study"])] = clock
    before = (deepcopy(state.get(NOW)), list(state["campaigns"].values()), len(state.get("pushed") or []))
    done = step(repo, state)
    if (deepcopy(state.get(NOW)), list(state["campaigns"].values()), len(state.get("pushed") or [])) != before:
        focus.save(repo, state)
    modes.keep(repo, state)
    return done


__all__ = ["CEILING_RULE", "CONTRACT", "EVERY_SECONDS", "NOW", "PUSH", "PUSHED_SLACK", "SEEDS", "asked", "campaign",
           "claim_bytes", "forecast", "is_push", "plan", "price", "pushed", "pushed_ask", "reach", "rungs",
           "running", "step", "tick", "trim", "typical_peaks", "workers"]
