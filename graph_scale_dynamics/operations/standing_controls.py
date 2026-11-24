from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics import PROJECT_ROOT

STANDING_CONTROLS_CONTRACT = "gsd-standing-controls-1"
NAME = "campaign-standing-controls"
CRITERION = Path(PROJECT_ROOT) / "graph_scale_dynamics" / "resources" / "readings" / "controls_criterion_2.json"
BASE_SPEC = Path(PROJECT_ROOT) / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json"
LEAST_BUDGET_SECONDS = 4 * 3600.0
MADE = Path("controls") / "made.json"


def made(var) -> dict:
    path = Path(var) / MADE if var is not None else None
    if path is None or not path.is_file():
        return {}
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")).get("made") or {})
    except (OSError, ValueError, AttributeError):
        return {}


def _record_made(var, name: str, campaign_id: str) -> None:
    if var is None:
        return
    known = made(var)
    if known.get(name) == campaign_id:
        return
    known[name] = campaign_id
    path = Path(var) / MADE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"contract": "gsd-controls-made-1", "made": known}, indent=1, sort_keys=True)
                         + "\n", encoding="utf-8")
    temporary.replace(path)


def load_criterion(path: Path = CRITERION) -> dict | None:
    path = Path(path)
    from graph_scale_dynamics.resources import committed
    return committed.read(path) if path.is_file() else None


def laws(criterion: dict) -> list[dict]:
    from graph_scale_dynamics.dsl.dsl import fingerprint
    return [dict(law, candidate_id=fingerprint(law["spec"])) for law in criterion["laws"]]


def campaign_spec(criterion: dict, base: dict | None = None) -> dict:
    from graph_scale_dynamics.decisions.engine import Policy
    from graph_scale_dynamics.scheduling.ladder_spec import engine_ladder
    from graph_scale_dynamics.scheduling.limits import units_for_seconds
    spec = json.loads(json.dumps(base if base is not None else json.loads(BASE_SPEC.read_text(encoding="utf-8"))))
    spec["proposer"] = {"pool_min": 1}
    spec["search_policy"] = {"contract": "gsd-hand-1", "kind": "hand"}
    policy_of_base = Policy.from_spec(spec)
    sizes = [int(n) for n in criterion["rungs"]]
    least = units_for_seconds(spec, LEAST_BUDGET_SECONDS)
    engine_ladder(spec, base_sizes=sizes, deep_sizes=[], seeds=int(criterion["seeds"]),
                  budgets={n: max(policy_of_base.work_budget(n), least) for n in sizes})
    policy = spec["policy"]
    policy["initial_sweeps_multiplier"] = {str(n): 4 for n in sizes}
    policy["max_sweeps_multiplier"] = 16
    known = laws(criterion)
    spec["sampling_contract"] = dict(spec.get("sampling_contract") or {}, max_sweeps_multiplier=16,
                                     given_start_by_law={law["candidate_id"]: dict(law["given_start"])
                                                          for law in known})
    spec["sampling_contract"].pop("given_start", None)
    spec["operator_whitelist"] = sorted({term["op"] for law in known for term in law["spec"]["terms"]})
    spec["name"] = criterion.get("campaign_name") or NAME
    spec["complexity_budget"] = 12
    spec["max_active_candidates"] = len(known)
    spec["controls_criterion"] = criterion["contract"]
    spec["description"] = criterion.get("campaign_description") or (
        "The standing controls (542): laws whose answer is known, each with a chain started at the answer, at "
        "every size of the survey's ladder, three seeds, the audit sample at 100% below 16,384 and the deep salt's "
        "0.5% from it (the build 648 review's L19), no proposals; every probe reads "
        "both chains. The criterion, committed before any run: graph_scale_dynamics/resources/readings/controls_criterion_2.json; judge it "
        "with tools/positive_control.py check <bundle>.")
    if criterion.get("capped_at"):
        spec["controls_capped_at"] = int(criterion["capped_at"])
        spec["description"] += (f" In this study to N={int(criterion['capped_at']):,}, its own top: past it the controls "
                                "read nothing the study asks (592).")
    return spec


def exempt_from_the_bar(spec: dict) -> dict:
    policy = ((spec.setdefault("engine", {})).setdefault("policy", {}))
    policy["promising_bar"] = False
    return spec


def study_top(repo) -> int | None:
    tops = []
    for campaign in repo.all_campaigns():
        spec = campaign.get("spec") or {}
        if spec.get("controls_criterion") or "controls" in str(spec.get("name") or ""):
            continue
        ladder = [int(n) for n in spec.get("ladder") or []]
        if ladder:
            tops.append(max(ladder))
    return max(tops) if tops else None


def capped(criterion: dict | None, top: int | None) -> dict | None:
    if not criterion or not top:
        return criterion
    rungs = [int(n) for n in criterion["rungs"] if int(n) <= int(top)]
    if not rungs or len(rungs) == len(criterion["rungs"]):
        return criterion
    return dict(criterion, rungs=rungs, capped_at=int(top))


def existing(repo, name: str = NAME) -> list[dict]:
    return [c for c in repo.all_campaigns() if str((c.get("spec") or {}).get("name")) == name]


def _insert_laws(repo, campaign_id: str, spec: dict, criterion: dict, *, only_missing: bool) -> int:
    from graph_scale_dynamics.domain.model import CandidateState
    from graph_scale_dynamics.dsl import dsl
    held = {str(c["candidate_id"]) for c in repo.candidates(campaign_id)} if only_missing else set()
    added = 0
    for law in laws(criterion):
        if law["candidate_id"] in held:
            continue
        raw = law["spec"]
        problems = dsl.validate(raw, complexity_budget=spec["complexity_budget"],
                                operator_whitelist=spec["operator_whitelist"])
        if problems:
            raise ValueError(f"control law {law['label']} is not a valid law: {problems}")
        normalized = dsl.normalize(raw)
        repo.insert_candidate(law["candidate_id"], campaign_id, normalized, normalized["dynamics"]["kind"],
                              dsl.complexity(normalized), CandidateState.PROPOSED.value)
        added += 1
    return added


def ensure(repo, *, criterion: dict | None = None, say=print, var=None) -> dict:
    criterion = capped(criterion if criterion is not None else load_criterion(), study_top(repo))
    return ensure_control_campaign(repo, criterion, contract=STANDING_CONTROLS_CONTRACT,
                                   reason="the standing controls (542)", search_seed=542, say=say, render=render,
                                   var=var)


def a_study_s_folder(repo) -> bool:
    from graph_scale_dynamics.operations.study import quadrant_label
    return any(quadrant_label(c.get("spec") or {}) for c in repo.all_campaigns())


def ensure_control_campaign(repo, criterion: dict | None, *, contract: str, reason: str, search_seed: int,
                            say=print, render=None, var=None) -> dict:
    from graph_scale_dynamics.operations import campaign_control as control
    if criterion is None:
        return {"contract": contract, "created": None, "why": "no committed criterion"}
    name = criterion.get("campaign_name") or NAME
    found = existing(repo, name)
    if found:
        campaign = found[0]
        _record_made(var, name, str(campaign["campaign_id"]))
        if str(campaign.get("status")) == "archived":
            return {"contract": contract, "created": None, "archived": str(campaign["campaign_id"]),
                    "why": "archived by the operator; given no laws"}
        added = _insert_laws(repo, str(campaign["campaign_id"]), campaign.get("spec") or {}, criterion,
                             only_missing=True)
        return {"contract": contract, "created": None, "added": added,
                "campaign_id": str(campaign["campaign_id"]), "why": "already there"}
    if name in made(var):
        return {"contract": contract, "created": None, "deleted": made(var)[name],
                "why": "deleted by the operator; not made again"}
    if not a_study_s_folder(repo):
        return {"contract": contract, "created": None, "why": "not a study's folder"}
    spec = exempt_from_the_bar(campaign_spec(criterion))
    judge = judged_in_the_study(var, name)
    if judge:
        spec["controls_judged_by"] = judge
    created = control.create_campaign(repo, spec, reason=reason, search_seed=search_seed)
    campaign_id = str(created["campaign_id"])
    _record_made(var, name, campaign_id)
    _insert_laws(repo, campaign_id, spec, criterion, only_missing=False)
    result = {"contract": contract, "created": campaign_id, "laws": len(criterion["laws"]),
              "rungs": criterion["rungs"], "criterion": criterion["contract"]}
    for line in (render or (lambda _: []))(result):
        say(line)
    return result


def judged_in_the_study(var, name: str) -> str | None:
    from graph_scale_dynamics.operations import study_design, study_record
    from graph_scale_dynamics.research.control_verdict import for_campaign, judged_by
    record = study_record.read(var)
    if record is None:
        return None
    try:
        design = study_design.design_for(None, str(record["study"]))
    except ValueError:
        return None
    criterion = judged_by(design)
    return str(design["controls_criterion"]) if criterion and for_campaign(criterion, name) else None


def repair(repo, var=None) -> dict:
    return ensure(repo, say=lambda *_: None, var=var)


def render(result: dict) -> list[str]:
    if result.get("deleted"):
        return [f"controls: Campaign {result['deleted']}, the standing controls, was deleted in this folder; "
                f"not made again"]
    if result.get("added"):
        return [f"controls: Campaign {result['campaign_id']}, the standing controls, given the {result['added']} "
                f"of its laws it lacked"]
    if not result.get("created"):
        return []
    rungs = result["rungs"]
    return [f"controls: created Campaign {result['created']}, the standing controls: {result['laws']} laws whose "
            f"answer is known, N={rungs[0]:,} to {rungs[-1]:,}, each with a chain at its answer "
            f"(graph_scale_dynamics/resources/readings/controls_criterion_2.json)"]
