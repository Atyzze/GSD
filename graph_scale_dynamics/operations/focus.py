from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from pathlib import Path

from graph_scale_dynamics.domain.model import utc_now
from graph_scale_dynamics.operations import focus_regions as R

CONTRACT = "gsd-focus-1"
FLAG = "study_focus"
PLAN = "graph_scale_dynamics/resources/readings/focus_plan_1.json"
KIND = "focus"
NEIGHBOURS, DEPTH, SEEDS = "N", "D", "S"
GROUP_OF = {NEIGHBOURS: NEIGHBOURS, SEEDS: NEIGHBOURS, DEPTH: DEPTH}
NEIGHBOURHOOD, BOUNDARIES, MAPPED, UNCONFIRMED, INVALIDATED = (
    "neighbourhood", "boundaries", "mapped", "unconfirmed", "invalidated")
ENDED = (MAPPED, UNCONFIRMED, INVALIDATED)
ROBUST, ITS_SEEDS, ITS_DIGITS = "robust", "its seeds", "its exact parameters"
DOS = ("start", "law", "skip", "back", "stop", "settings", "split", "run_on", "seed")
QUEUE_LENGTH = 100
KNOCKOUT = "term off"
MAPPED_PER_TYPE = 3
KNOWN_FROM_THE_TABLE = 1
INTERVAL_SECONDS = 60.0
_LAST: dict[str, float] = {}


def plan(tree=None) -> dict:
    from graph_scale_dynamics.resources import committed
    return json.loads(committed.resolve(PLAN, tree).read_text(encoding="utf-8"))


def load(repo) -> dict | None:
    try:
        state = json.loads(repo.get_flag(FLAG, "") or "null")
    except (TypeError, ValueError):
        return None
    return state if isinstance(state, dict) and state.get("contract") == CONTRACT else None


def save(repo, state: dict) -> None:
    repo.set_flag(FLAG, json.dumps(state, sort_keys=True, separators=(",", ":")))


def graph_number(repo, campaign_id: str, law: str) -> int | None:
    row = repo.conn.execute(
        "SELECT MIN(graph_ordinal) AS g FROM jobs WHERE campaign_id=? AND candidate_id=? AND kind='simulate' "
        "AND graph_ordinal IS NOT NULL", (str(campaign_id), str(law))).fetchone()
    return None if row is None or row["g"] is None else int(row["g"])


def label(repo, campaign_id: str, law: str) -> str:
    found = graph_number(repo, campaign_id, law)
    return f"C{campaign_id}-G{found}" if found is not None else f"C{campaign_id}-{str(law)[:8]}"


def own_campaigns(repo, study: str) -> list[str]:
    out = []
    for campaign in repo.all_campaigns():
        design = (campaign.get("spec") or {}).get("study_design") or {}
        if str(design.get("study")) == str(study) and design.get("kind") != KIND:
            out.append(str(campaign["campaign_id"]))
    return out


def _number(text) -> float:
    return float(text) if str(text).isdigit() else float("inf")


def best(repo, study: str) -> list[dict]:
    from graph_scale_dynamics.observability import score_board
    found = []
    for campaign_id in own_campaigns(repo, study):
        for law, score in (score_board.board(repo, campaign_id).get("scores") or {}).items():
            if int(score.get("score") or 0) > 0:
                found.append({"candidate_id": str(law), "campaign": campaign_id, "score": int(score["score"])})
    for entry in found:
        entry["graph"] = graph_number(repo, entry["campaign"], entry["candidate_id"])
        entry["label"] = (f"C{entry['campaign']}-G{entry['graph']}" if entry["graph"] is not None
                          else f"C{entry['campaign']}-{entry['candidate_id'][:8]}")
    return sorted(found, key=lambda e: (-e["score"], _number(e["campaign"]),
                                        e["graph"] if e["graph"] is not None else float("inf"), e["candidate_id"]))


def _rows(repo, campaign_id: str, law: str) -> tuple[list[dict], list | None]:
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    rows = repo.measurements(str(law), ANALYSIS_VERSION, str(campaign_id))
    spec = (repo.campaign(str(campaign_id)) or {}).get("spec") or {}
    return rows, (spec.get("sampling_contract") or {}).get("given_starts")


def _kinds_of(rows: list[dict], starts) -> dict[int, str]:
    from graph_scale_dynamics.observability import law_kind, two_chains
    return {int(n): k for n, k in law_kind.kinds(two_chains.chains_per_rung(rows, starts)).items()}


def kinds(repo, campaign_id: str, law: str, *, whole: int | None = None) -> dict[int, str]:
    rows, starts = _rows(repo, campaign_id, law)
    if whole:
        seeds: dict[int, set] = {}
        for row in rows:
            seeds.setdefault(int(row["n"]), set()).add(int(row["seed"]))
        rows = [row for row in rows if len(seeds[int(row["n"])]) >= int(whole)]
    return _kinds_of(rows, starts)


def seed_kinds(repo, campaign_id: str, law: str) -> dict[int, dict[int, str]]:
    rows, starts = _rows(repo, campaign_id, law)
    return {seed: _kinds_of([r for r in rows if int(r["seed"]) == seed], starts)
            for seed in sorted({int(row["seed"]) for row in rows})}


def verdict(repo, campaign_id: str, law: str, read_n: int) -> str | None:
    from graph_scale_dynamics.operations import study_map
    if not study_map.decided(repo, campaign_id, law):
        return None
    found = kinds(repo, campaign_id, law)
    if int(read_n) in found:
        return found[int(read_n)]
    row = repo.conn.execute("SELECT rule,at_n FROM engine_decisions_latest WHERE campaign_id=? AND candidate_id=?",
                            (str(campaign_id), str(law))).fetchone()
    return f"stopped: {row['rule']} at {int(row['at_n']):,}" if row is not None else "stopped"


def _design_for(repo, study: str, holder_campaign: str, tree: Path) -> tuple[dict, int]:
    from graph_scale_dynamics.operations import study_design as SD
    designed = ((repo.campaign(str(holder_campaign)) or {}).get("spec") or {}).get("study_design") or {}
    design = SD.design_for(tree, str(study))
    if design is None:
        raise ValueError(f"this tree holds no design for study {study}")
    if designed.get("design_sha256") and design["sha256"] != designed["design_sha256"]:
        raise ValueError(f"study {study}'s design in this tree ({design['sha256'][:12]}) is not the one campaign "
                         f"{holder_campaign} was made with ({str(designed['design_sha256'])[:12]})")
    return design, int(designed.get("campaign") or 0)


def _laddered(spec: dict, design: dict, deep: list[int], seeds: int) -> dict:
    from graph_scale_dynamics.decisions.engine import Policy
    from graph_scale_dynamics.scheduling.ladder_spec import engine_ladder
    base_sizes = [int(n) for n in design["ladder"]["base"]]
    policy = Policy.from_spec(spec)
    budgets = {int(n): int(units) for n, units in design["ladder"].get("budgets") or []}
    return engine_ladder(spec, base_sizes=base_sizes, deep_sizes=deep, seeds=int(seeds),
                         budgets={n: budgets.get(n, policy.work_budget(n)) for n in base_sizes + deep},
                         audit_fraction=float(policy.audit_fraction))


def campaign_specs(repo, study: str, holder_campaign: str, found_plan: dict, tree: Path) -> dict[str, dict]:
    from graph_scale_dynamics.operations import study_design as SD
    design, index = _design_for(repo, study, holder_campaign, tree)
    base = json.loads((Path(tree) / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json")
                      .read_text(encoding="utf-8"))
    base = SD.without_terms(design, base, log=lambda *_: None)
    around = SD.campaign_spec(design, base, design["campaigns"][index], index)
    read_n = int(found_plan["neighbourhood"]["read_n"])
    seeds = int(design["ladder"]["seeds"])
    upto = [int(n) for n in design["ladder"]["deep"] if int(n) <= read_n]
    shapes = {NEIGHBOURS: (upto, seeds, "its best laws' neighbourhoods"),
              SEEDS: (upto, seeds * int(found_plan["seeds"]["times"]), "its best laws on more seeds"),
              DEPTH: ([int(n) for n in design["ladder"]["deep"]] + [int(n) for n in found_plan["depth"]["beyond"]],
                      seeds, "its best laws' depth")}
    out = {}
    for name, (deep, count, words) in shapes.items():
        spec = deepcopy(around)
        spec["proposer"] = {"pool_min": 1}
        spec["search_policy"] = {"contract": "gsd-hand-1", "kind": "hand"}
        spec["study_design"] = dict(spec["study_design"], kind=KIND, group=GROUP_OF[name], campaign=None,
                                    focus={"contract": CONTRACT, "plan": PLAN, "part": name})
        spec["name"] = f"study {study}: {words} (group {GROUP_OF[name]})"
        spec["description"] = f"{spec['name']}; {found_plan['asked']}"
        out[name] = _laddered(spec, design, deep, count)
    out[DEPTH]["engine"]["policy"]["let_through_from"] = 2 * max(out[DEPTH]["ladder"])
    return out


def _seed(*parts) -> int:
    return int(hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).hexdigest(), 16) % (2 ** 63)


def _insert(repo, campaign_id: str, spec: dict) -> str:
    from graph_scale_dynamics.operations import study_map
    if str((repo.campaign(str(campaign_id)) or {}).get("status") or "") not in ("active", "paused"):
        repo.set_campaign_status(str(campaign_id), "active")
    return study_map._insert(repo, str(campaign_id), spec)


def _spec_of(repo, campaign_id: str, law: str) -> dict:
    return (repo.candidate(str(law), str(campaign_id)) or {}).get("spec") or {}


def neighbours(state: dict, law: str, spec: dict, radii: list) -> tuple[list[dict], list[dict]]:
    from graph_scale_dynamics.research import perturb as P
    out, refused = [], []
    for radius, count in radii:
        try:
            found = P.variants(spec, law, salt=f"focus {state['study']}", radii=(float(radius),),
                               per_radius=int(count), complexity_budget=int(state["complexity_budget"]),
                               whitelist=state["whitelist"])
        except ValueError as exc:
            refused.append({"radius": float(radius), "why": str(exc)})
            continue
        out += [{"how": "neighbour", "radius": f["radius"], "index": f["index"], "spec": f["spec"]} for f in found]
    return out, refused


def knockouts(state: dict, spec: dict) -> tuple[list[dict], list[dict]]:
    from graph_scale_dynamics.dsl import dsl
    terms = list((spec or {}).get("terms") or [])
    out, refused = [], []
    for place, term in enumerate(terms):
        name = R.term_name(term)
        child = dict(spec, terms=[t for i, t in enumerate(terms) if i != place])
        problems = dsl.validate(child, complexity_budget=int(state["complexity_budget"]),
                                operator_whitelist=state["whitelist"]) if child["terms"] else ["no term left"]
        if problems:
            refused.append({"term": name, "why": "; ".join(str(p) for p in problems)[:200]})
            continue
        out.append({"how": KNOCKOUT, "term": name, "spec": dsl.normalize(child)})
    return out, refused


def terms_read(current: dict, verdicts: dict) -> dict[str, dict]:
    out = {}
    for law, point in current["points"].items():
        if point.get("how") != KNOCKOUT:
            continue
        seen = verdicts.get(law)
        out[point["term"]] = {"law": law, "kind": seen,
                              "load_bearing": None if seen is None else seen != current["kind"]}
    return out


def core_of(found: dict[str, dict]) -> list[str] | None:
    if not found or any(row["load_bearing"] is None for row in found.values()):
        return None
    return sorted(term for term, row in found.items() if row["load_bearing"])


def _add(repo, state: dict, current: dict, points: list[dict]) -> int:
    for point in points:
        law = _insert(repo, state["campaigns"][NEIGHBOURS], point["spec"])
        current["points"].setdefault(law, {k: v for k, v in point.items() if k != "spec"})
    return len(points)


def contenders(repo, state: dict, ranked: list | None = None) -> list[str]:
    ranked = best(repo, state["study"]) if ranked is None else ranked
    wanted = ranked[:int(state["plan"]["depth"]["contenders"])]
    current = state.get("current") or {}
    if current.get("law") and all(e["candidate_id"] != current["law"] for e in wanted):
        wanted.append({"candidate_id": current["law"], "campaign": current["of"], "score": current.get("score")})
    added = []
    for entry in wanted:
        if entry["candidate_id"] in state["contenders"]:
            continue
        _insert(repo, state["campaigns"][DEPTH], _spec_of(repo, entry["campaign"], entry["candidate_id"]))
        state["contenders"][entry["candidate_id"]] = {"of": entry["campaign"], "score": entry.get("score"),
                                                      "label": label(repo, entry["campaign"], entry["candidate_id"]),
                                                      "joined_utc": utc_now()}
        added.append(entry["candidate_id"])
    return added


def alike_to(found_plan: dict, rows: dict | None) -> float | None:
    least = float(found_plan["neighbourhood"]["lines_from_radius"])
    out = None
    for radius, row in sorted((rows or {}).items(), key=lambda kv: float(kv[0])):
        if float(radius) < least - 1e-15:
            continue
        if row["other"] or row["waiting"]:
            break
        out = float(radius)
    return out


def inside(repo, state: dict, entry: dict) -> dict | None:
    from graph_scale_dynamics.research import neighbourhood as N
    read_n = int(state["plan"]["neighbourhood"]["read_n"])
    share = float(state["plan"]["next"]["inside_share"])
    kind, spec = None, None
    for done in state["done"]:
        if done.get("stage") != MAPPED or not done.get("alike_to"):
            continue
        if spec is None:
            spec = _spec_of(repo, entry["campaign"], entry["candidate_id"])
            kind = verdict(repo, entry["campaign"], entry["candidate_id"], read_n)
        if kind != done.get("kind"):
            continue
        far = N.distance(_spec_of(repo, done["of"], done["law"]), spec)
        if far is not None and far <= share * float(done["alike_to"]):
            return {"region_of": done.get("label"), "region": R.name_of(state, done["law"]),
                    "distance": round(far, 6), "alike_to": done["alike_to"]}
    return None


def type_of(repo, state: dict, campaign_id: str, law: str) -> str | None:
    from graph_scale_dynamics.observability import law_status, two_chains
    from graph_scale_dynamics.operations import study_map
    kept = state.setdefault("types", {})
    if law in kept:
        return kept[law]
    if not callable(getattr(repo, "measurements", None)):
        return None
    read_n = int(state["plan"]["neighbourhood"]["read_n"])
    rows, starts = _rows(repo, campaign_id, law)
    found = law_status.phenotype(two_chains.chains_per_rung(rows, starts), at_n=read_n)
    if study_map.decided(repo, campaign_id, law) and found.get("at_n") is not None:
        kept[law] = found.get("type")
    return found.get("type")


def known_types(state: dict, also=()) -> dict[str, int]:
    from graph_scale_dynamics.observability import law_status
    known: dict[str, int] = {}
    for entry in state.get("done") or []:
        if entry.get("stage") == MAPPED and entry.get("type"):
            known[entry["type"]] = known.get(entry["type"], 0) + 1
    for found in {t for t in also if t} | set((state.get("types") or {}).values()) | set(known):
        if law_status.known_from_the_table(found):
            known[found] = known.get(found, 0) + KNOWN_FROM_THE_TABLE
    return known


def _chosen(repo, state: dict, law: str | None, ranked: list | None = None) -> dict | None:
    ranked = best(repo, state["study"]) if ranked is None else ranked
    if not law:
        seen = ({entry["law"] for entry in state["done"]} | set(state.setdefault("inside", {}))
                | set(state.get("skipped") or {}))
        free = []
        for entry in ranked:
            if entry["candidate_id"] in seen:
                continue
            found = inside(repo, state, entry)
            if found is None:
                free.append(entry)
                continue
            state["inside"][entry["candidate_id"]] = dict(found, label=label(repo, entry["campaign"],
                                                                                entry["candidate_id"]))
        if not free:
            return None
        few = int(state["plan"]["next"].get("mapped_per_type", MAPPED_PER_TYPE))
        types = [type_of(repo, state, e["campaign"], e["candidate_id"]) for e in free]
        known = known_types(state, types)
        order = [(min(few, known.get(found or "", 0)), place) for place, found in enumerate(types)]
        return free[min(order)[1]]
    found = next((e for e in ranked if e["candidate_id"].startswith(str(law)) or e.get("label") == str(law)), None)
    if found is not None:
        return found
    for campaign_id in own_campaigns(repo, state["study"]):
        row = repo.conn.execute("SELECT candidate_id FROM campaign_candidates WHERE campaign_id=? AND candidate_id LIKE ?",
                                (campaign_id, f"{law}%")).fetchone()
        if row is not None:
            return {"candidate_id": str(row["candidate_id"]), "campaign": campaign_id, "score": 0}
    raise ValueError(f"study {state['study']} has no law {law!r}")


def start_next(repo, state: dict, law: str | None = None, chosen: dict | None = None,
               ranked: list | None = None) -> dict | None:
    chosen = chosen or _chosen(repo, state, law, ranked)
    if chosen is None:
        return None
    if state.get("next_plan"):
        state["plan"] = state.pop("next_plan")
        state["events"].append({"at": utc_now(), "settings": settings_of(state["plan"])})
    holder, campaign_id = chosen["candidate_id"], chosen["campaign"]
    spec = _spec_of(repo, campaign_id, holder)
    read_n = int(state["plan"]["neighbourhood"]["read_n"])
    radii = [[float(r), int(c)] for r, c in state["plan"]["neighbourhood"]["radii"]]
    current = {"law": holder, "of": campaign_id, "label": label(repo, campaign_id, holder),
               "score": chosen.get("score"), "kind": verdict(repo, campaign_id, holder, read_n),
               "stage": NEIGHBOURHOOD, "began_utc": utc_now(), "points": {}, "lines": {}, "radii": radii}
    state["current"] = current
    _insert(repo, state["campaigns"][SEEDS], spec)
    found, refused = neighbours(state, holder, spec, radii)
    current["refused"] = refused
    _add(repo, state, current, found)
    off, kept = knockouts(state, spec)
    current["terms_kept"] = kept
    _add(repo, state, current, off)
    contenders(repo, state, ranked)
    state["events"].append({"at": utc_now(), "began": current["label"], "points": len(current["points"])})
    return current


def begin(repo, study: str, *, law: str | None = None, tree=None) -> dict:
    from graph_scale_dynamics import PROJECT_ROOT
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.scheduling import work_groups
    tree = Path(tree) if tree is not None else Path(PROJECT_ROOT)
    state = load(repo)
    if state is not None and state.get("study") != str(study):
        raise ValueError(f"this folder's focus is on study {state['study']}")
    if state is None and law:
        _chosen(repo, {"study": str(study), "done": []}, law)
    if state is None:
        found_plan = plan(tree)
        anchor = next(iter(own_campaigns(repo, study)), None)
        if anchor is None:
            raise ValueError(f"this folder holds no campaign of study {study}")
        specs = campaign_specs(repo, study, anchor, found_plan, tree)
        state = {"contract": CONTRACT, "study": str(study), "plan": found_plan, "campaigns": {}, "contenders": {},
                 "complexity_budget": int(specs[NEIGHBOURS].get("complexity_budget") or 6),
                 "whitelist": specs[NEIGHBOURS].get("operator_whitelist"), "current": None, "done": [],
                 "seeds": int(specs[DEPTH]["default_seeds"]),
                 "events": [], "began_utc": utc_now()}
        for name in (NEIGHBOURS, SEEDS, DEPTH):
            made = control.create_campaign(repo, specs[name], search_seed=_seed(study, name),
                                           reason=f"study {study}'s focus: {name}")
            state["campaigns"][name] = str(made["campaign_id"])
        if not work_groups.shares(repo):
            work_groups.set_shares(repo, found_plan["groups"])
        save(repo, state)
    if state.get("stopped"):
        for campaign_id in state["campaigns"].values():
            control.resume(repo, campaign_id, reason="the focus started again")
        state["stopped"] = False
        state["events"].append({"at": utc_now(), "stopped": False})
    current = state.get("current")
    if law or current is None or current["stage"] in ENDED:
        chosen = _chosen(repo, state, law)
        if current is not None and current["stage"] not in ENDED:
            _end(state, current, UNCONFIRMED, "set aside for another law on the operator's word")
        if current is not None:
            _finish(repo, state, current)
        if chosen is not None:
            (state.get("skipped") or {}).pop(chosen["candidate_id"], None)
            start_next(repo, state, chosen=chosen)
    save(repo, state)
    return state


def expected(own: dict[int, str], n: int) -> str | None:
    from graph_scale_dynamics.observability import law_kind
    if not own:
        return None
    return own[max(own)] if int(n) > max(own) else law_kind.at(own, int(n))


def own_kinds(repo, state: dict, law: str, campaign_id: str) -> dict[int, str]:
    from graph_scale_dynamics.operations import study_map
    kept = state.setdefault("own_kinds", {})
    if law not in kept:
        found = kinds(repo, campaign_id, law)
        if not study_map.decided(repo, campaign_id, law):
            return found
        kept[law] = {str(n): k for n, k in sorted(found.items())}
    return {int(n): k for n, k in kept[law].items()}


def depth_of(repo, state: dict, law: str, campaign_id: str) -> dict:
    read_n = int(state["plan"]["neighbourhood"]["read_n"])
    found = kinds(repo, state["campaigns"][DEPTH], law, whole=int(state["seeds"]))
    own = own_kinds(repo, state, law, campaign_id)
    read = {n: k for n, k in sorted(found.items()) if n >= read_n}
    against = [n for n, k in read.items() if k != expected(own, n)]
    return {"kinds": {str(n): k for n, k in sorted(found.items())}, "deepest": max(found) if found else None,
            "own": {str(n): k for n, k in sorted(own.items())},
            "holds_to": max((n for n in read if n not in against), default=None),
            "invalidated_at": min(against) if against else None}


def seeds_of(repo, state: dict, current: dict) -> dict | None:
    from graph_scale_dynamics.observability import law_kind
    from graph_scale_dynamics.operations import study_map
    read_n = int(state["plan"]["neighbourhood"]["read_n"])
    campaign = state["campaigns"][SEEDS]
    if not study_map.decided(repo, campaign, current["law"]):
        return None
    own = {s: law_kind.at(k, read_n) for s, k in seed_kinds(repo, current["of"], current["law"]).items()}
    more = {s: law_kind.at(k, read_n) for s, k in seed_kinds(repo, campaign, current["law"]).items()}
    every = dict(own, **{s: k for s, k in more.items() if s not in own})
    return {"own": {str(s): k for s, k in sorted(own.items())}, "more": {str(s): k for s, k in sorted(more.items())},
            "reproduced": all(more.get(s) == k for s, k in own.items()),
            "other": sorted(s for s, k in every.items() if k != current["kind"]), "of": len(every)}


def tally(current: dict, verdicts: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for law, point in current["points"].items():
        if point["how"] != "neighbour":
            continue
        row = out.setdefault(f"{float(point['radius']):g}", {"laws": 0, "alike": 0, "other": 0, "waiting": 0})
        row["laws"] += 1
        seen = verdicts.get(law)
        row["waiting" if seen is None else "alike" if seen == current["kind"] else "other"] += 1
    return out


def sensitivity(found_plan: dict, rows: dict, seeds: dict | None) -> dict | None:
    tiny = float(found_plan["neighbourhood"]["tiny_to"])
    small = [row for radius, row in rows.items() if float(radius) <= tiny + 1e-15]
    if seeds is None or not small or any(row["waiting"] for row in small):
        return None
    moves, other = sum(row["laws"] for row in small), sum(row["other"] for row in small)
    if seeds["other"]:
        return {"on": ITS_SEEDS, "words": f"{len(seeds['other'])} of its {seeds['of']} seeds, each read alone, read "
                f"another kind; {other} of {moves} moves of {tiny:g} or less did too"}
    if other:
        return {"on": ITS_DIGITS, "words": f"its {seeds['of']} seeds, each read alone, agree, and {other} of {moves} "
                f"moves of {tiny:g} or less read another kind"}
    return {"on": ROBUST, "words": f"its {seeds['of']} seeds, each read alone, and all {moves} moves of {tiny:g} or "
            "less read its kind"}


def _lines_for(state: dict, current: dict, verdicts: dict) -> int:
    added = 0
    least = float(state["plan"]["neighbourhood"]["lines_from_radius"])
    for law, point in current["points"].items():
        if point["how"] != "neighbour" or float(point["radius"]) < least - 1e-15 or law in current["lines"]:
            continue
        seen = verdicts.get(law)
        if seen is not None and seen != current["kind"]:
            current["lines"][law] = {"lo": 0.0, "hi": 1.0, "lo_kind": current["kind"], "hi_kind": seen,
                                     "halvings": 0, "most": int(state["plan"]["boundaries"]["halvings"]), "points": {}}
            added += 1
    return added


def _advance_lines(repo, state: dict, current: dict, verdicts: dict) -> int:
    from graph_scale_dynamics.research import neighbourhood as N
    holder_spec = _spec_of(repo, current["of"], current["law"])
    added = 0
    for partner, line in current["lines"].items():
        while not line.get("done"):
            at = N.next_point(line)
            if at is None:
                line["done"] = True
                break
            law = line["points"].get(f"{at:g}")
            if law is None:
                child = N.between(holder_spec, _spec_of(repo, state["campaigns"][NEIGHBOURS], partner), at)
                problem = "no point between them" if child is None else N.valid(
                    child, complexity_budget=state["complexity_budget"], whitelist=state["whitelist"])
                if problem is not None:
                    line.update(done=True, why=problem)
                    break
                law = _insert(repo, state["campaigns"][NEIGHBOURS], child)
                line["points"][f"{at:g}"] = law
                current["points"].setdefault(law, {"how": "line", "partner": partner, "at": at})
                added += 1
                break
            seen = verdicts.get(law)
            if seen is None:
                break
            line.update(N.narrowed(line, at, seen))
    return added


def _summary(current: dict) -> dict:
    return {"law": current["law"], "of": current["of"], "label": current.get("label"), "score": current.get("score"),
            "stage": current["stage"], "kind": current.get("kind"), "why": current.get("why"),
            "radii": current.get("tally"), "seeds": current.get("seeds"), "sensitivity": current.get("sensitivity"),
            "alike_to": current.get("alike_to"),
            "depth": current.get("depth"), "refused": current.get("refused"),
            "boundaries": {p: {"between": [line["lo"], line["hi"]], "kinds": [line["lo_kind"], line["hi_kind"]],
                               "why": line.get("why")} for p, line in (current.get("lines") or {}).items()},
            "began_utc": current.get("began_utc"), "ended_utc": current.get("ended_utc"),
            "terms": current.get("terms"), "core": current.get("core"), "terms_kept": current.get("terms_kept")}


def _end(state: dict, current: dict, stage: str, why: str) -> None:
    current.update(stage=stage, ended_utc=utc_now(), why=why)
    state["events"].append({"at": utc_now(), "law": current["label"], "stage": stage, "why": why})


def _outward(repo, state: dict, current: dict) -> int:
    largest = max(float(r) for r, _c in current["radii"])
    outward = largest * float(state["plan"]["outward"]["factor"])
    if outward > float(state["plan"]["outward"]["most"]) + 1e-12:
        _end(state, current, MAPPED, f"every neighbour to radius {largest:g} reads its kind")
        return 0
    ring = [[outward, int(state["plan"]["outward"]["per_radius"])]]
    current["radii"] += ring
    found, refused = neighbours(state, current["law"], _spec_of(repo, current["of"], current["law"]), ring)
    current["refused"] = list(current.get("refused") or []) + refused
    if not found:
        _end(state, current, MAPPED, f"every neighbour to radius {largest:g} reads its kind; no valid law at {outward:g}")
    return _add(repo, state, current, found)


def advance(repo, state: dict) -> int:
    current = state["current"]
    p = state["plan"]["neighbourhood"]
    read_n = int(p["read_n"])
    verdicts = current.setdefault("read", {})
    for law in current["points"]:
        if law not in verdicts:
            seen = verdict(repo, state["campaigns"][NEIGHBOURS], law, read_n)
            if seen is not None:
                verdicts[law] = seen
    current["tally"] = tally(current, verdicts)
    current["terms"] = terms_read(current, verdicts)
    current["core"] = core_of(current["terms"])
    current["depth"] = depth_of(repo, state, current["law"], current["of"])
    if current.get("seeds") is None:
        current["seeds"] = seeds_of(repo, state, current)
    current["sensitivity"] = sensitivity(state["plan"], current["tally"], current["seeds"])
    current["alike_to"] = alike_to(state["plan"], current["tally"])
    if current["depth"]["invalidated_at"] is not None:
        at = int(current["depth"]["invalidated_at"])
        _end(state, current, INVALIDATED, f"at N={at:,} its run in the depth campaign read "
             f"{current['depth']['kinds'][str(at)]!r} where its own campaign reads "
             f"{expected({int(n): k for n, k in current['depth']['own'].items()}, at)!r}")
        return 0
    if current["stage"] == NEIGHBOURHOOD:
        first = current["tally"].get(f"{float(p['confirm_radius']):g}") or {}
        if not first or first["waiting"]:
            return 0
        if first["alike"] / max(1, first["laws"]) < float(p["confirm_share"]):
            _end(state, current, UNCONFIRMED, f"{first['alike']} of {first['laws']} neighbours at radius "
                 f"{float(p['confirm_radius']):g} read its kind at {read_n:,}")
            return 0
        if current["depth"]["holds_to"] is None or current["seeds"] is None \
                or any(row["waiting"] for row in current["tally"].values()) \
                or any(row["load_bearing"] is None for row in current["terms"].values()):
            return 0
        if not _lines_for(state, current, verdicts):
            return _outward(repo, state, current)
        current["stage"] = BOUNDARIES
        state["events"].append({"at": utc_now(), "law": current["label"], "stage": BOUNDARIES,
                                "lines": len(current["lines"])})
    added = _advance_lines(repo, state, current, verdicts)
    if all(line.get("done") for line in current["lines"].values()):
        _end(state, current, MAPPED, f"{len(current['lines'])} boundaries, each halved where the kind flips")
    return added


def members(repo, state: dict, current: dict) -> list[dict]:
    seen = current.get("read") or {}
    specs = [_spec_of(repo, current["of"], current["law"])]
    for law, point in current["points"].items():
        if seen.get(law) == current["kind"] and point["how"] in ("neighbour", "line", KNOCKOUT):
            specs.append(_spec_of(repo, state["campaigns"][NEIGHBOURS], law))
    return [spec for spec in specs if spec]


def _finish(repo, state: dict, current: dict) -> None:
    summary = _summary(current)
    summary["type"] = type_of(repo, state, current["of"], current["law"])
    if current["stage"] == MAPPED:
        region = R.place(state, summary, members(repo, state, current))
        summary["region"] = region["name"]
        if summary.get("core") is not None:
            region.setdefault("cores", {})[str(summary.get("label") or summary["law"])] = summary["core"]
        state["events"].append({"at": utc_now(), "law": current["label"], "region": region["name"]})
    state["done"].append(summary)
    state["current"] = None


def place_of(state: dict | None, law: str) -> dict | None:
    if not state:
        return None
    if (state.get("current") or {}).get("law") == law:
        return {"region": None, "how": "in focus now"}
    region = R.name_of(state, law)
    if region:
        return {"region": region, "how": "mapped"}
    inside_of = (state.get("inside") or {}).get(law)
    if inside_of:
        return {"region": inside_of.get("region") or inside_of.get("region_of"), "how": "inside, passed over"}
    ended = next((entry for entry in state.get("done") or [] if entry.get("law") == law), None)
    if ended:
        return {"region": None, "how": str(ended.get("stage"))}
    return None


def queue_of(state: dict, ranked: list[dict]) -> list[dict]:
    current = (state.get("current") or {}).get("law")
    ended = {entry["law"]: entry for entry in state["done"]}
    inside_of, skipped = state.get("inside") or {}, state.get("skipped") or {}
    out = []
    for entry in ranked[:QUEUE_LENGTH]:
        law = entry["candidate_id"]
        if law == current:
            status = "in focus"
        elif law in skipped:
            status = "skipped"
        elif law in ended:
            status = ended[law]["stage"]
        elif law in inside_of:
            status = "inside " + str(inside_of[law].get("region") or inside_of[law].get("region_of"))
        else:
            status = "waiting"
        out.append({"law": law, "campaign": entry["campaign"], "label": entry.get("label"), "score": entry["score"],
                    "status": status, "region": R.name_of(state, law), "type": (state.get("types") or {}).get(law)})
    return out


def _loaded(repo) -> dict:
    state = load(repo)
    if state is None:
        raise ValueError("this folder has no focus yet: start one first")
    return state


def resolve(state: dict, given: str) -> str:
    given = str(given or "").strip()
    if not given:
        raise ValueError("name a law by its id, the start of its id, or its label (C1-G6940)")
    known: dict[str, str | None] = {}
    for entry in state.get("queue") or []:
        known[entry["law"]] = entry.get("label")
    for entry in state["done"]:
        known.setdefault(entry["law"], entry.get("label"))
    for law, entry in list((state.get("skipped") or {}).items()) + list((state.get("inside") or {}).items()):
        known.setdefault(law, entry.get("label"))
    if state.get("current"):
        known[state["current"]["law"]] = state["current"].get("label")
    found = sorted(law for law, name in known.items() if law.startswith(given) or name == given)
    if len(found) != 1:
        raise ValueError(f"{given!r} names {len(found)} of the focus's laws; give more of its id")
    return found[0]


def skip(repo, given: str) -> dict:
    state = _loaded(repo)
    law = resolve(state, given)
    current = state.get("current")
    state.setdefault("skipped", {})[law] = {"at": utc_now(), "label": next(
        (e.get("label") for e in (state.get("queue") or []) if e["law"] == law), (current or {}).get("label"))}
    if current is not None and current["law"] == law and current["stage"] not in ENDED:
        _end(state, current, UNCONFIRMED, "skipped on the operator's word")
        _finish(repo, state, current)
    state["events"].append({"at": utc_now(), "skipped": state["skipped"][law].get("label") or law})
    save(repo, state)
    return state


def back(repo, given: str) -> dict:
    state = _loaded(repo)
    law = resolve(state, given)
    (state.get("skipped") or {}).pop(law, None)
    (state.get("inside") or {}).pop(law, None)
    state["done"] = [entry for entry in state["done"] if entry["law"] != law]
    state["events"].append({"at": utc_now(), "back": law})
    save(repo, state)
    return state


def stop(repo) -> dict:
    from graph_scale_dynamics.operations import campaign_control as control
    state = _loaded(repo)
    for campaign_id in state["campaigns"].values():
        control.pause(repo, campaign_id, reason="the focus stopped")
    state["stopped"] = True
    state["events"].append({"at": utc_now(), "stopped": True})
    save(repo, state)
    return state


def settings_of(found_plan: dict) -> dict:
    return {"radii": [[float(r), int(c)] for r, c in found_plan["neighbourhood"]["radii"]],
            "confirm_radius": float(found_plan["neighbourhood"]["confirm_radius"]),
            "confirm_share": float(found_plan["neighbourhood"]["confirm_share"]),
            "contenders": int(found_plan["depth"]["contenders"]),
            "outward_most": float(found_plan["outward"]["most"]),
            "inside_share": float(found_plan["next"]["inside_share"]),
            "mapped_per_type": int(found_plan["next"].get("mapped_per_type", MAPPED_PER_TYPE))}


def _bounded(value, low: float, high: float, what: str) -> float:
    try:
        found = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number") from None
    if not low <= found <= high:
        raise ValueError(f"{what} must lie between {low:g} and {high:g}")
    return found


def settled(found_plan: dict, given: dict) -> dict:
    out = deepcopy(found_plan)
    if "radii" in given:
        rings = given["radii"]
        if not isinstance(rings, list) or not 1 <= len(rings) <= 12:
            raise ValueError("give 1 to 12 rings, each [radius, laws]")
        radii = []
        for ring in rings:
            if not isinstance(ring, (list, tuple)) or len(ring) != 2:
                raise ValueError("each ring is [radius, laws]")
            radius = _bounded(ring[0], 1e-12, 0.8, "a ring's radius")
            count = int(_bounded(ring[1], 1, 32, "a ring's laws"))
            radii.append([radius, count])
        if sum(count for _r, count in radii) > 200:
            raise ValueError("at most 200 neighbours a law")
        confirm = float(out["neighbourhood"]["confirm_radius"])
        if not any(abs(radius - confirm) < 1e-12 for radius, _c in radii):
            raise ValueError(f"keep the ring at {confirm:g}: it confirms a law's neighbourhood")
        out["neighbourhood"]["radii"] = sorted(radii)
    if "confirm_share" in given:
        out["neighbourhood"]["confirm_share"] = _bounded(given["confirm_share"], 0.5, 1.0, "the share to confirm")
    if "contenders" in given:
        out["depth"]["contenders"] = int(_bounded(given["contenders"], 0, 20, "the contenders"))
    if "outward_most" in given:
        out["outward"]["most"] = _bounded(given["outward_most"], 0.1, 0.95, "the widest ring")
    if "inside_share" in given:
        out["next"]["inside_share"] = _bounded(given["inside_share"], 0.0, 1.0, "the share of a region's reach")
    if "mapped_per_type" in given:
        out["next"]["mapped_per_type"] = int(_bounded(given["mapped_per_type"], 1, 50, "the laws a type is mapped by"))
    unknown = sorted(set(given) - {"radii", "confirm_share", "contenders", "outward_most", "inside_share",
                                   "mapped_per_type"})
    if unknown:
        raise ValueError(f"no such setting: {', '.join(unknown)}")
    return out


def set_next(repo, given: dict) -> dict:
    state = _loaded(repo)
    if not isinstance(given, dict) or not given:
        raise ValueError("send the settings to change")
    state["next_plan"] = settled(state.get("next_plan") or state["plan"], given)
    state["events"].append({"at": utc_now(), "next_settings": settings_of(state["next_plan"])})
    save(repo, state)
    return state


def studies(repo) -> list[dict]:
    found: dict[str, int] = {}
    for campaign in repo.all_campaigns():
        design = (campaign.get("spec") or {}).get("study_design") or {}
        if design.get("study") is not None and design.get("kind") != KIND:
            found[str(design["study"])] = found.get(str(design["study"]), 0) + 1
    return [{"study": study, "campaigns": count} for study, count in sorted(found.items())]


def act(repo, body: dict, *, tree=None) -> dict:
    from graph_scale_dynamics.scheduling import work_groups
    do = str((body or {}).get("do") or "")
    if do not in DOS:
        raise ValueError(f"do must be one of {', '.join(DOS)}")
    if do == "start":
        study = str(body.get("study") or "")
        if not study:
            found = studies(repo)
            if len(found) != 1:
                raise ValueError(f"this folder holds {len(found)} studies: name one")
            study = found[0]["study"]
        begin(repo, study, tree=tree)
    elif do == "law":
        state = _loaded(repo)
        begin(repo, state["study"], law=resolve_any(state, str(body.get("law") or "")), tree=tree)
    elif do == "skip":
        skip(repo, str(body.get("law") or ""))
    elif do == "back":
        back(repo, str(body.get("law") or ""))
    elif do == "stop":
        stop(repo)
    elif do == "settings":
        set_next(repo, body.get("settings"))
    elif do == "seed":
        from graph_scale_dynamics.operations import study_seed
        return {"ok": True, "did": do, "seeded": study_seed.seed(repo, str(body.get("bundle") or ""))}
    elif do == "run_on":
        from graph_scale_dynamics.operations import run_on
        if body.get("clear"):
            return {"ok": True, "did": do, "run_on": run_on.clear(repo)}
        study = str(body.get("study") or ((load(repo) or {}).get("study")) or "")
        if not study:
            found = studies(repo)
            if len(found) != 1:
                raise ValueError(f"this folder holds {len(found)} studies: name one")
            study = found[0]["study"]
        return {"ok": True, "did": do, "run_on": run_on.name(repo, study, tree=tree)}
    else:
        work_groups.set_shares(repo, work_groups.split_of(str(body.get("split") or "")))
    return {"ok": True, "did": do}


def resolve_any(state: dict, given: str) -> str:
    try:
        return resolve(state, given)
    except ValueError:
        if not given.strip():
            raise
        return given.strip()


def step(repo, *, now: float | None = None, force: bool = False) -> dict | None:
    state = load(repo)
    if state is None or state.get("stopped"):
        return None
    clock = time.monotonic() if now is None else float(now)
    if not force and clock - _LAST.get(state["study"], -1e18) < INTERVAL_SECONDS:
        return None
    _LAST[state["study"]] = clock
    ranked = best(repo, state["study"])
    added = len(contenders(repo, state, ranked))
    state["depths"] = {law: dict(depth_of(repo, state, law, entry["of"]), label=entry["label"])
                       for law, entry in state["contenders"].items()}
    current = state.get("current")
    if current is not None and current["stage"] not in ENDED:
        added += advance(repo, state)
    if current is not None and current["stage"] in ENDED:
        _finish(repo, state, current)
        current = start_next(repo, state, ranked=ranked)
        added += len(current["points"]) if current else 0
    elif current is None:
        current = start_next(repo, state, ranked=ranked)
        added += len(current["points"]) if current else 0
    state["queue"] = queue_of(state, ranked)
    state["events"] = state["events"][-200:]
    save(repo, state)
    return {"stage": (current or {}).get("stage"), "added": added, "label": (current or {}).get("label")}


def reading(repo) -> dict | None:
    state = load(repo)
    return None if state is None else reading_of(state)


def reading_of(state: dict) -> dict:
    current = state.get("current")
    return {"contract": CONTRACT, "study": state["study"], "campaigns": state["campaigns"],
            "current": _summary(current) if current else None,
            "points": len((current or {}).get("points") or {}), "lines": len((current or {}).get("lines") or {}),
            "contenders": state.get("depths") or {law: dict(e) for law, e in state["contenders"].items()},
            "done": state["done"], "inside": state.get("inside") or {}, "stopped": bool(state.get("stopped")),
            "skipped": state.get("skipped") or {}, "queue": state.get("queue") or [],
            "regions": state.get("regions") or [], "touching": R.touching(state.get("regions") or []),
            "seeded": state.get("seeded") or [],
            "settings": settings_of(state["plan"]),
            "next_settings": settings_of(state["next_plan"]) if state.get("next_plan") else None,
            "events": (state.get("events") or [])[-30:]}


def words(found: dict | None) -> str:
    if not found:
        return "no focus in this folder"
    current = found.get("current")
    c = found["campaigns"]
    lines = [f"study {found['study']}'s focus: neighbours in campaign {c[NEIGHBOURS]} and more seeds in {c[SEEDS]} "
             f"(group N), the depth in {c[DEPTH]} (group D)"]
    if current:
        lines.append(f"  {current['label']} (score {current['score']}), its kind at the read: {current['kind']}: "
                     f"{current['stage']}" + (f" ({current['why']})" if current.get("why") else "")
                     + f"; {found['points']} laws, {found['lines']} boundary lines")
        for radius, row in sorted((current.get("radii") or {}).items(), key=lambda kv: float(kv[0])):
            lines.append(f"    radius {radius}: {row['alike']} alike, {row['other']} other, {row['waiting']} waiting "
                         f"of {row['laws']}")
        sensitive = current.get("sensitivity")
        lines.append(f"    sensitive to: {sensitive['on']} ({sensitive['words']})" if sensitive
                     else "    sensitive to: not read yet (its seeds and the moves of 1e-3 or less)")
    else:
        lines.append("  no law is in focus now")
    for entry in (found.get("contenders") or {}).values():
        lines.append(f"  depth of {entry.get('label')}: deepest {entry.get('deepest')}, holds to "
                     f"{entry.get('holds_to')}, invalidated at {entry.get('invalidated_at')}")
    for law, entry in (found.get("inside") or {}).items():
        lines.append(f"  passed over: {entry.get('label')}, inside the region of {entry.get('region_of')} "
                     f"(distance {entry.get('distance')}, its neighbours alike to {entry.get('alike_to')})")
    if found.get("stopped"):
        lines.insert(1, "  stopped: its three campaigns are paused; the blind draw goes on")
    for region in found.get("regions") or []:
        spans = "; ".join(f"{axis} {lo:.4g} to {hi:.4g}" for axis, (lo, hi) in region["ranges"].items() if lo != hi)
        lines.append(f"  {region['name']} ({region['kind']}): from {', '.join(map(str, region['labels']))}, "
                     f"{region['members']} laws read its kind" + (f"; {spans}" if spans else ""))
    for entry in found.get("done") or []:
        sensitive = entry.get("sensitivity") or {}
        lines.append(f"  done: {entry.get('label')}: {entry.get('stage')} ({entry.get('why')})"
                     + (f"; sensitive to {sensitive['on']}" if sensitive else ""))
    return "\n".join(lines)


def command(repo, study: str, law: str | None, show: bool) -> tuple[int, str]:
    try:
        if not show:
            begin(repo, str(study), law=law)
    except ValueError as exc:
        return 2, f"refused: {exc}"
    return 0, words(reading(repo))
