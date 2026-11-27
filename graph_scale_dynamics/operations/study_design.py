from __future__ import annotations

import hashlib
import json
import math
import random
from copy import deepcopy
from pathlib import Path

DESIGN_CONTRACT = "gsd-study-design-1"
STARTS_READING_KEYS = ("hold_structure", "lattice_chains_meet")
DESIGNS = Path("graph_scale_dynamics") / "resources" / "readings"
BLIND, AROUND, PERTURB, MAP, SEED = "blind", "around", "perturb", "map", "seed"
DEX = "dex"
NUDGE = 1.5
SIGNIFICANT_FIGURES = 4
TRIES = 50


def fresh(design: dict) -> bool:
    from graph_scale_dynamics.decisions.gates import LET_THROUGH_RULE
    return (design.get("engine") or {}).get("let_through_rule") == LET_THROUGH_RULE


def without_terms(design: dict, spec: dict, *, log=print) -> dict:
    left_out = sorted(str(op) for op in design.get("terms_left_out") or ())
    if not left_out:
        return spec
    whitelist = list(spec.get("operator_whitelist") or [])
    unknown = [op for op in left_out if op not in whitelist]
    if unknown:
        raise ValueError(f"study {design['study']} leaves out of its pool terms the language does not have: "
                         + ", ".join(unknown))
    out = deepcopy(spec)
    out["operator_whitelist"] = [op for op in whitelist if op not in left_out]
    log(f"study {design['study']} draws from {len(out['operator_whitelist'])} terms, {', '.join(left_out)} out of "
        "its pool: every law drawn runs, and its law budget is the laws that run")
    return out


def design_path(tree: Path, study_id: str) -> Path:
    return Path(tree) / DESIGNS / f"study_{study_id}_design.json"


def designed_studies(tree: Path | None = None) -> list[str]:
    from graph_scale_dynamics import PROJECT_ROOT
    root = Path(tree) if tree is not None else Path(PROJECT_ROOT)
    found = (p.name[len("study_"):-len("_design.json")] for p in (root / DESIGNS).glob("study_*_design.json"))
    return sorted(found, key=lambda s: (not s.isdigit(), int(s) if s.isdigit() else 0, s))


def design_for(tree: Path | None, study_id: str) -> dict | None:
    from graph_scale_dynamics import PROJECT_ROOT
    tree = Path(tree) if tree is not None else Path(PROJECT_ROOT)
    study_id = str(study_id)
    path = design_path(tree, study_id)
    if not path.is_file():
        return None
    raw = path.read_bytes()
    design = json.loads(raw)
    if design.get("contract") != DESIGN_CONTRACT or str(design.get("study")) != study_id:
        raise ValueError(f"{path} is not a study design for study {study_id}")
    return dict(design, sha256=hashlib.sha256(raw).hexdigest(), path=str(path.relative_to(tree)))


def _stream(*parts) -> random.Random:
    return random.Random(int(hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).hexdigest(), 16))


def neighbours(spec: dict, law: str, count: int, *, salt: str, complexity_budget: int,
               whitelist: list[str] | None) -> list[dict]:
    from graph_scale_dynamics.dsl.dsl import fingerprint, validate
    out, seen = [], {fingerprint(spec)}
    for index in range(count):
        for attempt in range(TRIES):
            rng = _stream(salt, law, index, attempt)
            child = deepcopy(spec)
            for term in child["terms"]:
                factor = math.exp(rng.uniform(-math.log(NUDGE), math.log(NUDGE)))
                term["coeff"]["c0"] = float(f"{float(term['coeff']['c0']) * factor:.{SIGNIFICANT_FIGURES}g}")
            if not validate(child, complexity_budget=complexity_budget, operator_whitelist=whitelist) \
                    and fingerprint(child) not in seen:
                seen.add(fingerprint(child))
                out.append(child)
                break
        else:
            raise ValueError(f"no valid neighbour {index} of {law[:10]} in {TRIES} draws")
    return out


def around_laws(design: dict, survey: dict, tree: Path) -> list[dict]:
    from graph_scale_dynamics.dsl.dsl import fingerprint
    around = design["around"]
    from graph_scale_dynamics.resources import committed
    source = json.loads(committed.resolve(around["source"], tree).read_text(encoding="utf-8"))
    by_label = {law["label"]: law for law in source["laws"]}
    holders = [by_label[label] for label in around["holders"]]
    total = int(around["laws"])
    counts = [total // len(holders) + (1 if i < total % len(holders) else 0) for i in range(len(holders))]
    laws = []
    for holder, count in zip(holders, counts, strict=True):
        for index, spec in enumerate(neighbours(holder["spec"], holder["candidate_id"], count,
                                                salt=f"study {design['study']}",
                                                complexity_budget=int(survey.get("complexity_budget") or 6),
                                                whitelist=survey.get("operator_whitelist")), start=1):
            laws.append({"label": f"{holder['label']}~{index}", "of": holder["candidate_id"], "spec": spec,
                         "candidate_id": fingerprint(spec)})
    return laws


def perturb_laws(design: dict, survey: dict, tree: Path) -> list[dict]:
    from graph_scale_dynamics.dsl.dsl import fingerprint, normalize
    from graph_scale_dynamics.research import perturb as P
    from graph_scale_dynamics.resources import committed
    plan = design["perturb"]
    source = json.loads(committed.resolve(plan["source"], tree).read_text(encoding="utf-8"))
    laws = []
    for holder in source["holders"]:
        if fingerprint(holder["spec"]) != holder["candidate_id"]:
            raise ValueError(f"holder {holder['label']}'s law is not the law {holder['candidate_id'][:12]} it names")
        laws.append({"label": holder["label"], "of": holder["candidate_id"], "radius": 0.0,
                     "spec": normalize(holder["spec"]), "candidate_id": holder["candidate_id"]})
        for found in P.variants(holder["spec"], holder["candidate_id"], salt=f"study {design['study']}",
                                complexity_budget=int(survey.get("complexity_budget") or 6),
                                whitelist=survey.get("operator_whitelist"), radii=tuple(plan["radii"]),
                                per_radius=int(plan["per_radius"])):
            laws.append({"label": f"{holder['label']}~{found['radius']:g}~{found['index']}",
                         "of": holder["candidate_id"], "radius": found["radius"], "spec": found["spec"],
                         "candidate_id": found["candidate_id"], "changes": found["changes"]})
    return laws


def map_holders(design: dict, tree: Path) -> list[dict]:
    from graph_scale_dynamics.resources import committed
    source = json.loads(committed.resolve(design["map"]["source"], tree).read_text(encoding="utf-8"))
    return list(source["holders"])


def map_laws(design: dict, survey: dict, tree: Path) -> list[dict]:
    from graph_scale_dynamics.operations import study_map
    return study_map.designed_points(design["map"], map_holders(design, tree), survey)


def fixed_laws(design: dict, entry: dict, survey: dict, tree: Path) -> list[dict]:
    if entry["kind"] == AROUND:
        return around_laws(design, survey, tree)
    if entry["kind"] == PERTURB:
        return perturb_laws(design, survey, tree)
    if entry["kind"] == MAP:
        return map_laws(design, survey, tree)
    return []


def axes_of(spec: dict) -> dict | None:
    designed = (spec or {}).get("study_design") or {}
    path = designed.get("design")
    if not path:
        return None
    from graph_scale_dynamics.resources import committed
    try:
        return dict(json.loads(committed.resolve(path).read_text(encoding="utf-8")).get("axes") or {})
    except (OSError, ValueError):
        return None


def laws_sha256(laws: list[dict]) -> str:
    return hashlib.sha256("\n".join(sorted(law["candidate_id"] for law in laws)).encode("utf-8")).hexdigest()


def stratified(design: dict, entry: dict) -> bool:
    return bool(design.get("strata")) and entry.get("kind") == BLIND and entry.get("stratified", True) is not False


def _merge_grid(spec: dict, keys: dict) -> None:
    policy = dict(spec.get("search_policy") or {})
    policy["grid"] = dict(policy.get("grid") or {}, **deepcopy(keys))
    spec["search_policy"] = policy


def campaign_spec(design: dict, base: dict, entry: dict, index: int) -> dict:
    from graph_scale_dynamics.decisions.engine import Policy
    from graph_scale_dynamics.operations.study import QUADRANT_PREFIX, _set_axis
    from graph_scale_dynamics.scheduling.ladder_spec import engine_ladder
    spec = deepcopy(base)
    for key in ("campaign_provenance_contract", "search_policy_contract", "resource_policy_contract"):
        spec.pop(key, None)
    for axis, value in design["axes"].items():
        _set_axis(spec, axis, value)
    if stratified(design, entry):
        from graph_scale_dynamics.research.strata import GRID_STRATA
        _merge_grid(spec, {GRID_STRATA: design["strata"]})
    if entry.get("grid"):
        _merge_grid(spec, entry["grid"])
    if design.get("engine") or entry.get("engine"):
        spec["engine"] = dict(spec.get("engine") or {},
                              policy={**((spec.get("engine") or {}).get("policy") or {}), **(design.get("engine") or {}),
                                      **(entry.get("engine") or {})})
    if design.get("limits"):
        spec["limits"] = dict(spec.get("limits") or {}, **design["limits"])
    policy = Policy.from_spec(spec)
    base_sizes, deep_sizes = [int(n) for n in design["ladder"]["base"]], [int(n) for n in design["ladder"]["deep"]]
    budgets = {int(n): int(units) for n, units in design["ladder"].get("budgets") or []}
    engine_ladder(spec, base_sizes=base_sizes, deep_sizes=deep_sizes, seeds=int(design["ladder"]["seeds"]),
                  budgets={n: budgets.get(n, policy.work_budget(n)) for n in base_sizes + deep_sizes},
                  audit_fraction=float(policy.audit_fraction))
    spec["budgets"] = dict(spec.get("budgets") or {}, max_n=max(base_sizes + deep_sizes))
    sampling = dict(spec.get("sampling_contract") or {})
    for key in ("given_start", "given_start_by_law", "given_start_rule", "given_starts"):
        sampling.pop(key, None)
    if not design.get("starts"):
        raise ValueError(f"study {design.get('study')}'s design names no starts: a design lists its starts, "
                         "and the start read from the null atlas left at 786")
    sampling["given_starts"] = [dict(start) for start in design["starts"]]
    for key in STARTS_READING_KEYS:
        sampling.pop(key, None)
        if key in (design.get("starts_reading") or {}):
            sampling[key] = bool(design["starts_reading"][key])
    spec["sampling_contract"] = sampling
    label = entry["label"]
    spec["name"] = f"study {design['study']}: {label}"
    spec["description"] = (f"{QUADRANT_PREFIX} ({label}); study {design['study']} ({design['path']}): "
                           f"{design['question']}")
    spec["study_design"] = {"contract": DESIGN_CONTRACT, "study": str(design["study"]), "design": design["path"],
                            "design_sha256": design["sha256"], "campaign": index, "kind": entry["kind"]}
    if design.get("strata"):
        spec["study_design"]["stratified"] = stratified(design, entry)
    if entry.get("arm"):
        spec["study_design"]["arm"] = str(entry["arm"])
    if entry.get("group"):
        spec["study_design"]["group"] = str(entry["group"])
    if entry["kind"] in (AROUND, PERTURB, MAP, SEED):
        spec["proposer"] = {"pool_min": 1}
        spec["search_policy"] = {"contract": "gsd-hand-1", "kind": "hand"}
    return spec


def entry_of(design: dict, index: int) -> dict:
    campaigns = design["campaigns"]
    if 0 <= int(index) < len(campaigns):
        return campaigns[int(index)]
    if int(index) == len(campaigns) and design.get(DEX):
        return design[DEX]
    raise ValueError(f"study {design.get('study')}'s design has no campaign {index}")


def dex_entry(design: dict | None) -> dict | None:
    found = (design or {}).get(DEX)
    return dict(found) if isinstance(found, dict) and found.get("kind") == SEED else None


def dex_search_seed(study: str) -> int:
    return int(hashlib.sha256(f"{study}:dex".encode("utf-8")).hexdigest(), 16) % (2 ** 63)


def dex_campaign(repo, study: str, *, tree=None, log=print) -> str:
    from graph_scale_dynamics import PROJECT_ROOT
    from graph_scale_dynamics.operations import campaign_control as control
    tree = Path(tree) if tree is not None else Path(PROJECT_ROOT)
    design = design_for(tree, str(study))
    entry = dex_entry(design)
    if entry is None:
        raise ValueError(f"study {study}'s design has no seeded campaign and makes none for a dex: a seed goes into "
                         "a study designed for one")
    base = json.loads((tree / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json")
                      .read_text(encoding="utf-8"))
    spec = campaign_spec(design, without_terms(design, base, log=lambda *_a: None), entry, len(design["campaigns"]))
    spec["study_design"]["dex"] = True
    made = control.create_campaign(repo, spec, search_seed=dex_search_seed(str(study)),
                                   reason=f"study {study} ({design['path']}): {entry['label']}")
    log(f"created Campaign {made['campaign_id']} ({entry['label']}), study {study}: the laws of the first dex read in")
    return str(made["campaign_id"])


def seed_of(design: dict, index: int, search_seed=None) -> int | None:
    fixed = design.get("search_seeds")
    if fixed:
        if len(fixed) != len(design["campaigns"]):
            raise ValueError(f"study {design.get('study')}'s design fixes {len(fixed)} search seeds for "
                             f"{len(design['campaigns'])} campaigns: one each, or none")
        if search_seed is not None and int(search_seed) != int(fixed[0]):
            raise ValueError(f"study {design.get('study')} grows the same laws in every folder: its design fixes its "
                             "search seeds, and --search-seed would draw other laws")
        return int(fixed[index])
    return None if search_seed is None else int(search_seed) + index


def start(repo, design: dict, spec: dict, *, var=None, tree=None, search_seed=None, budget: int | None = None,
          log=print, made: dict | None = None) -> str:
    import secrets

    from graph_scale_dynamics import PROJECT_ROOT
    from graph_scale_dynamics.domain.model import CandidateState
    from graph_scale_dynamics.dsl import dsl
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations.study import budget_once
    tree = Path(tree) if tree is not None else Path(PROJECT_ROOT)
    if not fresh(design):
        raise ValueError(f"study {design['study']}'s design does not run on the let-through rule: every "
                         "design learns its gates from its own laws alone (engine.let_through_rule)")
    spec = without_terms(design, spec, log=log)
    planned = []
    for index, entry in enumerate(design["campaigns"]):
        campaign = campaign_spec(design, spec, entry, index)
        laws = fixed_laws(design, entry, campaign, tree)
        if laws and laws_sha256(laws) != design[entry["kind"]]["laws_sha256"]:
            raise ValueError("the laws around the holders are not the ones the design committed: this tree draws "
                             "them differently, so the study would not be the one it describes")
        planned.append((index, entry, campaign, laws))
    if design.get("groups"):
        from graph_scale_dynamics.scheduling import work_groups
        if not work_groups.shares(repo):
            work_groups.set_shares(repo, design["groups"])
    first = None
    for index, entry, campaign, laws in planned:
        seed = seed_of(design, index, search_seed)
        if seed is None:
            seed = secrets.randbits(63)
        campaign_id = (made or {}).get(index)
        if campaign_id is None:
            created = control.create_campaign(repo, campaign, search_seed=seed,
                                              reason=f"study {design['study']} ({design['path']}): {entry['label']}")
            campaign_id = str(created["campaign_id"])
        first = first or campaign_id
        for law in laws:
            normalized = dsl.normalize(law["spec"])
            repo.insert_candidate(law["candidate_id"], campaign_id, normalized, normalized["dynamics"]["kind"],
                                  dsl.complexity(normalized), CandidateState.PROPOSED.value)
        laws_budget = int(budget if budget is not None else design["law_budget"])
        if entry["kind"] == BLIND and laws_budget:
            budget_once(repo, campaign_id, laws_budget, reason=f"study {design['study']}'s law budget")
        if entry["kind"] == MAP:
            from graph_scale_dynamics.operations import study_map
            study_map.begin(repo, str(design["study"]), campaign_id, design["map"], map_holders(design, tree), campaign)
        if index in (made or {}):
            continue
        log(f"created Campaign {campaign_id} ({entry['label']}), study {design['study']}: "
            + (f"{len(laws):,} laws around the design's holders" if laws else
               "empty until a bundle seeds it (the Map page)" if entry["kind"] == SEED else
               f"drawn blind, law budget {laws_budget:,}")
            + f"; {', '.join(f'{k} {v}' for k, v in design['axes'].items())}; to N={campaign['budgets']['max_n']:,}; "
            + (f"chains from empty, {', '.join(start['name'] for start in design['starts'])}"
               if design.get("starts") else "each law with a chain from a shape at the atlas's degree")
            + f"; search seed {seed}")
    if design.get("focus"):
        from graph_scale_dynamics.operations import focus
        focus.begin(repo, str(design["study"]), tree=tree)
    return str(first)
