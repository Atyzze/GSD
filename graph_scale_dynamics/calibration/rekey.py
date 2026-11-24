from __future__ import annotations

from pathlib import Path

from graph_scale_dynamics.calibration import contract as C
from graph_scale_dynamics.calibration import fingerprint as FP
from graph_scale_dynamics.calibration import table as T
from graph_scale_dynamics.calibration.admission import Admission
from graph_scale_dynamics.calibration.cells import cell_key, measure_cell, plan_cells, suite_families
from graph_scale_dynamics.calibration.suite import _run_in_workers, default_workers, resolve_table

REKEY_CONTRACT = "gsd-calibration-rekey-1"

EVIDENCE_FIELDS = ("n", "component", "status", "parameter", "graph_varies_per_seed", "half_volume_radius")

CHANNEL_FIELDS = ("valid", "value", "se", "measured_se", "reason", "refusal")

START_FIELDS = ("mean_degree", "triangles_per_node", "squares_per_node", "giant_fraction", "kappa", "random_wiring",
                "error")

RECORDED_OUTPUTS = ("d_s", "d_V", "d_B", "d_w", "n", "component", "parameter", "half_volume_radius")

UNRECORDED_OUTPUTS = (
    "clustering", "two_core_fraction", "degree_second_moment", "degree_heterogeneity",
    "max_degree", "edge_count", "cycle_rank", "connected_fraction", "mean_degree",
    "effective_samples", "iat_sweeps", "stationarity_drift", "activity",
    "late_edge_jaccard", "isolated_fraction",
)

IGNORED_FIELDS = ("computed_utc", "host", "elapsed_seconds", "cell_fingerprint",
                  "science_fingerprint")

DEFAULT_SAMPLE = 15

DEFAULT_BUDGET_SECONDS = 60.0


def _stale_cells(document: dict, plan: list[dict], root: str | None = None) -> list[dict]:
    cells = document.get("cells") or {}
    out = []
    for task in plan:
        cell = cells.get(task["key"])
        if not isinstance(cell, dict) or cell.get("status") != "ok":
            continue
        if str(cell.get("cell_fingerprint")) != FP.cell_fingerprint(task["family"], root):
            out.append({"task": task, "cell": cell})
    return out


def predicted_wall_seconds(items: list[dict], workers: int) -> float:
    costs = [float(i["cell"].get("elapsed_seconds") or 0.0) for i in items]
    if not costs:
        return 0.0
    return round(max(max(costs), sum(costs) / max(1, workers)), 1)


def choose_sample(stale: list[dict], *, sample: int = DEFAULT_SAMPLE,
                  budget_seconds: float | None = DEFAULT_BUDGET_SECONDS,
                  workers: int = 1, deep: bool = False) -> list[dict]:
    by_family: dict[str, list[dict]] = {}
    for item in stale:
        by_family.setdefault(item["task"]["family"], []).append(item)

    def cost(item):
        return float(item["cell"].get("elapsed_seconds") or 0.0)

    chosen: list[dict] = []
    if deep:
        for family in sorted(by_family):
            chosen.append(max(by_family[family], key=lambda i: (i["cell"].get("n") or 0)))
    else:
        for family in sorted(by_family):
            chosen.append(min(by_family[family], key=cost))

    picked = {id(i) for i in chosen}
    rest = sorted((i for i in stale if id(i) not in picked), key=cost, reverse=True)
    for item in rest:
        if len(chosen) >= sample:
            break
        if budget_seconds is not None:
            if predicted_wall_seconds(chosen + [item], workers) > budget_seconds:
                continue
        chosen.append(item)
    return chosen


def sample_coverage(chosen: list[dict]) -> dict:
    ns = sorted({int(i["cell"].get("n") or 0) for i in chosen})
    return {"families": sorted({i["task"]["family"] for i in chosen}),
            "n_values": ns,
            "n_min": (ns[0] if ns else None), "n_max": (ns[-1] if ns else None)}


def compare_cell(stored: dict, fresh: dict) -> list[str]:
    differences: list[str] = []
    for field in EVIDENCE_FIELDS:
        if stored.get(field) != fresh.get(field):
            differences.append(f"{field}: {stored.get(field)!r} -> {fresh.get(field)!r}")
    stored_channels = stored.get("channels") or {}
    fresh_channels = fresh.get("channels") or {}
    for channel in sorted(set(stored_channels) | set(fresh_channels)):
        a = stored_channels.get(channel) or {}
        b = fresh_channels.get(channel) or {}
        for field in CHANNEL_FIELDS:
            if a.get(field) != b.get(field):
                differences.append(
                    f"{channel}.{field}: {a.get(field)!r} -> {b.get(field)!r}")
    stored_start, fresh_start = stored.get("start") or {}, fresh.get("start") or {}
    for field in START_FIELDS:
        if stored_start.get(field) != fresh_start.get(field):
            differences.append(f"start.{field}: {stored_start.get(field)!r} -> {fresh_start.get(field)!r}")
    return differences


def verify_sample(chosen: list[dict], *, root: str | None = None, workers: int = 1,
                  log=print, document: dict | None = None, admission: Admission | None = None) -> dict:
    science = FP.science_fingerprint()
    checked, mismatches, failed = [], [], []
    stored_by_key = {i["task"]["key"]: i["cell"] for i in chosen}

    def args(task: dict) -> dict:
        return dict(task, cell_fingerprint=FP.cell_fingerprint(task["family"], root),
                    science_fingerprint=science)

    def record(key: str, fresh: dict) -> None:
        stored = stored_by_key[key]
        if fresh.get("status") != "ok" and stored.get("status") == "ok":
            failed.append({"key": key, "error": fresh.get("error")})
            return
        differences = compare_cell(stored, fresh)
        checked.append(key)
        mark = "same" if not differences else f"DIFFERS on {len(differences)} field(s)"
        log(f"  [{len(checked) + len(failed):>3}/{len(chosen)}] {fresh.get('family')} "
            f"n={fresh.get('n')} seed={fresh.get('seed')} "
            f"({fresh.get('elapsed_seconds', 0):.1f}s) {mark}")
        if differences:
            mismatches.append({"key": key, "family": fresh.get("family"),
                               "n": fresh.get("n"), "seed": fresh.get("seed"),
                               "differences": differences})

    if workers <= 1:
        for item in chosen:
            a = args(item["task"])
            record(item["task"]["key"],
                   measure_cell(a["family"], a["parameter"], a["seed"],
                                cell_fingerprint=a["cell_fingerprint"],
                                science_fingerprint=a["science_fingerprint"]))
    else:
        blocked: list[dict] = []

        def finish(fresh: dict, running: int = 1) -> None:
            record(cell_key(fresh["family"], fresh["parameter"], fresh["seed"]), fresh)

        _run_in_workers([item["task"] for item in chosen], workers=workers,
                        admission=admission or Admission(),
                        document=document if document is not None else {"cells": dict(stored_by_key)},
                        log=log, task_args=args, finish=finish, blocked=blocked, root=root, science=science)
        for entry in blocked:
            failed.append({"key": entry["key"], "error": f"cannot be admitted: {entry['reason']}"})
    return {"checked": checked, "mismatches": mismatches, "failed": failed,
            "identical": len(checked) - len(mismatches)}


def rekey_document(document: dict, plan: list[dict], *, verification: dict,
                   justification: str, root: str | None = None) -> dict:
    cells = document.get("cells") or {}
    science = FP.science_fingerprint()
    restamped = 0
    analysis = FP.analysis_version(root)
    for task in plan:
        cell = cells.get(task["key"])
        if not isinstance(cell, dict) or cell.get("status") != "ok" or cell.get("analysis") != analysis:
            continue
        cell["cell_fingerprint"] = FP.cell_fingerprint(task["family"], root)
        cell["science_fingerprint"] = science
        restamped += 1
    record = {
        "contract": REKEY_CONTRACT,
        "from_estimator_fingerprint": document.get("estimator_fingerprint"),
        "to_estimator_fingerprint": FP.estimator_fingerprint(root),
        "from_science_fingerprint": document.get("science_fingerprint"),
        "to_science_fingerprint": science,
        "cells_restamped": restamped,
        "cells_verified": sorted(verification["checked"]),
        "cells_verified_count": len(verification["checked"]),
        "justification": justification,
        "observable_claim": verification.get("_claim"),
        "utc": T._utc(),
        "reading": (
            "These cells were not recomputed. A sample was recomputed under the "
            "new measurement code and compared field by field against the stored "
            "records; every compared field was identical, so the rest were "
            "re-stamped. The sample is listed above by key. If this table is "
            "ever in doubt, the suite recomputes it from scratch and that is "
            "always the authoritative answer."),
    }
    document.setdefault("rekeys", []).append(record)
    return record


def classify_observables(names: list[str]) -> dict:
    recorded = [n for n in names if n in RECORDED_OUTPUTS]
    unrecorded = [n for n in names if n in UNRECORDED_OUTPUTS]
    unknown = [n for n in names if n not in RECORDED_OUTPUTS and n not in UNRECORDED_OUTPUTS]
    return {"recorded": recorded, "unrecorded": unrecorded, "unknown": unknown,
            "inert": bool(names) and not recorded and not unknown}


def rekey(root: Path | None = None, var: Path | None = None, *,
          sample: int = DEFAULT_SAMPLE,
          inert_observables: list[str] | None = None,
          budget_seconds: float | None = DEFAULT_BUDGET_SECONDS,
          workers: int | None = None, deep: bool = False,
          apply: bool = False, justification: str | None = None,
          log=print) -> dict:
    root = Path(root) if root else C.repository_root()
    var = Path(var) if var else (root / "var")
    path, document, origin = resolve_table(root, var)
    claim = classify_observables([n.strip() for n in (inert_observables or []) if n.strip()])
    if claim["recorded"]:
        log(f"REFUSING: {', '.join(claim['recorded'])} IS recorded by every "
            "calibration cell, so a change to it can move a stored value. "
            "This is not an inert change; run the suite.")
        return {"contract": REKEY_CONTRACT, "apply": bool(apply),
                "status": "REFUSED_OBSERVABLE_IS_RECORDED", "claim": claim,
                "stale": 0, "sampled": 0, "identical": 0, "mismatches": [],
                "failed": [], "restamped": 0}
    if claim["unknown"]:
        log(f"REFUSING: {', '.join(claim['unknown'])} is not in either list, so "
            "whether a cell records it is unknown. Add it to RECORDED_OUTPUTS or "
            "UNRECORDED_OUTPUTS in rekey.py, with the reason, and try again.")
        return {"contract": REKEY_CONTRACT, "apply": bool(apply),
                "status": "REFUSED_OBSERVABLE_UNKNOWN", "claim": claim,
                "stale": 0, "sampled": 0, "identical": 0, "mismatches": [],
                "failed": [], "restamped": 0}
    if claim["inert"] and apply and not (justification or "").strip():
        justification = (
            "change confined to " + ", ".join(claim["unrecorded"]) +
            "; no calibration cell records any of them, so no stored value can "
            "move. Checked against RECORDED_OUTPUTS at re-key time.")
        log(f"inert-observable claim accepted: {', '.join(claim['unrecorded'])} "
            "is recorded by no cell. Justification composed from it.")
    if apply and not (justification or "").strip():
        log("--apply requires --justification: one sentence saying why this change "
            "could not move a stored value. It is recorded on the table.")
        log("Nothing was run. Re-run with --justification, or without --apply to "
            "verify only.")
        return {"contract": REKEY_CONTRACT, "apply": True,
                "status": "REFUSED_NO_JUSTIFICATION", "stale": 0, "sampled": 0,
                "identical": 0, "mismatches": [], "failed": [], "restamped": 0}
    from graph_scale_dynamics.calibration import owed as OWED
    if OWED.recalibration_owed():
        log("REFUSING: a recalibration is owed (calibration/recalibration_owed.json): its cells are measured by "
            "`main.py run`, never re-keyed.")
        return {"contract": REKEY_CONTRACT, "apply": bool(apply), "status": "REFUSED_RECALIBRATION_OWED",
                "stale": 0, "sampled": 0, "identical": 0, "mismatches": [], "failed": [], "restamped": 0}
    workers = default_workers() if workers is None else int(workers)
    report = {"contract": REKEY_CONTRACT, "apply": bool(apply), "table": str(path),
              "origin": origin, "workers": workers, "stale": 0, "sampled": 0,
              "identical": 0, "mismatches": [], "failed": [], "restamped": 0,
              "sample_wall_seconds": 0.0, "full_wall_seconds": 0.0,
              "sample_serial_seconds": 0.0, "full_serial_seconds": 0.0,
              "coverage": {}, "status": "NO_TABLE"}
    if not document:
        log("no calibration table to re-key; the suite must compute one")
        return report

    families = suite_families()
    seeds = C.AUTHORITATIVE_SEEDS
    plan = plan_cells(families, seeds=seeds, max_nodes=None)
    stale = _stale_cells(document, plan, str(root))
    report["stale"] = len(stale)
    report["full_serial_seconds"] = round(
        sum(float(i["cell"].get("elapsed_seconds") or 0.0) for i in stale), 1)
    report["full_wall_seconds"] = predicted_wall_seconds(stale, workers)
    if not stale:
        report["status"] = "NOTHING_STALE"
        log("every cell is already current under this fingerprint; nothing to do")
        return report

    chosen = choose_sample(stale, sample=sample, budget_seconds=budget_seconds,
                           workers=workers, deep=deep)
    report["sampled"] = len(chosen)
    report["sample_serial_seconds"] = round(
        sum(float(i["cell"].get("elapsed_seconds") or 0.0) for i in chosen), 1)
    report["sample_wall_seconds"] = predicted_wall_seconds(chosen, workers)
    report["coverage"] = sample_coverage(chosen)
    log(f"{len(stale)} cells stale under the new fingerprint: "
        f"~{report['full_wall_seconds']:.0f}s wall to recompute in full "
        f"on {workers} worker(s)")
    log(f"verifying {len(chosen)} of them: ~{report['sample_wall_seconds']:.0f}s wall")
    cov = report["coverage"]
    log(f"  covering {len(cov['families'])} families, N from {cov['n_min']} "
        f"to {cov['n_max']}")
    if report["sample_wall_seconds"] >= report["full_wall_seconds"]:
        log("  the sample costs at least as much as the full recompute; "
            "run the suite instead, or lower --sample")

    verification = verify_sample(chosen, root=str(root), workers=workers, log=log, document=document)
    verification["_claim"] = claim if claim.get("inert") else None
    report["claim"] = claim
    report["identical"] = verification["identical"]
    report["mismatches"] = verification["mismatches"]
    report["failed"] = verification["failed"]

    if verification["mismatches"] or verification["failed"]:
        report["status"] = "REFUSED_EVIDENCE_CHANGED"
        log("")
        log("REFUSING to re-key: the measurement changed for at least one cell.")
        for m in verification["mismatches"][:10]:
            log(f"  {m['family']} n={m['n']} seed={m['seed']}")
            for d in m["differences"][:6]:
                log(f"     {d}")
        for f in verification["failed"][:5]:
            log(f"  {f['key']} now fails: {f['error']}")
        log("Run the suite; these cells are genuinely out of date.")
        return report

    report["status"] = "VERIFIED" if not apply else "APPLIED"
    if not apply:
        log("")
        log(f"all {verification['identical']} sampled cells identical on every "
            f"compared field")
        log("")
        log("What this is and is not: a smoke test on the claim that the change "
            "cannot move a stored value, not evidence about the other "
            f"{len(stale) - verification['identical']} cells. It is here to catch "
            "that claim being wrong, which is why it is small. If you want "
            "evidence about the whole table, run the suite.")
        log(f"NOT verified: cells outside N {cov['n_min']}..{cov['n_max']} "
            f"and every other seed. This is a sample, and the suite remains the "
            f"authoritative answer.")
        log("nothing was written; re-run with --apply and --justification")
        return report

    T.history_copy(document, C.history_dir(var), "pre_rekey")
    record = rekey_document(document, plan, verification=verification,
                            justification=justification, root=str(root))
    T.refresh(document, families, seeds=seeds, max_nodes=None, root=str(root))
    T.write(document, path)
    report["restamped"] = record["cells_restamped"]
    log(f"re-stamped {record['cells_restamped']} cells; previous table copied to "
        f"{C.history_dir(var)}")
    return report


def render(report: dict) -> str:
    lines = [f"calibration re-key ({'APPLIED' if report['apply'] else 'dry run'})",
             f"  table  {report['table']}",
             f"  status {report['status']}",
             f"  stale {report['stale']}   sampled {report['sampled']}"
             f"   identical {report['identical']}"]
    if report["stale"]:
        lines.append(f"  wall at {report['workers']} workers: full "
                     f"~{report['full_wall_seconds']}s, sample "
                     f"~{report['sample_wall_seconds']}s")
        cov = report.get("coverage") or {}
        if cov:
            lines.append(f"  verified {len(cov.get('families') or [])} families, "
                         f"N {cov.get('n_min')}..{cov.get('n_max')}")
    for m in report["mismatches"][:5]:
        lines.append(f"  MISMATCH {m['family']} n={m['n']}: {m['differences'][:3]}")
    if report["restamped"]:
        lines.append(f"  re-stamped {report['restamped']} cells")
    return "\n".join(lines)
