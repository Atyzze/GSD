from graph_scale_dynamics.calibration.contract import (
    AUTHORITATIVE_SEEDS, CHANNEL_VALUE_KEYS, CONTRACT, SUITE_FAMILIES, SUITE_VERSION,
    durable_artifact_path, non_authoritative_artifact_path,
)
from graph_scale_dynamics.calibration.suite import (
    CalibrationGateError, ensure_calibration, resolve_table,
)
from graph_scale_dynamics.calibration.table import cell_is_current
from graph_scale_dynamics.calibration.table import load as load_table
from graph_scale_dynamics.calibration.table import write as write_table

PUBLIC = (AUTHORITATIVE_SEEDS, CHANNEL_VALUE_KEYS, CONTRACT, SUITE_FAMILIES, SUITE_VERSION, durable_artifact_path,
          non_authoritative_artifact_path, CalibrationGateError, ensure_calibration, resolve_table,
          load_table, write_table, cell_is_current)
__all__ = ["AUTHORITATIVE_SEEDS", "cell_is_current", "CONTRACT", "SUITE_FAMILIES", "SUITE_VERSION", "durable_artifact_path",
           "non_authoritative_artifact_path", "CalibrationGateError", "ensure_calibration", "resolve_table",
           "load_table", "write_table", "current_suite_fingerprint", "science_fingerprint", "structure_limits",
           "gate_cells", "extension_cells", "d_s_margin_bands", "committed_d_s_margin_bands", "place_d_s_margin",
           "CHANNEL_VALUE_KEYS", "graph_of_a_cell", "readings_judged_as_the_gate_judges", "table_in_force",
           "cells_of_the_lattice_starts", "counted_on_a_start", "what_reads_a_start"]


def current_suite_fingerprint(seeds: int | None = None, families=None) -> str:
    from graph_scale_dynamics.calibration.cells import suite_families
    from graph_scale_dynamics.calibration.table import suite_fingerprint
    return suite_fingerprint(suite_families(families),
                             seeds=AUTHORITATIVE_SEEDS if seeds is None else int(seeds))


def science_fingerprint() -> str:
    from graph_scale_dynamics.calibration.fingerprint import science_fingerprint as _fp
    return _fp()


def structure_limits() -> dict:
    from graph_scale_dynamics.calibration.structure import (
        CLIQUE_MAX_N, GAP_MAX_N, LIMITS_BEFORE_531, SQUARE_MAX_N)
    return {"gap_max_n": GAP_MAX_N, "clique_max_n": CLIQUE_MAX_N, "square_max_n": SQUARE_MAX_N,
            "before_531": dict(LIMITS_BEFORE_531)}


def gate_cells(table: dict | None) -> dict:
    from graph_scale_dynamics.calibration.contract import LADDER_EXTENSIONS
    past = {(family, str(parameter)) for family, parameters in LADDER_EXTENSIONS.items() for parameter in parameters}
    cells = (table or {}).get("cells") or {}
    return {key: cell for key, cell in cells.items()
            if (str((cell or {}).get("family") or ""), str((cell or {}).get("parameter"))) not in past}


def extension_cells(table: dict | None) -> dict:
    gate = gate_cells(table)
    return {key: cell for key, cell in ((table or {}).get("cells") or {}).items() if key not in gate}


def d_s_margin_bands(table: dict | None) -> dict:
    from graph_scale_dynamics.calibration.margins import bands, committed_bands, table_rows
    rows = table_rows(table or {})
    committed = committed_bands()
    return {"from_this_table": bands(rows), "cells_with_margins": len(rows),
            "cells": len((table or {}).get("cells") or {}),
            "committed_with_the_build": (None if committed is None else {
                k: committed.get(k) for k in ("bands", "computed_utc", "max_n", "seeds")}),
            "threshold": 2.0}


def committed_d_s_margin_bands() -> dict | None:
    from graph_scale_dynamics.calibration.margins import committed_bands
    return committed_bands()


def place_d_s_margin(delta, n: int, table: dict | None) -> str:
    from graph_scale_dynamics.calibration.margins import place
    return place(delta, n, table)


def graph_of_a_cell(family: str, parameter, seed: int = 0) -> tuple:
    from graph_scale_dynamics.calibration.cells import build_graph, suite_families
    return build_graph(suite_families([family])[0], parameter, seed)


def readings_judged_as_the_gate_judges(family: str, parameter, n: int, readings: dict) -> dict:
    from graph_scale_dynamics.calibration.cells import suite_families
    from graph_scale_dynamics.calibration.deviation import readings_judged_as_a_rung
    return readings_judged_as_a_rung(suite_families([family])[0], parameter, n, readings)


def table_in_force(root=None) -> dict | None:
    table = load_table(durable_artifact_path(root))
    if table is None or table.get("contract") != CONTRACT or table.get("suite_version") != SUITE_VERSION:
        return None
    return table


def cells_of_the_lattice_starts(table: dict | None) -> dict:
    from graph_scale_dynamics.calibration import start_reading
    from graph_scale_dynamics.calibration.table import its_probes_are_current
    found: dict = {}
    for cell in ((table or {}).get("cells") or {}).values():
        if not its_probes_are_current(cell):
            continue
        family, n = str(cell.get("family")), cell.get("n")
        if start_reading.is_a_lattice_start(family, n):
            found.setdefault((family, int(n)), []).append(cell)
    out = {}
    for key in sorted(found):
        cells = sorted(found[key], key=lambda cell: int(cell.get("seed") or 0))
        out[key] = {"cells": cells, "starts": [cell["start"] for cell in cells if start_reading.current(cell)]}
    return out


def counted_on_a_start() -> tuple:
    from graph_scale_dynamics.calibration.start_reading import COUNTED
    return COUNTED


def what_reads_a_start() -> dict:
    from graph_scale_dynamics.calibration import start_reading
    return dict(start_reading.sources())


def the_whole_plan(seeds: int, extension_seeds: int) -> list[dict]:
    from graph_scale_dynamics.calibration.cells import plan_cells, plan_extension_cells, suite_families
    families = suite_families()
    return plan_cells(families, seeds=int(seeds)) + plan_extension_cells(families, seeds=int(extension_seeds))


def the_same_graph_on_every_seed(family: str) -> bool:
    from graph_scale_dynamics.calibration.cells import graph_varies_per_seed, suite_families
    return not graph_varies_per_seed(suite_families([family])[0])
