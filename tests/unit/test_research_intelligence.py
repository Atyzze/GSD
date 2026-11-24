from __future__ import annotations

from graph_scale_dynamics.research.proposal_memory import build_family_memory, proposal_assessment


def _spec(c0: float = 0.2, *, op: str = "degree_anchor") -> dict:
    terms = [
        {"op": "edge_count", "params": {}, "coeff": {"c0": c0, "scale": "log_N"}},
        {"op": op, "params": {"k": 4} if "anchor" in op else {},
         "coeff": {"c0": 0.4, "scale": "one"}},
    ]
    return {"init": "empty", "terms": terms,
            "dynamics": {"kind": "equilibrium", "move_mix": {"add": 0.5, "delete": 0.5},
                         "sweeps": 30}}


def test_family_memory_marks_repeated_single_phenotype_as_exhausted():
    candidates = []
    decisions = {}
    for index in range(7):
        cid = f"candidate-{index}"
        candidates.append({"candidate_id": cid, "campaign_id": "campaign",
                           "spec": _spec(0.1 + index / 10), "state": "REJECTED_SCALING"})
        decisions[cid] = {"action": "stop", "rule": "disconnected"}
    memory = build_family_memory(candidates, decisions)
    assessment = proposal_assessment(_spec(0.99), memory)
    assert assessment["exhausted"] is True
    assert assessment["would_admit"] is True
    assert assessment["allocation_weight"] > 0
    assert assessment["category"] == "exhausted"
    unseen = proposal_assessment(_spec(0.4, op="degree_anchor_abs"), memory)
    assert unseen["would_admit"] is True
