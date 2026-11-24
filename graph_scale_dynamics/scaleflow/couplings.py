from __future__ import annotations

from graph_scale_dynamics.dsl.dsl import coefficient

COUPLINGS_CONTRACT = "couplings-at-n-1"


def couplings_at(spec: dict, n: int) -> dict:
    from graph_scale_dynamics.research.hamiltonian_preflight import effective_basis

    beta = float((spec.get("dynamics") or {}).get("beta", 1.0))
    terms = []
    for index, term in enumerate(spec.get("terms") or []):
        value = float(coefficient(term, n))
        terms.append({"term_index": index, "op": term["op"], "params": dict(term.get("params") or {}),
                      "scale": (term.get("coeff") or {}).get("scale"), "coefficient": value,
                      "beta_coefficient": beta * value})
    reduced = []
    for row in effective_basis(spec):
        coeff = {"c0": row["coefficient"], "scale": row["scale"]}
        if row["scale"] == "power":
            coeff["p"] = row["p"]
        reduced.append({"op": row["op"], "params": row["params"], "scale": row["scale"],
                        "beta_coefficient": float(coefficient({"coeff": coeff}, n))})
    return {"contract": COUPLINGS_CONTRACT, "n": int(n), "beta": beta, "terms": terms, "reduced": reduced}
