from __future__ import annotations

import re

from graph_scale_dynamics.domain.model import JobKind, job_id as make_job_id
from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.scheduling.limits import limits, mean_degree_cap_armed, work_budget, work_unit
from graph_scale_dynamics.scaleflow.one_shot import ONE_SHOT_CONTRACT
from graph_scale_dynamics.engine.engine import ENGINE_VERSION


def initial_sweeps_multiplier(spec: dict, n: int) -> int:
    policy = (spec or {}).get("policy") or {}
    declared = policy.get("initial_sweeps_multiplier")
    if declared is None:
        return 1
    if isinstance(declared, dict):
        value = declared.get(str(int(n)), 1)
    else:
        value = declared
    try:
        if isinstance(value, bool):
            return 1
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def resolve_given_start(campaign_spec: dict, n, candidate_id: str | None = None,
                         candidate_spec: dict | None = None) -> dict | None:
    starts = given_starts(campaign_spec, n, candidate_id, candidate_spec)
    if starts is not None:
        return starts[0]
    sampling = (campaign_spec or {}).get("sampling_contract") or {}
    declared = ((sampling.get("given_start_by_law") or {}).get(str(candidate_id))
                if candidate_id is not None else None) or sampling.get("given_start")
    if not declared and sampling.get("given_start_rule"):
        raise ValueError("given_start_rule, a start read from the null atlas, left at 786 with the atlas: give the "
                         "campaign's starts (given_starts) or one start (given_start)")
    if not isinstance(declared, dict) or not declared.get("family"):
        return None
    from graph_scale_dynamics.measurements.calibration import control_family_reaches
    family = str(declared["family"])
    if n is None or not control_family_reaches(family, int(n)):
        raise ValueError(
            f"given_start family {family!r} cannot be built at exactly N={n}. "
            f"Declare a ladder whose rungs this family reaches, or a family that "
            f"reaches these rungs; a near-miss is not that start.")
    kernel = declared.get("kernel")
    if kernel is not None:
        from graph_scale_dynamics.scaleflow.engine_door import START_KERNELS
        if str(kernel) not in START_KERNELS:
            raise ValueError(f"given_start kernel {kernel!r} is not one the engine has ({', '.join(START_KERNELS)})")
        return {"family": family, "n": int(n), "kernel": str(kernel)}
    return {"family": family, "n": int(n)}


RESERVED_START_NAMES = frozenset({"empty", "given"})
_START_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def given_starts(campaign_spec: dict, n, candidate_id: str | None = None,
                candidate_spec: dict | None = None) -> list[dict] | None:
    sampling = (campaign_spec or {}).get("sampling_contract") or {}
    declared = sampling.get("given_starts")
    if declared is None:
        return None
    if any(sampling.get(key) for key in ("given_start", "given_start_by_law", "given_start_rule")):
        raise ValueError("a campaign declares its given starts one way: given_starts, or given_start and its kin")
    if not isinstance(declared, list) or not declared:
        raise ValueError("given_starts lists one start or more; a run from empty alone has no certificate yet")
    from graph_scale_dynamics.scaleflow.engine_door import CHAIN_NAMES, START_KERNELS
    from graph_scale_dynamics.measurements import random_starts
    from graph_scale_dynamics.measurements.calibration import control_family_reaches
    resolved, names, reserved = [], set(), RESERVED_START_NAMES | CHAIN_NAMES
    for start in declared:
        name = start.get("name") if isinstance(start, dict) else None
        if not isinstance(name, str) or not _START_NAME.match(name) or name in reserved:
            raise ValueError(f"a given start is named in lower case, not {sorted(reserved)}: {start!r}")
        if name in names:
            raise ValueError(f"two given starts are both named {name!r}")
        names.add(name)
        family = str(start.get("family") or "")
        if family == random_starts.DRAWN:
            if candidate_id is None:
                raise ValueError(f"the start {name!r} draws its degree from the law's id; make the job with one")
            cap = float((limits(campaign_spec).get("mean_degree_window") or {}).get("max") or 16.0)
            family = random_starts.drawn_family(str(candidate_id), name, cap)
        if n is None or not family or not control_family_reaches(family, int(n)):
            raise ValueError(f"the start {name!r} ({family or 'no family'}) cannot be built at exactly N={n}; "
                             f"a near-miss is not that start")
        kernel = start.get("kernel")
        if kernel is not None and str(kernel) not in START_KERNELS:
            raise ValueError(f"the start {name!r} names a kernel the engine does not have: {kernel!r}")
        resolved.append({"name": name, "family": family, "n": int(n),
                         **({"kernel": str(kernel)} if kernel is not None else {})})
    return resolved


CERTIFICATE_OVERRIDES = ("equilibration_connected_delta_floor", "equilibration_component_count_delta_floor",
                         "zero_temperature_rest_late_descent_share")


def one_shot_policy(campaign_spec: dict, n=None, candidate_id: str | None = None,
                    candidate_spec: dict | None = None) -> dict:
    policy = dict(campaign_spec.get("policy") or {})
    sampling = dict(campaign_spec.get("sampling_contract") or {})
    lim = limits(campaign_spec)
    starts = given_starts(campaign_spec, n, candidate_id, candidate_spec) or []
    more = {"more_given": starts[1:]} if starts else {}
    return {
        "contract": ONE_SHOT_CONTRACT,
        "required_consecutive_passes": max(1, int(sampling.get("required_consecutive_passes", 2))),
        "max_sweeps_multiplier": int(sampling.get("max_sweeps_multiplier",
                                                  policy.get("max_sweeps_multiplier", 64))),
        "min_effective_samples": float(policy.get("min_effective_samples", 8)),
        "equilibration_split_z": float(policy.get("equilibration_split_z", 3.0)),
        "stationarity_drift_max": float(policy.get("stationarity_drift_max", 3.0)),
        "equilibration_connected_delta_max": float(policy.get("equilibration_connected_delta_max", 0.25)),
        "equilibration_two_core_delta_max": float(policy.get("equilibration_two_core_delta_max", 0.25)),
        "equilibration_cycle_density_delta_max": float(policy.get("equilibration_cycle_density_delta_max", 0.15)),
        "equilibration_component_count_delta_max": float(policy.get("equilibration_component_count_delta_max", 0.10)),
        **{key: float(policy[key]) for key in CERTIFICATE_OVERRIDES if key in policy},
        "given_start": resolve_given_start(campaign_spec, n, candidate_id, candidate_spec),
        "mean_degree_cap": (float(lim["mean_degree_window"]["max"])
                            if mean_degree_cap_armed(campaign_spec, n) else None),
        "work_budget": int(work_budget(campaign_spec, n)),
        "work_unit": work_unit(campaign_spec),
        **more,
        **({"lattice_chains_meet": False} if starts and sampling.get("lattice_chains_meet") is False else {}),
        **({"analysis_version": str(campaign_spec["analysis_version"])}
           if campaign_spec.get("analysis_version") else {}),
    }


def enqueue_simulation_rung(repo, log, campaign: dict, candidate: dict, n: int,
                            seeds: range | list[int], requested_by: str | None,
                            sweeps_multiplier: int = 1, *, sealed: bool = False,
                            stage_prefix: str = "rung", queue_priority: int | None = None,
                            execution_overrides: dict | None = None,
                            resource_limits: dict | None = None,
                            replicate: int = 0, budget_scale: float = 1.0,
                            revive_cancelled: bool = False) -> int:
    spec = campaign["spec"]
    candidate_spec = candidate["spec"]
    if isinstance(sweeps_multiplier, bool) or not isinstance(sweeps_multiplier, int) \
            or sweeps_multiplier < 1:
        raise ValueError("sweeps_multiplier must be a positive integer")
    sweeps_multiplier = max(sweeps_multiplier, initial_sweeps_multiplier(spec, n))
    if isinstance(replicate, bool) or not isinstance(replicate, int) or replicate < 0:
        raise ValueError("replicate must be a non-negative integer")
    canonical_id = dsl.fingerprint(candidate_spec)
    if canonical_id != candidate["candidate_id"]:
        raise ValueError("candidate id does not match the canonical specification before enqueue")
    seed_values = list(seeds)
    if not bool((spec.get("sampling_contract") or {}).get("one_shot", True)):
        raise ValueError("every simulation job is one-shot; this spec's sampling contract is not")
    one_shot = one_shot_policy(spec, n, candidate["candidate_id"], candidate_spec)
    if isinstance(budget_scale, bool) or not isinstance(budget_scale, (int, float)) or budget_scale <= 0:
        raise ValueError("budget_scale must be a positive number")
    budget = int(work_budget(spec, n) * float(budget_scale))
    created = 0
    for seed in seed_values:
        stage = f"{stage_prefix}_n{n}" + ("" if sweeps_multiplier == 1 else f"_x{sweeps_multiplier}")
        jid = make_job_id(campaign["campaign_id"], candidate["candidate_id"], JobKind.SIMULATE.value,
                          stage, n, seed, replicate, ENGINE_VERSION)
        execution = {"sweeps_multiplier": sweeps_multiplier}
        if one_shot is not None:
            execution["one_shot"] = one_shot
        execution.update(dict(execution_overrides or {}))
        if float(budget_scale) != 1.0 and isinstance(execution.get("one_shot"), dict):
            execution["one_shot"] = dict(execution["one_shot"], work_budget=budget)
        if repo.insert_job(
            job_id=jid, campaign_id=campaign["campaign_id"], candidate_id=candidate["candidate_id"],
            kind=JobKind.SIMULATE.value, stage=stage, n=n, seed=seed, replicate=replicate,
            spec={"candidate_spec": candidate_spec,
                  "engine_version": ENGINE_VERSION,
                  "execution": execution,
                  "resource_limits": dict(resource_limits
                                          if resource_limits is not None
                                          else (spec.get("resource_limits") or {})),
                  "rung_extension": dict(spec.get("rung_extension") or {}),
                  "max_attempts": 0 if one_shot is not None else 3, "record_points": 240},
            priority=(int(queue_priority) if queue_priority is not None else n),
            requested_by=requested_by, sealed=sealed,
        ):
            created += 1
        elif revive_cancelled and repo.requeue_cancelled_job(
                jid, int(queue_priority) if queue_priority is not None else n):
            created += 1
    if created:
        log.write("jobs_enqueued", candidate=candidate["candidate_id"][:12], n=n, count=created)
    else:
        log.write("enqueue_noop", candidate=candidate["candidate_id"][:12], n=n,
                  note="all requested job ids already exist")
    return created
