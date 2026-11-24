from __future__ import annotations

import json
import time

from graph_scale_dynamics.domain.model import utc_now
from graph_scale_dynamics.research import neighbourhood as N

CONTRACT = "gsd-study-map-1"
FLAG = "study_map"
MAPPING, KNOWN = "mapping", "known"
INTERVAL_SECONDS = 60.0
EARLY = (1024, 4096)
PARTNER_TRIES = 50
_LAST: dict[str, float] = {}


def load(repo) -> dict | None:
    try:
        state = json.loads(repo.get_flag(FLAG, "") or "null")
    except (TypeError, ValueError):
        return None
    return state if isinstance(state, dict) and state.get("contract") == CONTRACT else None


def save(repo, state: dict) -> None:
    repo.set_flag(FLAG, json.dumps(state, sort_keys=True, separators=(",", ":")))


def _insert(repo, campaign_id: str, spec: dict) -> str:
    from graph_scale_dynamics.domain.model import CandidateState
    from graph_scale_dynamics.dsl import dsl
    normalized = dsl.normalize(spec)
    law = dsl.fingerprint(normalized)
    repo.insert_candidate(law, str(campaign_id), normalized, normalized["dynamics"]["kind"],
                          dsl.complexity(normalized), CandidateState.PROPOSED.value)
    return law


def points_of(holder: dict, *, step: float, halvings: int, complexity_budget: int, whitelist) -> tuple[list, dict]:
    from graph_scale_dynamics.dsl import dsl
    spec = holder["spec"]
    points = [{"how": "holder", "spec": dsl.normalize(spec), **({"campaign": str(holder["campaign"])}
                                                                 if holder.get("campaign") else {})}]
    refused = []
    for found in N.alone(spec, step):
        problem = N.valid(found["spec"], complexity_budget=complexity_budget, whitelist=whitelist)
        if problem is None:
            points.append({"how": "variant", "parameter": found["parameter"], "step": found["step"],
                           "spec": dsl.normalize(found["spec"])})
        else:
            refused.append({"parameter": found["parameter"], "step": found["step"], "why": problem})
    lines = {}
    partner = holder.get("partner")
    if partner and partner.get("spec") is not None:
        line = {"partner": partner["candidate_id"], "lo": 0.0, "hi": 1.0, "lo_kind": holder.get("kind_at_4096"),
                "hi_kind": partner.get("kind_at_4096"), "halvings": 0, "most": int(halvings), "points": {},
                "partner_spec": dsl.normalize(partner["spec"])}
        at = N.next_point(line)
        child = N.between(spec, partner["spec"], at) if at is not None else None
        problem = None if child is None else N.valid(child, complexity_budget=complexity_budget, whitelist=whitelist)
        if child is not None and problem is None:
            points.append({"how": "line", "partner": partner["candidate_id"], "at": at, "spec": dsl.normalize(child)})
        else:
            line.update(done=True, why=problem or "no point between them")
        lines[partner["candidate_id"]] = line
    return points, {"lines": lines, "refused": refused}


def designed_points(plan: dict, holders: list[dict], survey: dict) -> list[dict]:
    from graph_scale_dynamics.dsl import dsl
    out = []
    for holder in holders:
        points, _rest = points_of(holder, step=float(plan["step"]), halvings=int(plan["halvings"]),
                                  complexity_budget=int(survey.get("complexity_budget") or 6),
                                  whitelist=survey.get("operator_whitelist"))
        for point in points:
            out.append({"label": f"{holder['label']}~{point['how']}", "of": holder["candidate_id"],
                        "spec": point["spec"], "candidate_id": dsl.fingerprint(point["spec"])})
    return out


def begin(repo, study: str, campaign_id: str, plan: dict, holders: list[dict], survey: dict) -> dict:
    state = load(repo)
    if state is not None and state.get("study") == str(study) and state.get("campaign") == str(campaign_id):
        return state
    state = {"contract": CONTRACT, "study": str(study), "campaign": str(campaign_id), "top": int(plan["top"]),
             "step": float(plan["step"]), "halvings": int(plan["halvings"]),
             "complexity_budget": int(survey.get("complexity_budget") or 6),
             "whitelist": survey.get("operator_whitelist"), "regions": {}, "events": []}
    for holder in holders:
        enter(repo, state, holder, source="the baseline")
    save(repo, state)
    return state


def enter(repo, state: dict, holder: dict, *, source: str) -> dict:
    points, rest = points_of(holder, step=state["step"], halvings=state["halvings"],
                             complexity_budget=state["complexity_budget"], whitelist=state["whitelist"])
    region = {"holder": holder["candidate_id"], "label": holder.get("label"), "score": holder.get("score"),
              "entered_utc": utc_now(), "source": source, "state": MAPPING, "points": {}, **rest}
    for point in points:
        if point.get("campaign") and point["campaign"] != state["campaign"]:
            law = str(holder["candidate_id"])
        else:
            law = _insert(repo, state["campaign"], point["spec"])
        region["points"][law] = {k: v for k, v in point.items() if k != "spec"}
        if point["how"] == "line":
            region["lines"][point["partner"]]["points"][f"{point['at']:g}"] = law
    state["regions"][holder["candidate_id"]] = region
    state["events"].append({"at": utc_now(), "entered": holder["candidate_id"], "points": len(points),
                            "source": source})
    return region


def study_campaigns(repo, study: str) -> list[str]:
    out = []
    for campaign in repo.all_campaigns():
        spec = campaign.get("spec") or {}
        if str((spec.get("study_design") or {}).get("study")) == str(study):
            out.append(str(campaign["campaign_id"]))
    return out


def decided(repo, campaign_id: str, law: str) -> bool:
    from graph_scale_dynamics.reporting.every_chain_report import decided_law
    row = repo.conn.execute("SELECT action,rule,at_n FROM engine_decisions_latest WHERE campaign_id=? AND candidate_id=?",
                            (str(campaign_id), str(law))).fetchone()
    return row is not None and decided_law(dict(row))


def kinds_of(repo, campaign_id: str, law: str) -> dict[int, str]:
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    from graph_scale_dynamics.observability import law_kind, two_chains
    rows = repo.measurements(str(law), ANALYSIS_VERSION, str(campaign_id))
    spec = (repo.campaign(str(campaign_id)) or {}).get("spec") or {}
    starts = (spec.get("sampling_contract") or {}).get("given_starts")
    return law_kind.kinds(two_chains.chains_per_rung(rows, starts))


def _known_kinds(repo, state: dict, region: dict) -> dict[str, dict]:
    out = {}
    for law, point in region["points"].items():
        campaign = point.get("campaign") or state["campaign"]
        if "kinds" in point:
            out[law] = point["kinds"]
        elif decided(repo, campaign, law):
            point["kinds"] = {str(n): k for n, k in kinds_of(repo, campaign, law).items()}
            out[law] = point["kinds"]
    return out


def _kind_at(kinds: dict, n: int = 4096) -> str | None:
    from graph_scale_dynamics.observability import law_kind
    return law_kind.at({int(k): v for k, v in (kinds or {}).items()}, n)


def advance(repo, state: dict, region: dict) -> int:
    known = _known_kinds(repo, state, region)
    added = 0
    holder_kinds = known.get(region["holder"])
    for partner, line in region["lines"].items():
        if line.get("done"):
            continue
        if holder_kinds is not None:
            line["lo_kind"] = _kind_at(holder_kinds)
        at = N.next_point(line)
        law = line["points"].get(f"{at:g}") if at is not None else None
        if law is None or law not in known:
            continue
        narrowed = N.narrowed(line, at, _kind_at(known[law]))
        if line["lo_kind"] is not None and line["lo_kind"] == line["hi_kind"]:
            narrowed.update(done=True, why="the holder and its partner read one kind at 4,096 here")
        line.update(narrowed)
        following = N.next_point(line)
        if following is None:
            continue
        holder_campaign = region["points"][region["holder"]].get("campaign") or state["campaign"]
        child = N.between(_spec(repo, dict(state, campaign=holder_campaign), region["holder"]),
                          line["partner_spec"], following)
        problem = None if child is None else N.valid(child, complexity_budget=state["complexity_budget"],
                                                      whitelist=state["whitelist"])
        if child is None or problem is not None:
            line.update(done=True, why=problem or "no point between them")
            continue
        law = _insert(repo, state["campaign"], child)
        region["points"][law] = {"how": "line", "partner": partner, "at": following}
        line["points"][f"{following:g}"] = law
        added += 1
    if all(law in known for law in region["points"]) and all(line.get("done") for line in region["lines"].values()):
        mark_known(region, known)
    return added


def _spec(repo, state: dict, law: str) -> dict:
    return (repo.candidate(str(law), state["campaign"]) or {}).get("spec") or {}


def mark_known(region: dict, known: dict[str, dict]) -> None:
    holder = {int(n): k for n, k in (known.get(region["holder"]) or {}).items()}
    kind = holder[max(holder)] if holder else None
    alike = [{int(n): k for n, k in kinds.items()} for law, kinds in known.items()
             if kinds and kinds[str(max(int(n) for n in kinds))] == kind]
    spotted = None
    for n in EARLY:
        if alike and all(kinds.get(n) == kind for kinds in alike):
            spotted = n
            break
    tally: dict[str, int] = {}
    for kinds in known.values():
        last = kinds[str(max(int(n) for n in kinds))] if kinds else "unread"
        tally[last] = tally.get(last, 0) + 1
    region.update(state=KNOWN, kind=kind, spotted_at=spotted, known_utc=utc_now(), kinds=tally,
                  boundaries={partner: {"between": [line["lo"], line["hi"]], "kinds": [line["lo_kind"], line["hi_kind"]],
                                        "why": line.get("why")}
                              for partner, line in region["lines"].items()})


def taken(state: dict) -> set[str]:
    return {law for region in state["regions"].values() for law in [region["holder"], *region["points"]]}


def best(repo, state: dict) -> list[dict]:
    from graph_scale_dynamics.observability import law_score as L
    from graph_scale_dynamics.observability import score_board
    found = {}
    for campaign_id in study_campaigns(repo, state["study"]):
        for law, score in (score_board.board(repo, campaign_id)["scores"] or {}).items():
            if int(score.get("score") or 0) > L.FROZEN_SCORE:
                have = found.get(law)
                if have is None or int(score["score"]) > int(have[1]["score"]):
                    found[law] = (campaign_id, score)
    out = []
    for law, (campaign_id, score) in found.items():
        out.append({"candidate_id": law, "campaign": campaign_id, "score": int(score["score"]),
                    "to_n": int(score.get("to_n") or 0)})
    return sorted(out, key=lambda e: (-e["score"], -e["to_n"], e["candidate_id"]))


def partner_of(repo, state: dict, law: str, campaign_id: str, spec: dict, kind: str | None) -> dict | None:
    if kind is None:
        return None
    others = []
    for campaign in study_campaigns(repo, state["study"]):
        rows = repo.conn.execute("SELECT c.candidate_id,s.spec_json FROM campaign_candidates c JOIN candidate_specs s "
                                 "ON s.candidate_id=c.candidate_id WHERE c.campaign_id=? AND c.candidate_id<>?",
                                 (campaign, str(law))).fetchall()
        for row in rows:
            other = json.loads(row["spec_json"])
            gap = N.distance(spec, other)
            if gap is None or gap < N.MIN_DISTANCE:
                continue
            others.append((gap, campaign, str(row["candidate_id"]), other))
    for gap, campaign, other_law, other in sorted(others, key=lambda item: (item[0], item[2]))[:PARTNER_TRIES]:
        if not decided(repo, campaign, other_law):
            continue
        other_kind = _kind_at({str(n): k for n, k in kinds_of(repo, campaign, other_law).items()})
        if other_kind is not None and other_kind != kind:
            return {"candidate_id": other_law, "spec": other, "kind_at_4096": other_kind, "distance": round(gap, 6)}
    return None


def step(repo, *, now: float | None = None, force: bool = False) -> dict | None:
    state = load(repo)
    if state is None:
        return None
    clock = time.monotonic() if now is None else float(now)
    if not force and clock - _LAST.get(state["campaign"], -1e18) < INTERVAL_SECONDS:
        return None
    _LAST[state["campaign"]] = clock
    added = 0
    for region in state["regions"].values():
        if region["state"] == MAPPING:
            added += advance(repo, state, region)
    mapping = sum(1 for region in state["regions"].values() if region["state"] == MAPPING)
    entered = []
    if mapping < state["top"]:
        out = taken(state)
        for entry in best(repo, state):
            if mapping >= state["top"]:
                break
            if entry["candidate_id"] in out:
                continue
            spec = _spec(repo, dict(state, campaign=entry["campaign"]), entry["candidate_id"])
            if not spec:
                continue
            kind = _kind_at({str(n): k for n, k in kinds_of(repo, entry["campaign"], entry["candidate_id"]).items()})
            holder = {"candidate_id": entry["candidate_id"], "score": entry["score"], "spec": spec,
                      "campaign": entry["campaign"],
                      "kind_at_4096": kind,
                      "partner": partner_of(repo, state, entry["candidate_id"], entry["campaign"], spec, kind)}
            region = enter(repo, state, holder, source=f"campaign {entry['campaign']}")
            added += len(region["points"])
            entered.append(entry["candidate_id"])
            mapping += 1
    state["events"] = state["events"][-200:]
    save(repo, state)
    return {"added": added, "entered": entered, "mapping": mapping,
            "known": sum(1 for region in state["regions"].values() if region["state"] == KNOWN)}


def reading(repo) -> dict | None:
    state = load(repo)
    if state is None:
        return None
    regions = []
    for law, region in state["regions"].items():
        regions.append({"holder": law, "label": region.get("label"), "state": region["state"],
                        "score": region.get("score"), "points": len(region["points"]),
                        "kind": region.get("kind"), "spotted_at": region.get("spotted_at"),
                        "kinds": region.get("kinds"), "boundaries": region.get("boundaries")})
    return {"contract": CONTRACT, "study": state["study"], "campaign": state["campaign"], "top": state["top"],
            "regions": regions}
