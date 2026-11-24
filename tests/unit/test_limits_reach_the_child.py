from __future__ import annotations

import json
from pathlib import Path

from tests.support import chains as SC
from graph_scale_dynamics.scaleflow import one_shot as OS
from graph_scale_dynamics.scheduling.memory import effective_hard_fraction

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "tests" / "fixtures" / "campaign_5rung_sparse_survey.json").read_text(encoding="utf-8"))
ANCHOR = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs"
                     / "candidate_sparse_anchor.json").read_text(encoding="utf-8"))


def _envelope(*, declared: str | None, given: str | None, mean_degree: float = 2.0) -> dict:
    return SC.pair(64, [], empty={"final": {"mean_degree": mean_degree}},
                   given_record={"termination": {"reason": given} if given else None},
                   termination={"reason": declared} if declared else None, seed=0, cumulative_sweeps=30,
                   sampling_checkpoint={"resume": True})


def _run(envelopes, *, budget=10 ** 12):
    calls = {"n": 0}

    def simulate(*_args, **_kwargs):
        index = min(calls["n"], len(envelopes) - 1)
        calls["n"] += 1
        return envelopes[index]

    from graph_scale_dynamics.scheduling.limits import work_unit
    policy = {"contract": OS.ONE_SHOT_CONTRACT, "max_sweeps_multiplier": 8,
              "required_consecutive_passes": 2, "work_budget": budget, "work_unit": work_unit(SPEC)}
    ticks = iter([0.0] + [float(i) for i in range(1, 500)])
    result = OS.run_one_shot(ANCHOR, 64, 0, one_shot=policy, record_points=8,
                             engine_contract_version=1, initial_multiplier=1,
                             clock=lambda: next(ticks), simulate=simulate)
    return result["rung_terminal"], result.get("sampling_checkpoints", []), calls["n"]


def test_a_completed_pair_is_not_a_budget_stop():
    terminal, _history, _calls = _run([_envelope(declared="completed", given="completed")])
    assert terminal["reason"] != "budget"
    assert terminal["classification"] != "REFUSED_COMPUTE_BUDGET"


def test_a_mean_degree_cap_still_outranks_the_given_chain():
    terminal, _history, _calls = _run([_envelope(declared="mean_degree_cap", given=None)])
    assert terminal["reason"] == "mean_degree_cap"


class _Repo:
    def __init__(self):
        self.jobs: list[dict] = []

    def insert_job(self, **fields):
        self.jobs.append(fields)
        return True


def _enqueue(n: int = 16384, **kwargs) -> dict:
    from graph_scale_dynamics.dsl.dsl import fingerprint
    from graph_scale_dynamics.scheduling.job_creation import enqueue_simulation_rung
    from tests.support.doubles import NullLog
    repo = _Repo()
    enqueue_simulation_rung(repo, NullLog(), {"campaign_id": "c", "spec": SPEC},
                            {"candidate_id": fingerprint(ANCHOR), "spec": ANCHOR},
                            n, [0], "test", stage_prefix="base", **kwargs)
    return repo.jobs[0]["spec"]


def test_the_job_spec_carries_the_campaigns_memory_boundary():
    spec = _enqueue()
    assert spec["resource_limits"].get("hard_single_job_fraction_total") == 0.08
    assert effective_hard_fraction(spec, 16384) == (0.08, 0.25)
    assert effective_hard_fraction(spec, 16384) == effective_hard_fraction(SPEC, 16384), (
        "the child's boundary must be the campaign's boundary; two answers to "
        "one question is how a 19 GiB attempt passed a 7.8 GB guard")


def test_an_explicit_resource_limits_argument_still_wins():
    spec = _enqueue(resource_limits={"hard_single_job_fraction_total": 0.2})
    assert spec["resource_limits"] == {"hard_single_job_fraction_total": 0.2}


def test_no_production_call_asks_for_the_boundary_without_a_rung():
    import ast
    offenders = []
    for path in (ROOT / "graph_scale_dynamics").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name in ("hard_process_limit_bytes", "effective_hard_fraction"):
                    has_n = any(k.arg == "n" for k in node.keywords) or len(node.args) >= 2
                    if not has_n:
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, offenders
