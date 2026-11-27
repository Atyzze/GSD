from __future__ import annotations

import math
import time
from copy import deepcopy
from pathlib import Path

from graph_scale_dynamics.domain.model import utc_now

CONTRACT = "gsd-push-ladder-1"
PUSH = "P"
LEAST_SEEDS = 3
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


def plan(need_bytes: int | None, reach_bytes: int, workers_now: int) -> dict:
    fit = int(workers_now) if not need_bytes else int(reach_bytes) // max(1, int(need_bytes))
    if fit < 1:
        return {"fits": False, "at_once": 0, "seeds": 0, "passes": 0}
    at_once = min(int(workers_now), fit)
    seeds = max(LEAST_SEEDS, at_once)
    at_once = min(at_once, seeds)
    return {"fits": True, "at_once": at_once, "seeds": seeds, "passes": math.ceil(seeds / at_once)}


def rungs(repo, campaign_id: str, law: str) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for row in repo.conn.execute(
            "SELECT n, status, COUNT(*) AS c FROM jobs WHERE campaign_id=? AND candidate_id=? AND kind='simulate' "
            "GROUP BY n, status", (str(campaign_id), str(law))).fetchall():
        held = out.setdefault(int(row["n"]), {"queued": 0, "leased": 0, "done": 0, "failed": 0, "seeds": 0})
        key = str(row["status"]) if str(row["status"]) in held else "failed"
        held[key] += int(row["c"])
        held["seeds"] += int(row["c"])
    for row in repo.conn.execute(
            "SELECT j.n AS n, MAX(a.peak_rss_bytes) AS peak, AVG(CASE WHEN a.exit_code=0 THEN a.wall_seconds END) AS "
            "seconds FROM jobs j JOIN attempts a ON a.job_id=j.job_id WHERE j.campaign_id=? AND j.candidate_id=? "
            "AND j.kind='simulate' GROUP BY j.n", (str(campaign_id), str(law))).fetchall():
        if int(row["n"]) in out:
            out[int(row["n"])].update(peak_bytes=int(row["peak"]) if row["peak"] else None,
                                      seconds=round(float(row["seconds"]), 1) if row["seconds"] is not None else None)
    return out


def _ladder(repo, campaign_id: str) -> list[int]:
    spec = (repo.campaign(str(campaign_id)) or {}).get("spec") or {}
    return sorted(int(n) for n in spec.get("ladder") or [])


def _price(found: dict[int, dict], n: int) -> int | None:
    from graph_scale_dynamics.operations import depth_reach
    peaks = {m: int(r["peak_bytes"]) for m, r in found.items() if r.get("peak_bytes")}
    priced = depth_reach.price(peaks, int(n))
    return None if priced is None else int(priced["needs_bytes"])


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
    found = rungs(repo, camp, first)
    ladder = _ladder(repo, camp)
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
    need = None if following is None else _price(found, following)
    chosen = plan(need, reach(repo), workers(repo)) if following is not None else {"fits": False}
    if chosen["fits"]:
        _queue(repo, camp, first, following, chosen["seeds"])
        return {"law": first, "queued": following, "needs_bytes": need, **chosen}
    if any(r["queued"] or r["leased"] for r in found.values()):
        return None
    deepest = max((n for n, r in found.items() if r["done"]), default=top)
    why = (f"the top of its ladder, N={deepest:,}" if following is None else
           f"not one seed of N={following:,} fits: it needs {need / 1024 ** 3:.1f} GiB, the host admits "
           f"{reach(repo) / 1024 ** 3:.1f} GiB")
    return _end(state, first, entry, "memory" if following is not None else "ladder", deepest, why)


def _end(state: dict, law: str, entry: dict, rule: str, deepest: int | None, why: str) -> dict:
    from graph_scale_dynamics.operations import push
    push.ended(state, law, {"action": "settled", "rule": rule, "at_n": deepest, "ended_utc": utc_now()})
    state.setdefault("events", []).append({"at": utc_now(), "push_ended": entry.get("label"), "at_n": deepest,
                                           "why": why})
    state[NOW] = None
    return {"law": law, "ended": why}


def forecast(repo, campaign_id: str, law: str, *, workers_now: int | None = None, reach_bytes: int | None = None,
             now: float | None = None) -> dict:
    from graph_scale_dynamics.operations import depth_reach, push
    cores = int(workers_now if workers_now is not None else workers(repo))
    room = int(reach_bytes if reach_bytes is not None else reach(repo))
    found = rungs(repo, campaign_id, law)
    peaks = {n: int(r["peak_bytes"]) for n, r in found.items() if r.get("peak_bytes")}
    times = [{"n": n, "seconds": r["seconds"]} for n, r in sorted(found.items()) if r.get("seconds")]
    clock = time.time() if now is None else float(now)
    at, rows, limit = clock, [], None
    for n in _ladder(repo, campaign_id):
        r = found.get(n)
        if r and r["done"] and not (r["queued"] or r["leased"]):
            rows.append({"n": n, "state": "done", "seeds": r["seeds"], "done": r["done"], "failed": r["failed"],
                         "peak_bytes": r.get("peak_bytes"), "seconds": r.get("seconds")})
            continue
        priced = depth_reach.price(peaks, n) if n not in peaks else {"needs_bytes": peaks[n]}
        need = None if priced is None else int(priced["needs_bytes"])
        chosen = plan(need, room, cores)
        if not chosen["fits"]:
            limit = {"n": n, "needs_bytes": need, "reach_bytes": room}
            break
        seeds = r["seeds"] if r else chosen["seeds"]
        left = (r["queued"] + r["leased"]) if r else seeds
        took = r.get("seconds") if r and r.get("seconds") else (push.run_seconds(times, n) or {}).get("seconds")
        passes_left = math.ceil(left / max(1, chosen["at_once"]))
        hours = None if took is None else passes_left * float(took) / 3600
        row = {"n": n, "state": "running" if r else "ahead", "seeds": seeds, "left": left,
               "at_once": min(chosen["at_once"], seeds), "passes": math.ceil(seeds / max(1, chosen["at_once"])),
               "needs_bytes": need, "seconds": took, "hours": None if hours is None else round(hours, 3),
               "starts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at))}
        if hours is not None:
            at += hours * 3600
            row["ends_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at))
            if r is None:
                times.append({"n": n, "seconds": took})
        rows.append(row)
        if need is not None and n not in peaks:
            peaks[n] = int(need / depth_reach.SAFETY)
    ahead = [row for row in rows if row["state"] != "done"]

    def first(test) -> dict | None:
        found_row = next((row for row in ahead if test(row)), None)
        return None if found_row is None else {"n": found_row["n"], "at_utc": found_row["starts_utc"],
                                               "at_once": found_row["at_once"], "seeds": found_row["seeds"]}
    marks = {"fewer": first(lambda row: row["at_once"] < cores),
             "two_passes": first(lambda row: row["passes"] >= 2 and row["at_once"] < cores),
             "one_worker": first(lambda row: row["at_once"] == 1 < cores)}
    timed = all(row.get("hours") is not None for row in ahead)
    end = None if not ahead or not timed else {"n": ahead[-1]["n"], "ends_utc": ahead[-1].get("ends_utc"),
                                               "hours": round((at - clock) / 3600, 2)}
    return {"contract": CONTRACT, "law": law, "campaign": str(campaign_id), "workers": cores, "reach_bytes": room,
            "rungs": rows, "limit": limit, "marks": marks, "end": end, "now_utc": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock))}


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


__all__ = ["CONTRACT", "EVERY_SECONDS", "LEAST_SEEDS", "NOW", "PUSH", "campaign", "forecast", "is_push", "plan", "reach", "rungs",
           "step", "tick", "workers"]
