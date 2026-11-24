from __future__ import annotations

import hashlib
import math
import platform
import random
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone

from graph_scale_dynamics.calibration import fingerprint as FP
from graph_scale_dynamics.calibration import ledger as L
from graph_scale_dynamics.calibration import probe_groups as G
from graph_scale_dynamics.calibration.cells import build_graph, plan_cells, suite_families
from graph_scale_dynamics.calibration.contract import AUTHORITATIVE_SEEDS

DEFAULT_TOLERANCE = 1e-9
BATCH = 16


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def values_hash(record: dict) -> str:
    return hashlib.sha256(L.canonical({"cell": record.get("cell"),
                                       "family_fingerprint": record.get("family_fingerprint"),
                                       "channels": record.get("channels")})).hexdigest()


def table_geometry_fingerprint(document: dict) -> str:
    return G.geometry_fingerprint_of(str(document.get("analysis_version")),
                                     str(document.get("estimator_fingerprint")))


def records_from_table(document: dict) -> tuple[str, list[dict]]:
    fingerprint = table_geometry_fingerprint(document)
    families = document.get("families") or {}
    out = []
    for key, cell in sorted((document.get("cells") or {}).items()):
        if not isinstance(cell, dict) or cell.get("status") != "ok":
            continue
        family = str(cell.get("family"))
        record = {"kind": L.MEASURE, "cell": key, "family": family, "parameter": cell.get("parameter"),
                  "seed": cell.get("seed"), "n": cell.get("n"),
                  "family_fingerprint": (families.get(family) or {}).get("family_fingerprint"),
                  "channels": cell.get("channels"), "host": cell.get("host"), "utc": cell.get("computed_utc"),
                  "elapsed_seconds": cell.get("elapsed_seconds"), "cell_record": cell,
                  "source": {"table_build": document.get("build_number"),
                             "table_written_utc": document.get("written_utc")}}
        record["values"] = values_hash(record)
        out.append(record)
    return fingerprint, out


def adopt_table(root, document: dict) -> dict:
    fingerprint, records = records_from_table(document)
    path = L.ledger_path(root, G.GEOMETRY, fingerprint)
    held = L.measured(root, G.GEOMETRY, fingerprint)
    fresh = [r for r in records if r["cell"] not in held]
    changed = [r["cell"] for r in records if r["cell"] in held and held[r["cell"]].get("values") != r["values"]]
    written = L.append(path, fresh)
    return {"group": G.GEOMETRY, "fingerprint": fingerprint, "written": len(written),
            "already_held": len(records) - len(fresh), "held_with_other_values": changed}


def plan(max_nodes: int | None, families=None, seeds: int = AUTHORITATIVE_SEEDS) -> list[dict]:
    return plan_cells(suite_families(families), seeds=seeds, max_nodes=max_nodes)


def missing(root, group: str, tasks: list[dict]) -> list[dict]:
    held = L.measured(root, group, G.group_fingerprint(group, root))
    return [t for t in tasks if t["key"] not in held]


def measure_task(group: str, task: dict) -> dict:
    module = G.group_module(group)
    family = suite_families([task["family"]])[0]
    started = time.monotonic()
    n, edges = build_graph(family, task["parameter"], int(task["seed"]))
    result = module.measure(int(n), edges, int(task["seed"]))
    record = {"kind": L.MEASURE, "cell": task["key"], "family": task["family"], "parameter": task["parameter"],
              "seed": int(task["seed"]), "n": int(n), "family_fingerprint": FP.family_fingerprint(task["family"]),
              "channels": result["channels"],
              "context": {k: v for k, v in result.items() if k != "channels"},
              "host": platform.node(), "utc": _utc(), "elapsed_seconds": round(time.monotonic() - started, 3),
              "environment": G.environment()}
    record["values"] = values_hash(record)
    return record


def _run(group: str, tasks: list[dict], workers: int, sink) -> int:
    done = 0
    if workers <= 1:
        for task in tasks:
            sink([measure_task(group, task)])
            done += 1
        return done
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(tasks), BATCH * workers):
            chunk = tasks[start:start + BATCH * workers]
            records = list(pool.map(measure_task, [group] * len(chunk), chunk))
            sink(records)
            done += len(records)
    return done


def measure_missing(root, group: str, tasks: list[dict], *, workers: int = 1, limit: int | None = None,
                    progress=None) -> dict:
    if group == G.GEOMETRY:
        raise G.ProbeGroupError("the geometry group is measured by the calibration suite and adopted from its table")
    fingerprint = G.group_fingerprint(group, root)
    todo = missing(root, group, tasks)
    if limit is not None:
        todo = todo[:max(0, int(limit))]
    path = L.ledger_path(root, group, fingerprint)

    def sink(records):
        L.append(path, records)
        if progress:
            progress(records)

    count = _run(group, todo, workers, sink)
    return {"group": group, "fingerprint": fingerprint, "measured": count,
            "still_missing": len(missing(root, group, tasks))}


def deviation(first: dict, second: dict) -> float:
    worst = 0.0
    for name in sorted(set(first) | set(second)):
        a, b = first.get(name) or {}, second.get(name) or {}
        if bool(a.get("valid")) != bool(b.get("valid")):
            return math.inf
        if a.get("valid"):
            x, y = float(a["value"]), float(b["value"])
            worst = max(worst, abs(x - y) / max(abs(x), abs(y), 1e-12))
    return worst


def attest(root, group: str, *, sample: int, seed: int = 0, tolerance: float = DEFAULT_TOLERANCE) -> dict:
    if group == G.GEOMETRY:
        raise G.ProbeGroupError("the geometry group is attested by tools/adopt_calibration.py")
    fingerprint = G.group_fingerprint(group, root)
    held = L.measured(root, group, fingerprint)
    chosen = random.Random(seed).sample(sorted(held), min(int(sample), len(held)))
    out = []
    for key in chosen:
        original = held[key]
        task = {"key": key, "family": original["family"], "parameter": original["parameter"],
                "seed": original["seed"]}
        again = measure_task(group, task)
        worst = deviation(original["channels"], again["channels"])
        out.append({"kind": L.ATTEST, "of": original["hash"], "cell": key, "values": again["values"],
                    "identical": again["values"] == original["values"],
                    "max_relative_deviation": None if math.isinf(worst) else worst,
                    "agrees": worst <= tolerance, "tolerance": tolerance, "host": again["host"],
                    "utc": again["utc"], "environment": again["environment"]})
    L.append(L.ledger_path(root, group, fingerprint), out)
    return {"group": group, "fingerprint": fingerprint, "attested": len(out),
            "agree": sum(1 for r in out if r["agrees"]), "identical": sum(1 for r in out if r["identical"])}


def status(root, tasks: list[dict]) -> list[dict]:
    keys = {t["key"] for t in tasks}
    out = []
    for group, fingerprint in G.current_fingerprints(root).items():
        held = L.measured(root, group, fingerprint)
        older = [p.stem for p in (L.ledger_dir(root) / group).glob("*.jsonl") if p.stem != fingerprint] \
            if (L.ledger_dir(root) / group).is_dir() else []
        out.append({"group": group, "fingerprint": fingerprint, "channels": list(G.channels_of(group)),
                    "planned": len(keys), "held": len(keys & set(held)), "missing": len(keys - set(held)),
                    "older_fingerprints": sorted(older)})
    return out


def content_root(root, fingerprints: dict[str, str], cells=None) -> str:
    wanted = None if cells is None else {str(c) for c in cells}
    values = [r["values"] for group, fp in sorted(fingerprints.items())
              for key, r in L.measured(root, group, fp).items() if wanted is None or key in wanted]
    return L.merkle_root(values)


def view_snapshot(root, cells=None) -> dict:
    fingerprints = G.current_fingerprints(root)
    found = L.snapshot(root, fingerprints, cells)
    found["content_root"] = content_root(root, fingerprints, cells)
    return found
