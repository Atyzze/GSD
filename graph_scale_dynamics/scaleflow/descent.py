from __future__ import annotations

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.dsl.dsl import coefficient
from graph_scale_dynamics.engine.engine import configuration_energy

DESCENT_CONTRACT = "descent-record-1"
REFERENCE_MAX_N = 262144


def _late_neutral_share(accounting: dict) -> float | None:
    counts = ((accounting or {}).get("late") or {}).get("counts") or {}
    accepted = sum(v for k, v in counts.items() if k.endswith(".accepted"))
    neutral = sum(v for k, v in counts.items() if k.endswith(".zero.accepted"))
    return None if accepted == 0 else neutral / accepted


def disjoint_cliques(n: int, size: int) -> list[tuple[int, int]]:
    edges = []
    for start in range(0, n, size):
        members = range(start, min(n, start + size))
        edges += [(u, v) for u in members for v in members if u < v]
    return edges


def reference_configuration(candidate_spec: dict, n: int) -> dict:
    anchors = [t for t in candidate_spec.get("terms") or []
               if t["op"] == "degree_anchor" and coefficient(t, n) > 0
               and int((t.get("params") or {}).get("k", 0)) >= 1]
    rewards = [t for t in candidate_spec.get("terms") or []
               if t["op"] == "triangle_count" and coefficient(t, n) < 0]
    if not anchors or not rewards:
        return {"kind": None, "reason": "no degree anchor with a triangle reward"}
    k = int(anchors[0]["params"]["k"])
    if n > REFERENCE_MAX_N:
        return {"kind": "disjoint_cliques", "clique_size": k + 1, "energy": None,
                "reason": f"not summed above N={REFERENCE_MAX_N}"}
    return {"kind": "disjoint_cliques", "clique_size": k + 1,
            "energy": configuration_energy(candidate_spec, n, disjoint_cliques(n, k + 1)),
            "reason": None}


def descent_record(candidate_spec: dict, n: int, envelope: dict) -> dict:
    accounting = CL.move_accounting(envelope)
    reference = reference_configuration(candidate_spec, n)
    ref = reference.get("energy")
    chains = {}
    for row in CL.records(envelope):
        name = str(row.get("start"))
        acc = accounting.get(name) or {}
        if name == CL.FROM_EMPTY:
            energy = (row.get("final") or {}).get("energy")
        else:
            energy = None if row.get("skipped") else CL.block(envelope, name).get("energy")
        chains[name] = {
            "last_decrease_move": acc.get("last_decrease_move"),
            "late_neutral_share": _late_neutral_share(acc),
            "final_energy": energy,
            "distance_from_reference": (None if energy is None or ref is None else float(energy) - float(ref)),
        }
    return {"contract": DESCENT_CONTRACT, "reference": reference, "chains": chains}
