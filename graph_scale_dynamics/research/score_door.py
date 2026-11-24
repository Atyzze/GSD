from __future__ import annotations

INPUTS = frozenset({"floors", "floors_by_n", "connectivity_floor", "control_reference"})


def score_evidence(*, phenotype: dict | None = None, rows: list[dict] | None = None, **inputs) -> dict:
    from graph_scale_dynamics.research import stability_score
    if (phenotype is None) == (rows is None):
        raise TypeError("score_evidence takes exactly one of phenotype= or rows=")
    unknown = sorted(set(inputs) - INPUTS)
    if unknown:
        raise TypeError(f"score_evidence got inputs the scorer does not take: {unknown}")
    if phenotype is not None:
        return stability_score.score_phenotype(phenotype, **inputs)
    return stability_score.score_rung_rows(rows, **inputs)


def table_noise_floors() -> tuple[dict, dict]:
    from graph_scale_dynamics.calibration import durable_artifact_path, load_table
    from graph_scale_dynamics.research.stability_score import noise_floors, noise_floors_by_n
    path = durable_artifact_path()
    table = load_table(path)
    if not table:
        raise RuntimeError(
            f"no calibration table at {path}; the extender scores against the "
            "instrument's measured tolerances and cannot decide anything without "
            "them. Compute one with `python tools/probe_calibration.py --write`, "
            "restore a previous run from var/calibration/history/, or pass "
            "`floors=` explicitly.")
    return noise_floors(table), noise_floors_by_n(table)
