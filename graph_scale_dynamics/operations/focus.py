from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from pathlib import Path

from graph_scale_dynamics.domain.model import utc_now
from graph_scale_dynamics.operations import focus_regions as R
from graph_scale_dynamics.operations import law_code as LC

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
DOS = ("start", "law", "skip", "back", "stop", "settings", "split", "run_on", "seed", "lean", "order", "push", "unpush",
       "push_move")
QUEUE_LENGTH = 100
FOCUS_LIST, DEPTH_LIST = "focus", "depth"
LIST_SHOWN = 10
DEPTH_WORKERS = 1
DEFAULT_WORKERS = 16
FIRST_LEAN = 0.5
TYPE_WORDS = "law-type-2"
KNOCKOUT = "term off"
MAPPED_PER_TYPE = 3
KNOWN_FROM_THE_TABLE = 1
INTERVAL_SECONDS = 60.0
FAILED_FLAG = "study_focus_failed"
TYPICAL_EVERY_SECONDS = 300.0
BEHIND = 10_000_000_000
BY_SCORE, BY_BUNDLE, BY_OUTLIER, BY_OPERATOR, BY_ZONE = "score", "bundle", "outlier", "operator", "zone"
OWN_CAMPAIGN, SEEDS_CAMPAIGN = "its own campaign", "its seeds' campaign"
SET_ASIDE_WHY = "an outlier set aside: a scoring law waits, and outliers come only once every scoring law is mapped"
_LAST: dict[str, float] = {}


def plan(tree=None) -> dict:
    from graph_scale_dynamics.resources import committed
    return json.loads(committed.resolve(PLAN, tree).read_text(encoding="utf-8"))


def load(repo) -> dict | None:
    try:
        state = json.loads(repo.get_flag(FLAG, "") or "null")
    except (TypeError, ValueError):
        return None
    return coded(state) if isinstance(state, dict) and state.get("contract") == CONTRACT else None


def coded(state: dict) -> dict:
    study = state.get("study")

    def put(entry) -> None:
        if isinstance(entry, dict) and entry.get("label") is not None:
            entry["label"] = LC.upgraded(entry["label"], study)

    put(state.get("current"))
    put(state.get("depth_now"))
    for name in ("contenders", "depths", "inside", "skipped", "depth_done", "set_aside"):
        for entry in (state.get(name) or {}).values():
            put(entry)
    for entry in list(state.get("done") or []) + list(state.get("queue") or []):
        put(entry)
    for rows in (state.get("lists") or {}).values():
        for entry in rows or []:
            put(entry)
    for region in list(state.get("regions") or []) + list(state.get("regions_let_go") or []):
        if not region.get("seeded_from") and "labels" in region:
            region["labels"] = [LC.upgraded(label, study) for label in region["labels"] or []]
        if not region.get("seeded_from") and "cores" in region:
            region["cores"] = {LC.upgraded(k, study): v for k, v in (region["cores"] or {}).items()}
    return state


def save(repo, state: dict) -> None:
    repo.set_flag(FLAG, json.dumps(state, sort_keys=True, separators=(",", ":")))


def graph_number(repo, campaign_id: str, law: str) -> int | None:
    row = repo.conn.execute(
        "SELECT MIN(graph_ordinal) AS g FROM jobs WHERE campaign_id=? AND candidate_id=? AND kind='simulate' "
        "AND graph_ordinal IS NOT NULL", (str(campaign_id), str(law))).fetchone()
    return None if row is None or row["g"] is None else int(row["g"])


def label(repo, campaign_id: str, law: str, known: dict | None = None) -> str:
    return LC.code(LC.study_of(repo, campaign_id, known), campaign_id, graph_number(repo, campaign_id, law), law)


HOME_ORDER = {"blind": 0, "seed": 1, "map": 2, "perturb": 2, NEIGHBOURS: 3, SEEDS: 4, DEPTH: 5}


def home_campaign(repo, campaigns) -> str | None:
    def rank(campaign_id: str):
        spec = (repo.campaign(str(campaign_id)) or {}).get("spec") or {}
        design = spec.get("study_design") or {}
        part = (design.get("focus") or {}).get("part") if design.get("kind") == KIND else design.get("kind")
        controls = str(spec.get("name") or "") == "campaign-standing-controls"
        return (9 if controls else HOME_ORDER.get(part, 6), _number(campaign_id), str(campaign_id))
    found = sorted((str(c) for c in campaigns or []), key=rank)
    return found[0] if found else None


def own_campaigns(repo, study: str) -> list[str]:
    out = []
    for campaign in repo.all_campaigns():
        design = (campaign.get("spec") or {}).get("study_design") or {}
        if str(design.get("study")) == str(study) and design.get("kind") != KIND:
            out.append(str(campaign["campaign_id"]))
    return out


def _number(text) -> float:
    return float(text) if str(text).isdigit() else float("inf")


def read_here(repo, campaign_id: str, read_n: int) -> set[str]:
    return {str(row["candidate_id"]) for row in repo.conn.execute(
        "SELECT candidate_id FROM engine_decisions_latest WHERE campaign_id=? AND at_n>=?",
        (str(campaign_id), int(read_n))).fetchall()}


def best(repo, study: str, state: dict | None = None) -> list[dict]:
    from graph_scale_dynamics.observability import score_board
    from graph_scale_dynamics.operations import study_seed
    if state is None and callable(getattr(repo, "get_flag", None)):
        state = load(repo)
    standing, gone = study_seed.standing(state), study_seed.let_go(state)
    seeded_in = study_seed.campaign_of(state)
    found = []
    for campaign_id in own_campaigns(repo, study):
        for law, score in (score_board.board(repo, campaign_id).get("scores") or {}).items():
            if int(score.get("score") or 0) <= 0 or (campaign_id == seeded_in and str(law) in gone):
                continue
            entry = {"candidate_id": str(law), "campaign": campaign_id, "score": int(score["score"])}
            if campaign_id == seeded_in and str(law) in standing:
                entry["origin"] = standing[str(law)]
            found.append(entry)
    if standing and seeded_in is not None:
        here = {e["candidate_id"] for e in found if e["campaign"] == seeded_in}
        read_n = int(((state or {}).get("plan") or plan())["neighbourhood"]["read_n"])
        read = read_here(repo, seeded_in, read_n)
        for law, origin in standing.items():
            if law not in here and law not in read and law not in gone:
                found.append({"candidate_id": law, "campaign": seeded_in, "score": int(origin.get("score") or 0),
                              "origin": origin, "standing": "bundle"})
    known: dict = {}
    for entry in found:
        entry["graph"] = graph_number(repo, entry["campaign"], entry["candidate_id"])
        entry["label"] = LC.code(LC.study_of(repo, entry["campaign"], known), entry["campaign"], entry["graph"],
                                 entry["candidate_id"])
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


def kinds_so_far(repo, campaign_id: str, law: str, seeds: int) -> dict[str, str]:
    return {str(n): k for n, k in sorted(kinds(repo, campaign_id, law, whole=int(seeds)).items())}


def seed_kinds(repo, campaign_id: str, law: str) -> dict[int, dict[int, str]]:
    rows, starts = _rows(repo, campaign_id, law)
    return {seed: _kinds_of([r for r in rows if int(r["seed"]) == seed], starts)
            for seed in sorted({int(row["seed"]) for row in rows})}


def decided_past(repo, campaign_id: str, law: str, read_n: int) -> bool:
    row = repo.conn.execute("SELECT at_n FROM engine_decisions_latest WHERE campaign_id=? AND candidate_id=?",
                            (str(campaign_id), str(law))).fetchone()
    return row is not None and row["at_n"] is not None and int(row["at_n"]) >= int(read_n)


def verdict(repo, campaign_id: str, law: str, read_n: int) -> str | None:
    from graph_scale_dynamics.operations import study_map
    finished = study_map.decided(repo, campaign_id, law)
    if not finished and not decided_past(repo, campaign_id, law, read_n):
        return None
    found = kinds(repo, campaign_id, law)
    if int(read_n) in found:
        return found[int(read_n)]
    if not finished:
        return None
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
    around = SD.campaign_spec(design, base, SD.entry_of(design, index), index)
    read_n = int(found_plan["neighbourhood"]["read_n"])
    seeds = int(design["ladder"]["seeds"])
    upto = [int(n) for n in design["ladder"]["deep"] if int(n) <= read_n]
    wanted = depth_wanted(found_plan)
    shapes = {NEIGHBOURS: (upto, seeds, "its best laws' neighbourhoods"),
              SEEDS: (upto, seeds * int(found_plan["seeds"]["times"]), "its best laws on more seeds"),
              DEPTH: ([int(n) for n in design["ladder"]["deep"]] + [int(n) for n in found_plan["depth"]["beyond"]],
                      wanted["seeds"] or seeds, "its best laws' depth")}
    out = {}
    for name, (deep, count, words) in shapes.items():
        spec = deepcopy(around)
        spec["proposer"] = {"pool_min": 1}
        spec["search_policy"] = {"contract": "gsd-hand-1", "kind": "hand"}
        part = {"contract": CONTRACT, "plan": PLAN, "part": name}
        if name == DEPTH and wanted["memory_share"]:
            part["memory_share"] = wanted["memory_share"]
        spec["study_design"] = dict(spec["study_design"], kind=KIND, group=GROUP_OF[name], campaign=None,
                                    focus=part)
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


def early_call(repo, state: dict, current: dict, verdicts: dict) -> dict | None:
    from graph_scale_dynamics.observability import law_kind
    at_n = current.get("identified_from")
    read_n = int(state["plan"]["neighbourhood"]["read_n"])
    if at_n is None or int(at_n) >= read_n:
        return None
    early = current.setdefault("early", {})
    for law, point in current["points"].items():
        if law in early or point.get("how") != "neighbour" or verdicts.get(law) is None:
            continue
        early[law] = law_kind.at(kinds(repo, state["campaigns"][NEIGHBOURS], law), int(at_n))
    read = [law for law in early if verdicts.get(law) is not None]
    return {"at_n": int(at_n), "of": len(read), "agreed": sum(1 for law in read if early[law] == verdicts[law])}


def terms_read(current: dict, verdicts: dict) -> dict[str, dict]:
    out = {}
    for law, point in current["points"].items():
        if point.get("how") != KNOCKOUT:
            continue
        seen = verdicts.get(law)
        out[point["term"]] = {"law": law, "kind": seen,
                              "load_bearing": None if seen is None or current.get("kind") is None
                              else seen != current["kind"]}
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
    from graph_scale_dynamics.operations import study_seed
    ranked = best(repo, state["study"]) if ranked is None else ranked
    gone, seeded_in = study_seed.let_go(state), study_seed.campaign_of(state)
    for law in [law for law, e in state["contenders"].items() if law in gone and str(e.get("of")) == str(seeded_in)]:
        state["contenders"].pop(law)
    from graph_scale_dynamics.operations import push
    current = state.get("current") or {}
    scoring = {e["candidate_id"] for e in ranked} | set(push.laws(state)) | set(push.central(state))
    for entry in push.entries(state):
        state["contenders"].setdefault(entry["law"], {"of": entry["of"], "label": entry.get("label"),
                                                      "joined_utc": entry.get("since") or utc_now(), "pushed": True})
    for law in [law for law in state["contenders"] if law not in scoring and law != current.get("law")]:
        state["contenders"].pop(law)
        state["events"].append({"at": utc_now(), "depth_dropped": law[:12], "why": "it no longer scores and is not in focus"})
    wanted = depth_order(state, ranked)[:int(state["plan"]["depth"]["contenders"])]
    if current.get("law") and all(e["candidate_id"] != current["law"] for e in wanted):
        wanted.append({"candidate_id": current["law"], "campaign": current["of"], "score": current.get("score")})
    added = []
    for entry in wanted:
        if entry["candidate_id"] in state["contenders"]:
            continue
        state["contenders"][entry["candidate_id"]] = {"of": entry["campaign"], "score": entry.get("score"),
                                                      "label": label(repo, entry["campaign"], entry["candidate_id"]),
                                                      "joined_utc": utc_now(),
                                                      **({"origin": entry["origin"]} if entry.get("origin") else {})}
        added.append(entry["candidate_id"])
    return added


def confirmed_at(found_plan: dict, rows: dict | None):
    p = found_plan["neighbourhood"]
    least, most = float(p["lines_from_radius"]), float(p["confirm_radius"])
    for radius, row in sorted((rows or {}).items(), key=lambda kv: -float(kv[0])):
        if not least - 1e-15 <= float(radius) < most - 1e-15:
            continue
        if row["waiting"]:
            return None
        if row["alike"] / max(1, row["laws"]) >= float(p["confirm_share"]):
            return float(radius)
    return False


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
    from graph_scale_dynamics.operations import study_seed
    kind, spec, off = None, None, study_seed.bundles_let_go(state)
    for done in state["done"]:
        reach = done.get("alike_to") or done.get("confirmed_at")
        if done.get("stage") != MAPPED or not reach or done.get("seeded") in off:
            continue
        if spec is None:
            spec = _spec_of(repo, entry["campaign"], entry["candidate_id"])
            kind = verdict(repo, entry["campaign"], entry["candidate_id"], read_n)
        if kind != done.get("kind"):
            continue
        far = N.distance(_spec_of(repo, done["of"], done["law"]), spec)
        if far is not None and far <= share * float(reach):
            return {"region_of": done.get("label"), "region": R.name_of(state, done["law"]),
                    "distance": round(far, 6), "alike_to": reach}
    return None


def type_of(repo, state: dict, campaign_id: str, law: str) -> str | None:
    from graph_scale_dynamics.observability import law_status, two_chains
    from graph_scale_dynamics.operations import study_map
    if state.get("types_by") != TYPE_WORDS:
        state["types"], state["types_by"] = {}, TYPE_WORDS
    kept = state.setdefault("types", {})
    if law in kept:
        return kept[law]
    if not callable(getattr(repo, "measurements", None)):
        return None
    read_n = int(state["plan"]["neighbourhood"]["read_n"])
    rows, starts = _rows(repo, campaign_id, law)
    chains = two_chains.chains_per_rung(rows, starts)
    found = law_status.phenotype(chains, at_n=read_n)
    if study_map.decided(repo, campaign_id, law) and found.get("at_n") is not None:
        kept[law] = found.get("type")
        state.setdefault("identified", {})[law] = identified_from(_kinds_of(rows, starts))
    return found.get("type")


def identified_from(found: dict[int, str]) -> int | None:
    if not found:
        return None
    sizes = sorted(int(n) for n in found)
    last = found[sizes[-1]]
    earliest = sizes[-1]
    for n in reversed(sizes):
        if found[n] != last:
            break
        earliest = n
    return earliest


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


def suggested(repo, state: dict, free: list[dict]) -> list[dict]:
    if not free:
        return []
    few = int(state["plan"]["next"].get("mapped_per_type", MAPPED_PER_TYPE))
    types = [type_of(repo, state, e["campaign"], e["candidate_id"]) for e in free]
    known = known_types(state, types)
    hand = {law: place for place, law in enumerate((state.get("order") or {}).get(FOCUS_LIST) or [])}
    keyed = sorted(range(len(free)), key=lambda i: (hand.get(free[i]["candidate_id"], len(hand)),
                                                    min(few, known.get(types[i] or "", 0)), i))
    return [free[i] for i in keyed]


def free_laws(repo, state: dict, ranked: list[dict]) -> list[dict]:
    seen = ({entry["law"] for entry in state["done"]} | set(state.get("inside") or {})
            | set(state.get("skipped") or {}) | {(state.get("current") or {}).get("law")})
    return [entry for entry in ranked if entry["candidate_id"] not in seen]


def depth_order(state: dict, ranked: list[dict]) -> list[dict]:
    hand = {law: place for place, law in enumerate((state.get("order") or {}).get(DEPTH_LIST) or [])}
    return [ranked[i] for i in sorted(range(len(ranked)),
                                      key=lambda i: (hand.get(ranked[i]["candidate_id"], len(hand)), i))]


def lists_of(repo, state: dict, ranked: list[dict]) -> dict[str, list[dict]]:
    def row(entry: dict) -> dict:
        law = entry["candidate_id"]
        return {"law": law, "campaign": entry["campaign"], "label": entry.get("label"), "score": entry.get("score"),
                "type": (state.get("types") or {}).get(law),
                "identified_from": (state.get("identified") or {}).get(law),
                "placed": law in ((state.get("order") or {}).get(FOCUS_LIST) or [])
                or law in ((state.get("order") or {}).get(DEPTH_LIST) or []),
                "in_depth": law in state.get("contenders", {}),
                **({"origin": entry["origin"]} if entry.get("origin") else {}),
                **({"standing": entry["standing"]} if entry.get("standing") else {})}
    return {FOCUS_LIST: [row(e) for e in suggested(repo, state, free_laws(repo, state, ranked))[:LIST_SHOWN]],
            DEPTH_LIST: [row(e) for e in depth_order(state, ranked)[:LIST_SHOWN]]}


def reorder(repo, which: str, given: str, move: str) -> dict:
    state = _loaded(repo)
    if which not in (FOCUS_LIST, DEPTH_LIST):
        raise ValueError(f"the list is {FOCUS_LIST} or {DEPTH_LIST}")
    orders = state.setdefault("order", {})
    if move == "reset":
        orders.pop(which, None)
        state["events"].append({"at": utc_now(), "order": which, "reset": True})
        save(repo, state)
        return state
    shown = [entry["law"] for entry in (state.get("lists") or {}).get(which) or []]
    law = next((x for x in shown if x.startswith(str(given or "").strip()) and given), None)
    if law is None:
        raise ValueError(f"{given!r} is not on the {which} list as the page last read it")
    order = list(orders.get(which) or [])
    order += [x for x in shown if x not in order]
    place = order.index(law)
    if move not in ("up", "down", "top"):
        raise ValueError("move is up, down, top or reset")
    order.pop(place)
    order.insert(0 if move == "top" else max(0, place - 1) if move == "up" else min(len(order), place + 1), law)
    orders[which] = order
    state["events"].append({"at": utc_now(), "order": which, "law": law, "move": move})
    save(repo, state)
    return state


def _lean(repo, state: dict, share) -> None:
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.scheduling import work_groups, worker_count
    focus_share = _bounded(share, 0.0, 1.0, "the focus's share")
    state["lean"] = {"focus": focus_share, "at": utc_now()}
    state["events"].append({"at": utc_now(), "lean": focus_share})
    if focus_share <= 0.0:
        for campaign_id in state["campaigns"].values():
            control.pause(repo, campaign_id, reason="the focus slid to the blind draw")
        state["stopped"] = True
        work_groups.set_shares(repo, {work_groups.BLIND: 1.0})
        return
    if state.get("stopped"):
        for campaign_id in state["campaigns"].values():
            control.resume(repo, campaign_id, reason="the focus given a share again")
        state["stopped"] = False
    workers = worker_count.wanted(repo.get_flag(worker_count.FLAG, ""), DEFAULT_WORKERS) or DEFAULT_WORKERS
    one = 1.0 / max(2, workers)
    work_groups.set_shares(repo, {work_groups.BLIND: (1.0 - focus_share) * (1.0 - one),
                                  NEIGHBOURS: focus_share * (1.0 - one), DEPTH: one})
    control.set_workers(repo, state["campaigns"][DEPTH], DEPTH_WORKERS, reason="the depth seeker holds one worker")


def lean(repo, share) -> dict:
    state = _loaded(repo)
    _lean(repo, state, share)
    save(repo, state)
    return state


def zone_entry(repo, state: dict, zone: dict) -> dict:
    law, campaign_id = str(zone["centre"]), str(zone["campaign"])
    here = next((e for e in best(repo, state["study"], state) if e["candidate_id"] == law), None)
    return {"candidate_id": law, "campaign": campaign_id,
            "score": (here or {}).get("score", (zone.get("chosen") or {}).get("best")),
            "chosen_by": BY_ZONE, "zone": {k: zone.get(k) for k in ("code", "why", "radius", "at")}}


def _chosen(repo, state: dict, law: str | None, ranked: list | None = None) -> dict | None:
    from graph_scale_dynamics.operations import dex_check
    if not law and dex_check.waiting(state):
        return None
    zone = dex_check.taken(state) if not law else None
    if zone is not None:
        return zone_entry(repo, state, zone)
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
            if not ranked:
                return None
            from graph_scale_dynamics.operations import outliers as OUT
            found = OUT.next_outlier(repo, state, rows_of=_rows, inside=inside, label=label)
            return None if found is None else dict(found, chosen_by=BY_OUTLIER)
        picked = suggested(repo, state, free)[0]
        return dict(picked, chosen_by=BY_BUNDLE if picked.get("standing") == "bundle" else BY_SCORE)
    found = next((e for e in ranked if e["candidate_id"].startswith(str(law)) or e.get("label") == str(law)
                  or LC.same(e.get("label"), law)), None)
    if found is not None:
        return dict(found, chosen_by=BY_OPERATOR)
    for campaign_id in own_campaigns(repo, state["study"]):
        row = repo.conn.execute("SELECT candidate_id FROM campaign_candidates WHERE campaign_id=? AND candidate_id LIKE ?",
                                (campaign_id, f"{law}%")).fetchone()
        if row is not None:
            return {"candidate_id": str(row["candidate_id"]), "campaign": campaign_id, "score": 0,
                    "chosen_by": BY_OPERATOR}
    raise ValueError(f"study {state['study']} has no law {law!r}")


def start_next(repo, state: dict, law: str | None = None, chosen: dict | None = None,
               ranked: list | None = None) -> dict | None:
    chosen = chosen or _chosen(repo, state, law, ranked)
    if chosen is None:
        return None
    if state.get("next_plan"):
        state["plan"] = state.pop("next_plan")
        state["events"].append({"at": utc_now(), "settings": settings_of(state["plan"])})
    if chosen.get("chosen_by") == BY_ZONE and (state.get("zone_chosen") or {}).get("centre") == chosen["candidate_id"]:
        state["zone_chosen"]["taken_utc"] = utc_now()
    holder, campaign_id = chosen["candidate_id"], chosen["campaign"]
    spec = _spec_of(repo, campaign_id, holder)
    read_n = int(state["plan"]["neighbourhood"]["read_n"])
    radii = [[float(r), int(c)] for r, c in state["plan"]["neighbourhood"]["radii"]]
    known, known_from = kind_here(repo, state, {"law": holder, "of": campaign_id}, read_n)
    current = {"law": holder, "of": campaign_id, "label": label(repo, campaign_id, holder),
               "score": chosen.get("score"), "kind": known, "kind_from": known_from,
               "stage": NEIGHBOURHOOD, "began_utc": utc_now(), "points": {}, "lines": {}, "radii": radii,
               **({"origin": chosen["origin"]} if chosen.get("origin") else {}),
               **({"standing": chosen["standing"]} if chosen.get("standing") else {}),
               **({"chosen_by": chosen["chosen_by"]} if chosen.get("chosen_by") else {}),
               **({"outlier": chosen["outlier"]} if chosen.get("outlier") else {}),
               **({"zone": chosen["zone"]} if chosen.get("zone") else {})}
    state["current"] = current
    type_of(repo, state, campaign_id, holder)
    current["identified_from"] = (state.get("identified") or {}).get(holder)
    _insert(repo, state["campaigns"][SEEDS], spec)
    if state.get("lean") is None and not state.get("stopped") and callable(getattr(repo, "set_flag", None)):
        _lean(repo, state, FIRST_LEAN)
    if chosen.get("chosen_by") == BY_ZONE:
        from graph_scale_dynamics.operations import zone_search
        zone_search.begin(repo, state, current, spec)
        contenders(repo, state, ranked)
        state["events"].append({"at": utc_now(), "began": current["label"], "search": True})
        return current
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
        from graph_scale_dynamics.operations import study_design as SD
        dex_entry = SD.dex_entry(SD.design_for(tree, str(study)))
        state = {"contract": CONTRACT, "study": str(study), "plan": found_plan, "campaigns": {}, "contenders": {},
                 "dex_first": bool((dex_entry or {}).get("verified_first")),
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
    if state.get("current") and not state.get("depth_now"):
        depth_next(repo, state, best(repo, state["study"], state))
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
    found = kinds(repo, state["campaigns"][SEEDS], law, whole=int(state["seeds"]))
    own = own_kinds(repo, state, law, campaign_id)
    read = {n: k for n, k in sorted(found.items()) if n >= read_n}
    from graph_scale_dynamics.operations import study_map
    whole = study_map.decided(repo, campaign_id, law) if own else False
    against = [n for n, k in read.items() if (whole or (own and n <= max(own))) and k != expected(own, n)]
    return {"kinds": {str(n): k for n, k in sorted(found.items())}, "deepest": max(found) if found else None,
            "own": {str(n): k for n, k in sorted(own.items())},
            "holds_to": max((n for n in read if n not in against), default=None),
            "invalidated_at": min(against) if against else None}


def seeds_of(repo, state: dict, current: dict) -> dict | None:
    from graph_scale_dynamics.observability import law_kind
    from graph_scale_dynamics.operations import study_map
    read_n = int(state["plan"]["neighbourhood"]["read_n"])
    campaign = state["campaigns"][SEEDS]
    if current.get("kind") is None or not study_map.decided(repo, campaign, current["law"]):
        return None
    own_all = seed_kinds(repo, current["of"], current["law"])
    more_all = seed_kinds(repo, campaign, current["law"])
    own = {s: law_kind.at(k, read_n) for s, k in own_all.items()}
    more = {s: law_kind.at(k, read_n) for s, k in more_all.items()}
    compared, agreed = {}, {}
    for seed, kinds_here in own_all.items():
        both = [n for n in kinds_here if n in (more_all.get(seed) or {}) and n <= read_n]
        if both:
            at = max(both)
            compared[seed] = at
            agreed[seed] = kinds_here[at] == more_all[seed][at]
    every = {**own, **more}
    return {"own": {str(s): k for s, k in sorted(own.items())}, "more": {str(s): k for s, k in sorted(more.items())},
            "compared_at": {str(s): n for s, n in sorted(compared.items())},
            "reproduced": bool(agreed) and all(agreed.values()),
            "other": sorted(s for s, k in every.items() if k != current["kind"]), "of": len(every)}


def tally(current: dict, verdicts: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    known = current.get("kind")
    for law, point in current["points"].items():
        if point["how"] != "neighbour":
            continue
        row = out.setdefault(f"{float(point['radius']):g}",
                             {"laws": 0, "alike": 0, "other": 0, "waiting": 0, "read": 0})
        row["laws"] += 1
        seen = verdicts.get(law)
        row["read"] += 0 if seen is None else 1
        row["waiting" if seen is None or known is None else "alike" if seen == known else "other"] += 1
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
            "alike_to": current.get("alike_to"), "confirmed_at": current.get("confirmed_at"),
            "depth": current.get("depth"), "refused": current.get("refused"),
            "boundaries": {p: {"between": [line["lo"], line["hi"]], "kinds": [line["lo_kind"], line["hi_kind"]],
                               "why": line.get("why")} for p, line in (current.get("lines") or {}).items()},
            "began_utc": current.get("began_utc"), "ended_utc": current.get("ended_utc"),
            "terms": current.get("terms"), "core": current.get("core"), "terms_kept": current.get("terms_kept"),
            "needs": current.get("needs"), "kind_from": current.get("kind_from"),
            "chosen_by": current.get("chosen_by"),
            "identified_from": current.get("identified_from"), "early_call": current.get("early_call"),
            "origin": current.get("origin"), "standing": current.get("standing"),
            **({"search": current.get("search_summary") or current["search"]} if current.get("search") else {})}


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


def kind_here(repo, state: dict, current: dict, read_n: int) -> tuple[str | None, str | None]:
    own = verdict(repo, current["of"], current["law"], read_n)
    if own is not None:
        return own, OWN_CAMPAIGN
    more = verdict(repo, state["campaigns"][SEEDS], current["law"], read_n)
    if more is not None and not str(more).startswith("stopped"):
        return more, SEEDS_CAMPAIGN
    return None, None


def _need(what: str, done: bool, said: str) -> dict:
    return {"what": what, "done": bool(done), "said": said}


def needs(state: dict, current: dict) -> list[dict]:
    if current.get("search") is not None:
        from graph_scale_dynamics.operations import zone_search
        return zone_search.needs(state, current)
    p = state["plan"]["neighbourhood"]
    read_n, radius = int(p["read_n"]), f"{float(p['confirm_radius']):g}"
    kind, rows = current.get("kind"), current.get("tally") or {}
    out = [_need("its kind", kind is not None,
                 f"{kind} at N={read_n:,}, read in {current.get('kind_from') or 'its own campaign'}" if kind is not None
                 else f"not read at N={read_n:,} yet in its own campaign or its seeds' campaign")]
    first = rows.get(radius) or {}
    share = float(p["confirm_share"])
    if kind is None:
        out.append(_need(f"ring {radius}", False, f"{first.get('read', 0)} of {first.get('laws', 0)} neighbours read; "
                                                  "judged once its own kind is read"))
    else:
        holds = bool(first) and not first.get("waiting") and first["alike"] / max(1, first["laws"]) >= share
        smaller = current.get("confirmed_at")
        said = (f"{first.get('alike', 0)} of {first.get('laws', 0)} alike, {first.get('waiting', 0)} waiting; "
                f"{share:.0%} must be alike")
        if not holds and smaller is not None and float(smaller) < float(radius):
            said += f"; its zone stands at ring {float(smaller):g} instead"
        elif not holds and first and not first.get("waiting"):
            said += f"; else a ring from {float(p['lines_from_radius']):g} up"
        out.append(_need(f"ring {radius}", holds or (smaller is not None and float(smaller) < float(radius)), said))
    depth = current.get("depth") or {}
    out.append(_need("its depth", depth.get("holds_to") is not None,
                     f"holds its kind to N={int(depth['holds_to']):,}" if depth.get("holds_to") is not None
                     else f"its seeds have read it to N={int(depth['deepest']):,}; it must reach N={read_n:,}"
                     if depth.get("deepest") else f"its seeds must read it to N={read_n:,}"))
    seeds = current.get("seeds")
    out.append(_need("its seeds", seeds is not None,
                     ("reproduced" if seeds.get("reproduced") else "not reproduced at the sizes both read")
                     + f"; {len(seeds.get('other') or [])} of {seeds.get('of')} seeds read another kind" if seeds
                     else "its seeds' campaign and its own kind first"))
    waiting = sum(int(row.get("waiting") or 0) for row in rows.values())
    total = sum(int(row.get("laws") or 0) for row in rows.values())
    out.append(_need("every ring", total > 0 and waiting == 0, f"{total - waiting} of {total} neighbours judged"))
    terms = current.get("terms") or {}
    open_terms = [t for t, row in terms.items() if row.get("load_bearing") is None]
    knocked = sum(1 for point in (current.get("points") or {}).values() if point.get("how") == KNOCKOUT)
    out.append(_need("each term switched off", not open_terms and len(terms) >= knocked,
                     f"{len(terms) - len(open_terms)} of {max(len(terms), knocked)} judged"))
    return out


def advance(repo, state: dict) -> int:
    current = state["current"]
    if current.get("search") is not None:
        from graph_scale_dynamics.operations import zone_search
        return zone_search.advance(repo, state, current)
    p = state["plan"]["neighbourhood"]
    read_n = int(p["read_n"])
    if current.get("kind") is None:
        current["kind"], current["kind_from"] = kind_here(repo, state, current, read_n)
    verdicts = current.setdefault("read", {})
    stamps, so_far = current.setdefault("read_at", {}), current.setdefault("so_far", {})
    for law in current["points"]:
        if law not in verdicts:
            seen = verdict(repo, state["campaigns"][NEIGHBOURS], law, read_n)
            if seen is not None:
                verdicts[law] = seen
                stamps.setdefault(law, utc_now())
                so_far.pop(law, None)
                continue
            found = kinds_so_far(repo, state["campaigns"][NEIGHBOURS], law, int(state.get("seeds") or 3))
            if found:
                so_far[law] = found
    current["tally"] = tally(current, verdicts)
    current["early_call"] = early_call(repo, state, current, verdicts)
    current["terms"] = terms_read(current, verdicts)
    current["core"] = core_of(current["terms"])
    current["depth"] = depth_of(repo, state, current["law"], current["of"])
    current["seeds"] = seeds_of(repo, state, current)
    more = int(state.get("seeds") or 3) * int(state["plan"]["seeds"]["times"])
    current["law_kinds"] = dict((current["depth"] or {}).get("own") or {},
                                **kinds_so_far(repo, state["campaigns"][SEEDS], current["law"], more))
    current["sensitivity"] = sensitivity(state["plan"], current["tally"], current["seeds"])
    current["alike_to"] = alike_to(state["plan"], current["tally"]) if current.get("kind") is not None else None
    current["needs"] = needs(state, current)
    if current["kind"] is None:
        return 0
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
            found = confirmed_at(state["plan"], current["tally"])
            if found is None:
                return 0
            if found is False:
                _end(state, current, UNCONFIRMED, f"{first['alike']} of {first['laws']} neighbours at radius "
                     f"{float(p['confirm_radius']):g} read its kind at {read_n:,}, and no smaller ring from "
                     f"{float(p['lines_from_radius']):g} does by {float(p['confirm_share']):.0%}")
                return 0
            if current.get("confirmed_at") != found:
                current["confirmed_at"] = found
                state["events"].append({"at": utc_now(), "law": current["label"], "confirmed_at": found,
                                        "why": f"{first['alike']} of {first['laws']} alike at "
                                               f"{float(p['confirm_radius']):g}: its zone is smaller"})
        else:
            current["confirmed_at"] = float(p["confirm_radius"])
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
    if current.get("search") is not None:
        from graph_scale_dynamics.operations import zone_search
        return zone_search.members_specs(repo, state, current)
    seen = current.get("read") or {}
    specs = [_spec_of(repo, current["of"], current["law"])]
    for law, point in current["points"].items():
        if seen.get(law) == current["kind"] and point["how"] in ("neighbour", "line", KNOCKOUT):
            specs.append(_spec_of(repo, state["campaigns"][NEIGHBOURS], law))
    return [spec for spec in specs if spec]


def _finish(repo, state: dict, current: dict) -> None:
    if current.get("search") is not None:
        from graph_scale_dynamics.operations import zone_search
        current["search_summary"] = zone_search.summary(current)
    summary = _summary(current)
    summary["type"] = type_of(repo, state, current["of"], current["law"])
    region = None
    if current["stage"] == MAPPED:
        region = R.place(state, summary, members(repo, state, current))
        summary["region"] = region["name"]
        if summary.get("core") is not None:
            region.setdefault("cores", {})[str(summary.get("label") or summary["law"])] = summary["core"]
        state["events"].append({"at": utc_now(), "law": current["label"], "region": region["name"]})
    state["done"].append(summary)
    state["current"] = None
    if current.get("search") is not None:
        from graph_scale_dynamics.operations import zone_search
        zone_search.ended(repo, state, current, region)


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
                    "status": status, "region": R.name_of(state, law), "type": (state.get("types") or {}).get(law),
                    **({"origin": entry["origin"]} if entry.get("origin") else {}),
                    **({"standing": entry["standing"]} if entry.get("standing") else {})})
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
    found = sorted(law for law, name in known.items() if law.startswith(given) or name == given or LC.same(name, given))
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
    from graph_scale_dynamics.operations import modes
    modes.keep(repo, state)
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
        out["next"]["inside_share"] = _bounded(given["inside_share"], 0.0, 1.0, "the share of a zone's reach")
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
    elif do == "lean":
        lean(repo, body.get("focus"))
    elif do == "order":
        reorder(repo, str(body.get("list") or ""), str(body.get("law") or ""), str(body.get("move") or ""))
    elif do == "push_move":
        from graph_scale_dynamics.operations import push
        return {"ok": True, "did": do, **push.move(repo, str(body.get("law") or ""), int(body.get("to") or 0))}
    elif do in ("push", "unpush"):
        from graph_scale_dynamics.operations import push
        return {"ok": True, "did": do, **push.toggle(repo, str(body.get("law") or ""),
                                                     campaign=body.get("campaign") or None, on=do == "push")}
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
    try:
        done = _step(repo, state)
    except Exception as exc:
        failed(repo, exc)
        raise
    passed(repo)
    return done


def taken_as_outlier(current: dict | None) -> bool:
    if not current or current.get("stage") in ENDED:
        return False
    if current.get("chosen_by"):
        return current["chosen_by"] == BY_OUTLIER
    return not current.get("score") and not current.get("origin")


def set_aside(repo, state: dict, ranked: list[dict]) -> str | None:
    current = state.get("current")
    if not taken_as_outlier(current) or not free_laws(repo, state, ranked):
        return None
    law = current["law"]
    state.setdefault("set_aside", {})[law] = {"at": utc_now(), "label": current.get("label"), "why": SET_ASIDE_WHY,
                                              "outlier": current.get("outlier")}
    state["contenders"].pop(law, None)
    state["current"] = None
    state["events"].append({"at": utc_now(), "set_aside": current.get("label"), "why": SET_ASIDE_WHY})
    return law


def _step(repo, state: dict) -> dict:
    from graph_scale_dynamics.operations import dex_check
    renew_depth(repo, state)
    tidy_depth(repo, state)
    ranked = [] if dex_check.waiting(state) else best(repo, state["study"])
    set_aside(repo, state, ranked)
    added = len(contenders(repo, state, ranked))
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
    added += 1 if depth_next(repo, state, ranked) else 0
    state["zone_first"] = zone_first(repo, state)
    state["depths"] = {law: dict(depth_of(repo, state, law, entry["of"]), label=entry["label"], of=entry["of"])
                       for law, entry in state["contenders"].items()}
    for law, entry in depth_ceilings(repo, state).items():
        if law in state["depths"]:
            state["depths"][law]["ceiling"] = entry
    state["queue"] = queue_of(state, ranked)
    state["lists"] = lists_of(repo, state, ranked)
    state["events"] = state["events"][-200:]
    if state.get("current") and state["current"].get("stage") not in ENDED:
        state["current"]["depth"] = state["current"].get("depth") or (state["depths"].get(state["current"]["law"]) or {})
        state["current"]["needs"] = needs(state, state["current"])
        stamped = state["current"].setdefault("needs_at", {})
        for need in state["current"]["needs"]:
            if need["done"]:
                stamped.setdefault(need["what"], utc_now())
            else:
                stamped.pop(need["what"], None)
    state["typical"] = typical_of(repo, state)
    save(repo, state)
    return {"stage": (current or {}).get("stage"), "added": added, "label": (current or {}).get("label")}


def _behind(repo, campaign_id: str, keep: list[str]) -> dict:
    keep = sorted(set(keep))
    marks = ",".join("?" for _ in keep)
    clause = f" AND candidate_id NOT IN ({marks})" if keep else ""
    back = repo.conn.execute(
        "UPDATE jobs SET priority=priority+? WHERE campaign_id=? AND kind='simulate' AND status='queued' "
        f"AND priority<?{clause}", (BEHIND, str(campaign_id), BEHIND, *keep)).rowcount
    forward = repo.conn.execute(
        "UPDATE jobs SET priority=priority-? WHERE campaign_id=? AND kind='simulate' AND status='queued' "
        f"AND priority>=? AND candidate_id IN ({marks})", (BEHIND, str(campaign_id), BEHIND, *keep)).rowcount if keep else 0
    waiting = repo.conn.execute(
        "SELECT COUNT(*) AS c FROM jobs WHERE campaign_id=? AND kind='simulate' AND status='queued' AND priority>=?",
        (str(campaign_id), BEHIND)).fetchone()["c"]
    return {"back": int(back or 0), "forward": int(forward or 0), "waiting": int(waiting or 0)}


def _released(repo, campaign_id: str) -> dict:
    forward = repo.conn.execute(
        "UPDATE jobs SET priority=priority-? WHERE campaign_id=? AND kind='simulate' AND status='queued' "
        "AND priority>=?", (BEHIND, str(campaign_id), BEHIND)).rowcount
    return {"back": 0, "forward": int(forward or 0), "waiting": 0}


def zone_first(repo, state: dict) -> dict:
    current = state.get("current")
    live = current is not None and current.get("stage") not in ENDED
    campaigns = state.get("campaigns") or {}
    out = {"at": utc_now(), "law": current.get("law") if live else None}
    for name, keep in ((NEIGHBOURS, list(current.get("points") or {}) if live else None),
                       (SEEDS, [current["law"]] if live else None)):
        if campaigns.get(name):
            out[name] = _released(repo, campaigns[name]) if keep is None else _behind(repo, campaigns[name], keep)
    return out


def typical_of(repo, state: dict) -> dict:
    from graph_scale_dynamics.operations import zone_live
    found = state.get("typical") or {}
    age = zone_live.seconds_since(found.get("at"), zone_live.when(utc_now()))
    if found.get("at") and age is not None and age < TYPICAL_EVERY_SECONDS:
        return found
    return zone_live.typical(repo, list((state.get("campaigns") or {}).values()))


def failing(repo) -> dict | None:
    try:
        found = json.loads(repo.get_flag(FAILED_FLAG, "") or "null")
    except (TypeError, ValueError):
        return None
    return found if isinstance(found, dict) and found.get("error") else None


def failed(repo, exc: BaseException) -> dict:
    seen = failing(repo) or {}
    error = f"{type(exc).__name__}: {exc}"[:400]
    found = {"since": seen.get("since") or utc_now(), "last": utc_now(), "times": int(seen.get("times") or 0) + 1,
             "error": error}
    try:
        repo.conn.rollback_if_open()
    except Exception:  # noqa: BLE001
        pass
    repo.set_flag(FAILED_FLAG, json.dumps(found, sort_keys=True))
    return found


def passed(repo) -> None:
    if failing(repo) is not None:
        repo.set_flag(FAILED_FLAG, "")


def depth_ladder(repo, campaign_id: str) -> list[int]:
    return [int(n) for n in (((repo.campaign(str(campaign_id)) or {}).get("spec") or {}).get("ladder") or [])]


def depth_wanted(found_plan: dict) -> dict:
    depth = found_plan["depth"]
    return {"top": max(int(n) for n in depth["beyond"]),
            "seeds": int(depth["seeds"]) if depth.get("seeds") else None,
            "memory_share": float(depth["memory_share"]) if depth.get("memory_share") else None}


def depth_fits(repo, campaign_id: str, wanted: dict) -> bool:
    spec = (repo.campaign(str(campaign_id)) or {}).get("spec") or {}
    if max((int(n) for n in spec.get("ladder") or []), default=0) < int(wanted["top"]):
        return False
    if wanted["seeds"] is not None and int(spec.get("default_seeds") or 0) != int(wanted["seeds"]):
        return False
    share = ((spec.get("study_design") or {}).get("focus") or {}).get("memory_share")
    return wanted["memory_share"] is None or (share is not None and float(share) == float(wanted["memory_share"]))


def depth_campaigns(repo, study: str) -> list[dict]:
    out = []
    for campaign in repo.all_campaigns():
        design = (campaign.get("spec") or {}).get("study_design") or {}
        if (str(design.get("study")) == str(study) and design.get("kind") == KIND
                and (design.get("focus") or {}).get("part") == DEPTH):
            out.append(campaign)
    return sorted(out, key=lambda c: _number(c["campaign_id"]))


def depth_ceilings(repo, state: dict) -> dict[str, dict]:
    from graph_scale_dynamics.operations import depth_reach
    campaign_id = state["campaigns"][DEPTH]
    try:
        depth_reach.refresh(repo, campaign_id)
    except Exception as exc:  # noqa: BLE001
        state["events"].append({"at": utc_now(), "depth_reach_unread": f"{type(exc).__name__}: {exc}"[:200]})
    return depth_reach.ceilings(repo, campaign_id)


def renew_depth(repo, state: dict, tree=None) -> str | None:
    from graph_scale_dynamics import PROJECT_ROOT
    from graph_scale_dynamics.operations import campaign_control as control
    tree = Path(tree) if tree is not None else Path(PROJECT_ROOT)
    found_plan = plan(tree)
    wanted = depth_wanted(found_plan)
    old = str(state["campaigns"][DEPTH])
    if depth_fits(repo, old, wanted):
        return None
    made = next((str(c["campaign_id"]) for c in depth_campaigns(repo, state["study"])
                 if str(c["campaign_id"]) != old and c.get("status") == "active"
                 and not control.is_paused(repo, str(c["campaign_id"]))
                 and depth_fits(repo, str(c["campaign_id"]), wanted)), None)
    adopted = made is not None
    if made is None:
        anchor = next(iter(own_campaigns(repo, state["study"])), None)
        if anchor is None:
            return None
        spec = campaign_specs(repo, state["study"], anchor, found_plan, tree)[DEPTH]
        made = str(control.create_campaign(
            repo, spec, search_seed=_seed(state["study"], DEPTH, wanted["top"], wanted["seeds"]),
            reason=f"study {state['study']}'s focus: the depth seeker, one law at a time on "
                   f"{wanted['seeds'] or spec.get('default_seeds')} seed, its ladder open to N={wanted['top']:,}"
        )["campaign_id"])
    control.pause(repo, old, reason=f"the depth seeker moved to campaign {made}")
    control.set_workers(repo, made, DEPTH_WORKERS, reason="the depth seeker holds one worker")
    state["campaigns"][DEPTH] = made
    state["seeds"] = int(((repo.campaign(made) or {}).get("spec") or {}).get("default_seeds") or state["seeds"])
    state.setdefault("depth_before", []).append({"campaign": old, "until": utc_now()})
    state["depth_now"], state["depth_done"] = None, {}
    state["events"].append({"at": utc_now(), "depth_renewed": made, "from": old, "to_n": wanted["top"],
                            "seeds": state["seeds"], "adopted": adopted})
    save(repo, state)
    return made


def tidy_depth(repo, state: dict) -> list[str]:
    from graph_scale_dynamics.operations import campaign_control as control
    keep = str(state["campaigns"][DEPTH])
    paused = []
    for campaign in depth_campaigns(repo, state["study"]):
        campaign_id = str(campaign["campaign_id"])
        if campaign_id == keep or campaign.get("status") != "active" or control.is_paused(repo, campaign_id):
            continue
        control.pause(repo, campaign_id, reason=f"one depth seeker: campaign {keep} is the focus's depth campaign; "
                                                "this one rests, everything it measured kept")
        paused.append(campaign_id)
    if paused:
        state["events"].append({"at": utc_now(), "depth_paused": paused, "kept": keep})
        save(repo, state)
    return paused


def depth_line(state: dict, ranked: list[dict]) -> list[str]:
    held = state.get("contenders") or {}
    line = [e["candidate_id"] for e in depth_order(state, ranked) if e["candidate_id"] in held]
    line += [law for law, _e in sorted(held.items(), key=lambda kv: str(kv[1].get("joined_utc") or ""))
             if law not in line]
    current = (state.get("current") or {}).get("law")
    if current in held and current not in ((state.get("order") or {}).get(DEPTH_LIST) or []):
        line = [current] + [law for law in line if law != current]
    from graph_scale_dynamics.operations import push
    return push.front(state, line, held)


def depth_next(repo, state: dict, ranked: list[dict]) -> str | None:
    from graph_scale_dynamics.operations import modes, push, push_ladder
    push.adopt_central(state)
    if not state.get(push.ADOPTED):
        push.adopt_now(state)
        state[push.ADOPTED] = utc_now()
    done = push_ladder.step(repo, state)
    modes.keep(repo, state)
    return (done or {}).get("law") if (done or {}).get("queued") else None


def work_of(repo, state: dict | None) -> dict[str, dict]:
    if not state or not state.get("campaigns"):
        return {}
    ids = {str(cid): name for name, cid in state["campaigns"].items()}
    rows = repo.conn.execute(
        "SELECT campaign_id, SUM(CASE WHEN status='leased' THEN 1 ELSE 0 END) AS running, "
        "SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) AS queued, "
        "SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done, "
        "MAX(CASE WHEN status='done' THEN n END) AS deepest FROM jobs WHERE kind='simulate' "
        f"AND campaign_id IN ({','.join('?' for _ in ids)}) GROUP BY campaign_id", tuple(ids)).fetchall()
    out = {name: {"campaign": cid, "running": 0, "queued": 0, "done": 0, "deepest": None} for cid, name in ids.items()}
    for row in rows:
        out[ids[str(row["campaign_id"])]].update(running=int(row["running"] or 0), queued=int(row["queued"] or 0),
                                                 done=int(row["done"] or 0),
                                                 deepest=None if row["deepest"] is None else int(row["deepest"]))
    return out


def reading(repo) -> dict | None:
    state = load(repo)
    if state is None:
        return None
    found = failing(repo)
    if found:
        state["failing"] = found
    return reading_of(state)


STAGE_WORDS = {NEIGHBOURHOOD: "reading its neighbourhood", BOUNDARIES: "halving its boundaries"}


def origin_words(origin: dict | None) -> str | None:
    if not origin:
        return None
    return f"{origin.get('score')} in study {origin.get('study')}'s bundle"


def depth_words(state: dict) -> str:
    now = state.get("depth_now")
    done = state.get("pushed_done") or []
    many = f"{len(done)} law{'' if len(done) == 1 else 's'} pushed to their limit"
    if now:
        return f"; the N-push on {now.get('label') or str(now.get('law'))[:12]}" + (f", {many} before it" if done else "")
    return f"; {many}" if done else ""


def failing_words(found: dict | None) -> str | None:
    if not found:
        return None
    return (f"the focus's step has failed {int(found.get('times') or 1):,} time{'' if found.get('times') == 1 else 's'} "
            f"since {found.get('since')} ({found.get('error')}); nothing it reads is saved until it passes")


def chosen_words(current: dict) -> str:
    by = current.get("chosen_by")
    if by == BY_OUTLIER:
        found = current.get("outlier") or {}
        reading = (f", {found.get('probe')} {found.get('value')} at N={int(found['n']):,} on {len(found.get('seeds_over') or [])} "
                   f"of {found.get('seeds')} seeds" if found.get("probe") and found.get("n") else "")
        return f" (an outlier, every scoring law mapped{reading})"
    if by == BY_BUNDLE:
        return f" (score {current.get('score')} in {(current.get('origin') or {}).get('bundle') or 'its bundle'})"
    if by == BY_OPERATOR:
        return " (the operator's choice)"
    if by == BY_SCORE:
        return f" (the best free scoring law, score {current.get('score')})"
    if by == BY_ZONE:
        return f" (the centre of the first zone, chosen to confirm fast: {(current.get('zone') or {}).get('why')})"
    return ""


def doing_of(state: dict) -> str:
    said = _doing(state)
    failed_now = failing_words(state.get("failing"))
    return f"{failed_now}. {said}" if failed_now else said


def _doing(state: dict) -> str:
    current, read_n = state.get("current"), int(state["plan"]["neighbourhood"]["read_n"])
    depth = depth_words(state)
    if state.get("stopped"):
        return "off: the focus's campaigns are paused and the blind draw has every worker"
    if current and current.get("stage") not in ENDED:
        said = f"in focus: {current.get('label')}{chosen_words(current)}, {STAGE_WORDS.get(current.get('stage'), current.get('stage'))}"
        if current.get("standing") == "bundle":
            said += (f", on its bundle's score ({origin_words(current.get('origin'))}) until this folder reads it at "
                     f"N={read_n:,}")
        if current.get("kind") is None:
            said += f"; its neighbours wait for its own kind at N={read_n:,}"
        return said + depth
    from graph_scale_dynamics.operations import dex_check
    verifying = dex_check.words(state)
    if verifying:
        return verifying + depth
    queue = state.get("queue") or []
    if not queue:
        return (f"idle: no law scores in this folder yet and no seeded law stands on a bundle's score; a law joins the "
                f"focus once it scores here at N={read_n:,} or a bundle is seeded" + depth)
    if not any(entry.get("status") == "waiting" for entry in queue):
        return "idle: every scoring law is mapped, inside a mapped zone or skipped" + depth
    return "waiting for the focus's next step (once a minute)" + depth


def reading_of(state: dict) -> dict:
    from graph_scale_dynamics.operations import dex_check, study_seed
    current = state.get("current")
    return {"contract": CONTRACT, "study": state["study"], "campaigns": state["campaigns"], "doing": doing_of(state),
            "current": _summary(current) if current else None,
            "points": len((current or {}).get("points") or {}), "lines": len((current or {}).get("lines") or {}),
            "contenders": state.get("depths") or {law: dict(e) for law, e in state["contenders"].items()},
            "done": state["done"], "inside": state.get("inside") or {}, "stopped": bool(state.get("stopped")),
            "skipped": state.get("skipped") or {}, "queue": state.get("queue") or [],
            "regions": state.get("regions") or [], "touching": R.touching(state.get("regions") or []),
            "seeded": [{k: v for k, v in r.items() if k != "laws"} | {"laws_standing": len(r.get("laws") or {}),
                                                                      "selected": study_seed.selected(r),
                                                                      "laws_recorded": r.get("laws") is not None}
                       for r in study_seed.records(state)],
            "lists": state.get("lists") or {}, "lean": state.get("lean"),
            "order": state.get("order") or {}, "identified": state.get("identified") or {},
            "failing": state.get("failing"), "depth_now": state.get("depth_now"),
            "depth_done": state.get("depth_done") or {},
            "settings": settings_of(state["plan"]),
            "next_settings": settings_of(state["next_plan"]) if state.get("next_plan") else None,
            "dex_check": dex_check.reading(state),
            "pushed": [dict(e) for e in state.get("pushed") or []],
            "events": (state.get("events") or [])[-30:]}


def words(found: dict | None) -> str:
    if not found:
        return "no focus in this folder"
    current = found.get("current")
    c = found["campaigns"]
    lines = [f"study {found['study']}'s focus: neighbours in campaign {c[NEIGHBOURS]} and more seeds in {c[SEEDS]} "
             f"(group N), the depth in {c[DEPTH]} (group D)"] + ([f"  {found['doing']}"] if found.get("doing") else [])
    if current:
        lines.append(f"  {current['label']} (score {current['score']}"
                     + (f", {origin_words(current.get('origin'))}" if current.get("origin") else "")
                     + f"), its kind at the read: {current['kind']}: "
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
