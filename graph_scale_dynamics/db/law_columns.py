from __future__ import annotations

import json

from graph_scale_dynamics.dsl.dsl import dynamics_record

LAW_COLUMNS = "regime,beta,locality,local_move,zero_temperature,swap_share,reduced_basis_json"


def law_columns(spec: dict) -> tuple:
    from graph_scale_dynamics.research.hamiltonian_preflight import effective_basis

    axes = dynamics_record(spec)
    return (axes["regime"], axes["beta"], axes["locality"], axes["local_move"], axes["zero_temperature"],
            axes["swap_share"], json.dumps(effective_basis(spec), sort_keys=True))
