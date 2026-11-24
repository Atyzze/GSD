from __future__ import annotations

import json
from itertools import product
from pathlib import Path

from graph_scale_dynamics.domain.model import utc_now
from graph_scale_dynamics.operations import study_record

STUDY_CONTRACT = "study-1"
KNOWN_RESULT_AFTER = 100
DEFAULT_LAW_BUDGET = 10000
LAW_BUDGET_PREFIX = "law_budget:"
BUDGET_REACHED_PREFIX = "law_budget_reached:"
DONE = "done"
AT_BUDGET = "at its law budget"

AXES = {
    "zero_temperature": {"values": (True, False),
                         "label": {True: "zero temperature", False: "finite temperature",
                                   "drawn": "zero or finite temperature, drawn per law"}},
    "dense_cap": {"values": (16.0, 32.0), "label": {16.0: "mean degree to 16", 32.0: "mean degree to 32"}},
}
DEFAULT_STUDY = ("zero_temperature", "dense_cap")
DRAWN = "drawn"
QUADRANT_PREFIX = "a quadrant of the study"


def _set_axis(spec: dict, axis: str, value) -> None:
    if axis == "zero_temperature":
        policy = dict(spec.get("search_policy") or {})
        drawn = [False, True] if value == DRAWN else [bool(value)]
        policy["grid"] = dict(policy.get("grid") or {}, zero_temperature=drawn)
        spec["search_policy"] = policy
    elif axis == "dense_cap":
        engine = dict(spec.get("engine") or {})
        engine["policy"] = dict(engine.get("policy") or {}, dense_cap=float(value))
        spec["engine"] = engine
        limits = dict(spec.get("limits") or {})
        limits["mean_degree_window"] = dict(limits.get("mean_degree_window") or {}, max=float(value))
        spec["limits"] = limits
    else:
        raise ValueError(f"no such axis {axis!r}; the axes are {', '.join(sorted(AXES))}")


def set_mean_degree_window(spec: dict, low: float, high: float) -> None:
    _set_axis(spec, "dense_cap", float(high))
    limits = dict(spec.get("limits") or {})
    limits["mean_degree_window"] = dict(limits.get("mean_degree_window") or {}, min=float(low))
    spec["limits"] = limits


def quadrant_specs(base_spec: dict, axes=DEFAULT_STUDY) -> list[tuple[str, dict]]:
    from copy import deepcopy

    axes = tuple(axes)
    for axis in axes:
        if axis not in AXES:
            raise ValueError(f"no such axis {axis!r}; the axes are {', '.join(sorted(AXES))}")
    out = []
    for values in product(*(AXES[axis]["values"] for axis in axes)):
        spec = deepcopy(base_spec)
        for key in ("campaign_provenance_contract", "search_policy_contract", "resource_policy_contract"):
            spec.pop(key, None)
        for axis, value in zip(axes, values, strict=True):
            _set_axis(spec, axis, value)
        label = ", ".join(AXES[axis]["label"][value] for axis, value in zip(axes, values, strict=True))
        spec["name"] = f"{spec.get('name') or 'survey'}: {label}"
        spec["description"] = f"{QUADRANT_PREFIX} ({label}); {spec.get('description') or ''}".strip()
        out.append((label, spec))
    return out


def quadrant_of(spec: dict) -> dict:
    from graph_scale_dynamics.decisions.engine import Policy

    grid = ((spec or {}).get("search_policy") or {}).get("grid") or {}
    temperature = grid.get("zero_temperature")
    if temperature is None:
        from graph_scale_dynamics.operations.study_design import axes_of
        temperature = (axes_of(spec) or {}).get("zero_temperature")
    if isinstance(temperature, list) and len(temperature) == 1:
        temperature = bool(temperature[0])
    elif isinstance(temperature, list) and {bool(v) for v in temperature} == {True, False}:
        temperature = DRAWN
    values = {"zero_temperature": temperature, "dense_cap": float(Policy.from_spec(spec or {}).dense_cap)}
    labels = []
    for axis in DEFAULT_STUDY:
        value = values[axis]
        known = AXES[axis]["label"].get(value) if isinstance(value, (bool, float, str)) else None
        labels.append(known or (f"{axis}: {value}" if value is not None else f"{axis}: not set"))
    return {**values, "label": ", ".join(labels)}


def quadrant_label(spec: dict) -> str | None:
    if not str((spec or {}).get("description") or "").startswith(QUADRANT_PREFIX):
        return None
    return quadrant_of(spec)["label"]


def available_studies(tree=None) -> dict:
    from graph_scale_dynamics.operations import study_design
    return {"designed": study_design.designed_studies(tree)}


def _available_line(tree=None) -> str:
    designed = available_studies(tree)["designed"]
    return f"design{'s' if len(designed) > 1 else ''} {', '.join(designed)}" if designed else "none"


class UnknownStudy(ValueError):
    pass


def instrument_refusal(root, study: str | None) -> str | None:
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    from graph_scale_dynamics.operations import study_design
    if study is None or not study_record.valid_id(str(study)):
        return None
    design = study_design.design_for(root, str(study))
    designed_on = ((design or {}).get("instrument") or {}).get("analysis")
    if designed_on is None or designed_on == ANALYSIS_VERSION:
        return None
    return (f"refusing study {study}: it was designed on {designed_on} and this tree measures with "
            f"{ANALYSIS_VERSION}, so its readings here would not be its own. Its folder stays on the build "
            "it runs; a study on this tree needs a design made on this tree's analysis")


def study_choice(wanted: str | None, *, spec=None, repo=None, var=None, root=None, starting: bool) -> str | None:
    from graph_scale_dynamics.operations import study_design
    if starting:
        recorded = study_record.read(var)
        if recorded is not None and wanted is not None and str(wanted) != recorded["study"]:
            return (f"refusing --study {wanted}: this folder's first start chose study {recorded['study']} "
                    f"({study_record.path(var)}); start study {wanted} in a new folder")
        if wanted is None or (str(wanted) == study_record.DEFAULT and not spec):
            return None
        if spec:
            return ("refusing --study with --spec: a named spec starts one campaign, not a study; start either one in "
                    "a new folder")
        if not study_record.valid_id(wanted):
            return f"refusing --study {wanted!r}: a study id is letters, digits, '.', '_' and '-'"
        if study_design.design_for(root, wanted) is None:
            return (f"refusing --study {wanted}: this tree holds no design for it "
                    f"(graph_scale_dynamics/resources/readings/study_{wanted}_design.json); it holds "
                    f"{_available_line(root)}. `--study {study_record.DEFAULT}`, or no --study, starts the default "
                    "study. Nothing was created.")
        return instrument_refusal(root, wanted)
    try:
        study_record.ensure(var, repo)
        current = study_record.study_id(var, repo)
    except ValueError as error:
        return f"refusing to start: {error}"
    if wanted is not None and str(wanted) != current:
        return (f"refusing --study {wanted}: this folder is study {current} ({study_record.path(var)}), and a folder "
                f"is one study for its whole life; start study {wanted} in a new folder")
    return instrument_refusal(root, current)


def default_study_note(tree=None) -> str:
    return (f"study {study_record.DEFAULT}: no --study given, so the default study: "
            "533's first split, zero or finite temperature crossed with a mean-degree cap of 16 or 32, "
            f"{DEFAULT_LAW_BUDGET:,} laws each. Another start instead, in a new folder: "
            "`uv run python main.py run --study <id>` for a committed study (this tree holds "
            f"{_available_line(tree)}), or `uv run python main.py run --spec <file>` (one campaign from your spec; "
            "start from a copy of graph_scale_dynamics/resources/configs/campaign_engine_survey.json)")


def start_study(repo, spec: dict, *, search_seed=None, default: bool = True,
                budget: int | None = DEFAULT_LAW_BUDGET, log=print, var=None, tree=None,
                study: str | None = None) -> str:
    import secrets

    from graph_scale_dynamics.operations import campaign_control as control

    recorded = study_record.read(var)
    if recorded is not None and not (getattr(repo, "all_campaigns", None) or list)() and study_record.forget_unmade(var):
        recorded = None
    if study is None and default and recorded is not None and recorded.get("kind") != study_record.NAMED_SPEC:
        study = recorded["study"]
    digest = spec_digest(spec)
    if study is not None and not default:
        raise UnknownStudy("a named spec is one campaign, not a study: start either --study or --spec, not both")
    if study is not None and str(study) != study_record.DEFAULT:
        study = str(study)
        if not study_record.valid_id(study):
            raise UnknownStudy(f"{study!r} is not a study id (letters, digits, '.', '_', '-')")
        from graph_scale_dynamics.operations import study_design
        design = study_design.design_for(tree, study)
        if design is None:
            raise UnknownStudy(f"--study {study}: this tree holds no design for it "
                               f"(graph_scale_dynamics/resources/readings/study_{study}_design.json); it holds "
                               f"{_available_line(tree)}. Nothing was created.")
        study_record.write(var, study=study, kind=study_record.DESIGNED, chosen_by=study_record.BY_FLAG,
                           source={"design": design["path"], "sha256": design["sha256"]}, search_seed=search_seed,
                           spec_sha256=digest, log=log)
        record_note(var, note_for(tree, study, labels=[c["label"] for c in design["campaigns"]]), log=log)
        first = study_design.start(repo, design, spec, var=var, tree=tree, search_seed=search_seed, log=log,
                                   made=made(repo, study))
        study_record.finish(var, kind=study_record.DESIGNED)
        return first
    if default:
        study_record.write(var, study=study_record.DEFAULT, kind=study_record.DEFAULT,
                           chosen_by=study_record.BY_FLAG if study is not None else study_record.BY_DEFAULT,
                           search_seed=search_seed, spec_sha256=digest, log=log)
    else:
        study_record.write(var, study=study_record.NAMED_SPEC, kind=study_record.NAMED_SPEC,
                           chosen_by=study_record.BY_SPEC, search_seed=search_seed, spec_sha256=digest, log=log)
    if default:
        spec = on_the_let_through_rule(spec, log=log)
    specs = quadrant_specs(spec) if default else [("the named spec", spec)]
    if default:
        record_note(var, note_for(tree, study_record.DEFAULT, labels=[label for label, _ in specs]), log=log)
    reason = ("the study's first quadrants (533's G and N)" if default
              else "the campaign the named spec asks for")
    first, have = None, made(repo, None) if default else {}
    for index, (label, quadrant) in enumerate(specs):
        seed = (int(search_seed) + index) if search_seed is not None else secrets.randbits(63)
        campaign_id = have.get(label)
        if campaign_id is None:
            created = control.create_campaign(repo, quadrant, reason=f"{reason}: {label}", search_seed=seed)
            campaign_id = str(created["campaign_id"])
            mode = "reproducible" if search_seed is not None else "cryptographically random"
            log(f"created Campaign {campaign_id} ({label}) as a new immutable experiment; search seed {seed} ({mode})"
                + (f"; law budget {budget:,}" if default and budget else ""))
        first = first or campaign_id
        if default and budget:
            budget_once(repo, campaign_id, budget, reason="the study's first law budget")
    if default:
        log(default_study_note(tree))
    study_record.finish(var, kind=study_record.DEFAULT if default else study_record.NAMED_SPEC)
    return str(first)


def spec_digest(spec: dict) -> str:
    import hashlib
    from graph_scale_dynamics.scheduling.provenance import freeze_campaign_spec
    text = json.dumps(freeze_campaign_spec(spec), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def made(repo, study: str | None) -> dict:
    out: dict = {}
    for campaign in (getattr(repo, "all_campaigns", None) or list)():
        spec, campaign_id = campaign.get("spec") or {}, str(campaign["campaign_id"])
        design = spec.get("study_design") or {}
        if study is not None and str(design.get("study")) == str(study):
            out[int(design["campaign"])] = campaign_id
        elif study is None and not design and quadrant_label(spec):
            out[quadrant_label(spec)] = campaign_id
    return out


def budget_once(repo, campaign_id: str, laws: int, *, reason: str) -> None:
    events = getattr(repo, "campaign_events", None)
    if not any(e.get("event_type") == "campaign_law_budget_changed" for e in (events(campaign_id) if events else [])):
        set_law_budget(repo, campaign_id, laws, reason=reason)


def repair(repo, *, var=None, tree=None) -> dict | None:
    from graph_scale_dynamics.domain.version import BUILD_NUMBER
    record = study_record.read(var)
    if study_record.complete(record) or record.get("kind") == study_record.NAMED_SPEC or not repo.all_campaigns():
        return None
    if int(record.get("build_number") or 0) != int(BUILD_NUMBER):
        return {"study": record["study"], "made": None, "lines": [
            f"its first start was on build {record.get('build_number')} and this is {BUILD_NUMBER}: start this folder "
            f"on build {record.get('build_number')} to make the rest, or reset it"]}
    from graph_scale_dynamics.operations.campaign_control import shipped_spec
    from graph_scale_dynamics.scheduling.provenance import freeze_campaign_spec
    spec = freeze_campaign_spec(shipped_spec())
    if record.get("spec_sha256") and record["spec_sha256"] != spec_digest(spec):
        return {"study": record["study"], "made": None, "lines": [
            "its first start was from another base spec than this tree ships (sha256 "
            f"{str(record['spec_sha256'])[:12]}): start it from that spec to make the rest, or reset it"]}
    before, lines = {str(c["campaign_id"]) for c in repo.all_campaigns()}, []
    start_study(repo, spec, var=var, tree=tree, study=record["study"], search_seed=record.get("search_seed"),
                log=lines.append)
    return {"study": record["study"],
            "lines": [line for line in lines if line.startswith(("created Campaign", "completed Campaign"))],
            "made": sorted({str(c["campaign_id"]) for c in repo.all_campaigns()} - before, key=int)}


def render(out: dict | None) -> list[str]:
    if not out:
        return []
    return [f"study {out['study']}: its first start stopped part-way; this start made "
            + ("nothing" if out["made"] is None else f"the rest of it, campaign(s) {', '.join(out['made'])}"
               if out["made"] else "the laws its campaign lacked" if out["lines"] else "nothing new: it was whole")
            ] + out["lines"]


def note_for(tree=None, study: str | None = None, *, labels=()) -> str:
    from graph_scale_dynamics import PROJECT_ROOT
    tree = Path(tree or PROJECT_ROOT)
    try:
        register = json.loads((tree / "graph_scale_dynamics" / "resources" / "readings" / "studies.json").read_text(encoding="utf-8"))
        line = (next((s.get("notes") for s in register["studies"] if str(s.get("id")) == str(study)), None)
                if study not in (None, study_record.DEFAULT, study_record.NAMED_SPEC) else None)
        if line:
            return str(line)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return f"base {len(labels)} quadrant: " + "; ".join(labels)


def record_note(var, line: str, *, log=print) -> dict | None:
    return study_record.add_note(var, line, log=log)


def on_the_let_through_rule(spec: dict, *, log=print) -> dict:
    from copy import deepcopy

    from graph_scale_dynamics.decisions.gates import LET_THROUGH_RULE
    out = deepcopy(spec)
    engine = dict(out.get("engine") or {})
    engine["policy"] = dict(engine.get("policy") or {}, let_through_rule=LET_THROUGH_RULE,
                            known_result_after=KNOWN_RESULT_AFTER)
    out["engine"] = engine
    log("the let-through: every gate learns from this study's own decisions alone (784's rule); nothing is carried "
        "from another study")
    return out

def law_budget(repo, campaign_id: str) -> int | None:
    raw = str(repo.get_flag(f"{LAW_BUDGET_PREFIX}{campaign_id}", "") or "").strip()
    try:
        return max(0, int(raw)) if raw else None
    except ValueError:
        return None


def laws_held(repo, campaign_id: str) -> int:
    row = repo.conn.execute("SELECT COUNT(*) AS c FROM campaign_candidates WHERE campaign_id=?",
                            (str(campaign_id),)).fetchone()
    return int(row["c"] or 0) if row else 0


def budget_reached(repo, campaign_id: str) -> dict | None:
    raw = repo.get_flag(f"{BUDGET_REACHED_PREFIX}{campaign_id}", "")
    if not raw:
        return None
    try:
        record = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def set_law_budget(repo, campaign_id: str, laws: int | None, *,
                   reason: str = "the operator changed the campaign's law budget") -> dict:
    campaign_id = str(campaign_id)
    if repo.campaign(campaign_id) is None:
        return {"ok": False, "problem": f"unknown campaign {campaign_id!r}"}
    if laws is not None:
        try:
            laws = int(laws)
        except (TypeError, ValueError):
            return {"ok": False, "problem": f"{laws!r} is not a number of laws"}
        if laws < 1:
            return {"ok": False, "problem": "a law budget is at least one law; pause a campaign to stop it"}
    before = law_budget(repo, campaign_id)
    repo.set_flag(f"{LAW_BUDGET_PREFIX}{campaign_id}", "" if laws is None else str(laws))
    held = laws_held(repo, campaign_id)
    if budget_reached(repo, campaign_id) and (laws is None or held < laws):
        repo.set_flag(f"{BUDGET_REACHED_PREFIX}{campaign_id}", "")
    repo.record_campaign_event(campaign_id, "campaign_law_budget_changed", {
        "contract": STUDY_CONTRACT, "reason": reason, "from": before, "to": laws, "laws_held": held})
    return {"ok": True, "campaign_id": campaign_id, "law_budget": laws, "laws_held": held,
            "reading": ("no law budget: the campaign proposes for as long as it runs" if laws is None
                        else f"{held:,} of {laws:,} laws: " + ("room for more" if held < laws
                                                               else "it proposes no more"))}


def budget_room(repo, campaign_id: str, held: int) -> int | None:
    budget = law_budget(repo, campaign_id)
    if budget is None:
        return None
    room = budget - int(held)
    if room <= 0 and not budget_reached(repo, campaign_id):
        record = {"contract": STUDY_CONTRACT, "budget": budget, "laws_held": int(held), "at": utc_now(),
                  "reading": (f"{int(held):,} laws, the budget of {budget:,}: the campaign proposes no more; the "
                              "laws it holds go on being measured and its workers go to the campaigns still "
                              "under theirs")}
        repo.set_flag(f"{BUDGET_REACHED_PREFIX}{campaign_id}", json.dumps(record))
        repo.record_campaign_event(str(campaign_id), "campaign_law_budget_reached", record)
    return max(0, room)


def budget_state(repo, campaign_id: str, spec: dict | None = None) -> dict | None:
    budget = law_budget(repo, campaign_id)
    if budget is None:
        return None
    held = laws_held(repo, campaign_id)
    reached = budget_reached(repo, campaign_id)
    done = bool(reached) and not in_flight(repo, campaign_id)
    return {"law_budget": budget, "laws_held": held, "reached": bool(reached),
            "reached_at": (reached or {}).get("at"), "done": done,
            "state": DONE if done else (AT_BUDGET if reached else None)}


def in_flight(repo, campaign_id: str) -> bool:
    if repo.campaign_pending_work(str(campaign_id)):
        return True
    row = repo.conn.execute(
        "SELECT 1 FROM campaign_candidates WHERE campaign_id=? AND state IN "
        "('PROPOSED','VALIDATING','BASE_BLOCK_RUNNING','EXTENDING') LIMIT 1", (str(campaign_id),)).fetchone()
    if row is not None:
        return True
    row = repo.conn.execute(
        "SELECT 1 FROM engine_decisions_latest WHERE campaign_id=? AND action='hold' AND rule='deep_lane_full' "
        "LIMIT 1", (str(campaign_id),)).fetchone()
    return row is not None
