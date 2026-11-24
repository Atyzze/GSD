#!/usr/bin/env python3
from __future__ import annotations

import gc
import json
from pathlib import Path

from graph_scale_dynamics.measurements import starts as the_starts

LATTICES = tuple(start.name for start in the_starts.known_lattices())
LATTICE_DEGREE = {start.name: start.neighbours for start in the_starts.known_lattices()}
ANCHORS = ("degree_anchor", "degree_anchor_abs")


def lattices_given(fates_of_laws) -> tuple:
    seen = {name for fates in fates_of_laws for name in (fates or {})}
    return tuple(name for name in LATTICES if name in seen)


def body(part: Path) -> dict:
    from graph_scale_dynamics.research.bundle_layout import report_path
    try:
        found = report_path(Path(part), "28")
    except FileNotFoundError:
        return {}
    return json.loads(found.read_text(encoding="utf-8")).get("body") or {}


def bodies(part: Path):
    for report in sorted(Path(part).rglob("28-decision-engine.json")):
        yield json.loads(report.read_text(encoding="utf-8")).get("body") or {}


def latest(engine: dict) -> dict:
    return {str(law.get("candidate_id")): law for law in engine.get("laws") or []}


def seeds(engine: dict) -> list[dict]:
    table = engine.get("seeds") or {}
    columns = {name: i for i, name in enumerate(table.get("columns") or [])}
    laws = table.get("laws") or []
    return [{"law": str(laws[row[columns["law"]]]), "n": int(row[columns["n"]]), "seed": row[columns["seed"]],
             "ended": row[columns["ended"]] if "ended" in columns else None} for row in table.get("rows") or []]


def campaigns(root: Path) -> list[dict]:
    study = json.loads((root / "study.json").read_text(encoding="utf-8"))
    if study.get("missing"):
        names = [str((m or {}).get("campaign_id") if isinstance(m, dict) else m) for m in study["missing"]]
        raise ValueError(f"the bundle could not carry campaigns {names} (study.json's missing): its laws would be "
                         "read as none; make the bundle again once their report cycle completes")
    return [record for record in study.get("campaigns") or [] if record.get("law_budget")
            and not (record.get("study_design") or {}).get("arm")]


def law_row(row: dict, chains: dict, latest: dict, campaign: str) -> dict:
    law = str(row.get("candidate_id"))
    chain = chains.get(law) or {}
    starts = chain.get("starts_reading") or {}
    by_n = starts.get("by_n") or {}
    fate = list(row.get("fate") or [None, None]) + [None, None]
    score = chain.get("score") or {}
    return {"law": law, "campaign": campaign, "drawn": row.get("admitted_utc"), "spec": row.get("spec") or {},
            "kind": row.get("kind"), "fate": fate[0], "fate_n": fate[1],
            "mean_degree": {int(n): float(v) for n, v in (row.get("mean_degree") or {}).items() if v is not None},
            "latest": (latest.get(law) or {}).get("rule"), "class": starts.get("class"),
            "class_1024": (by_n.get("1024") or [None])[0],
            "fates": {name: (value or [None])[0] for name, value in (starts.get("fates") or {}).items()},
            "score": score.get("score"), "score_by": score.get("by"), "top_n": chain.get("top_n")}


def rows(root: Path) -> list[dict]:
    out = []
    for record in campaigns(root):
        engine = body(root / str(record.get("bundle") or ""))
        chains = (engine.get("every_chain") or {}).get("laws") or {}
        last = latest(engine)
        campaign = str(record.get("campaign_id"))
        out.extend(law_row(row, chains, last, campaign) for row in (engine.get("law_ledger") or {}).get("rows") or [])
        del engine, chains, last
        gc.collect()
    return out


def drawn(root: Path) -> int:
    return sum(int(record.get("laws_drawn", record.get("laws_held")) or 0) for record in campaigns(root))


def budget(root: Path) -> int:
    return sum(int(record.get("law_budget") or 0) for record in campaigns(root))


def read_by_the_starts(row: dict) -> bool:
    return row.get("class") not in (None, "not_read")


def held(row: dict, lattice: str | None = None) -> bool:
    fates = row.get("fates") or {}
    return any(fates.get(name) == "holds" for name in ((lattice,) if lattice else LATTICES))


def anchor_degrees(row: dict) -> set[int]:
    return {int(term[1]) for term in (row.get("spec") or {}).get("terms") or []
            if term[0] in ANCHORS and term[1] is not None}


def operators(row: dict) -> set[str]:
    return {str(term[0]) for term in (row.get("spec") or {}).get("terms") or []}


def spec_of(compact: dict) -> dict:
    from graph_scale_dynamics.dsl.dsl import DSL_VERSION
    terms = []
    for op, k, c0, scale, p in compact.get("terms") or []:
        coeff = {"c0": c0, "scale": scale, **({"p": p} if p is not None else {})}
        terms.append({"op": op, "params": {} if k is None else {"k": int(k)}, "coeff": coeff})
    swap = float(compact.get("swap_share") or 0.0)
    rest = (1.0 - swap) / 2.0
    dynamics = {"kind": "equilibrium", "beta": compact.get("beta"),
                "move_mix": {"add": rest, "delete": rest, "swap": swap}, "sweeps": compact.get("sweeps")}
    if compact.get("locality"):
        dynamics["locality"] = compact["locality"]
        dynamics["local_move"] = compact.get("local_move") or "toggle"
    if compact.get("zero_temperature"):
        dynamics["zero_temperature"] = True
    return {"dsl_version": DSL_VERSION, "terms": terms, "dynamics": dynamics, "init": "empty"}


def _failed(section) -> str | None:
    if not isinstance(section, dict) or not section:
        return "absent"
    return f"failed: {section['error']}" if section.get("error") else None


def regime_of(spec: dict | None) -> str | None:
    if not spec:
        return None
    if spec.get("regime"):
        return str(spec["regime"])
    from graph_scale_dynamics.dsl.dsl import dynamics_regime
    return dynamics_regime({"dynamics": {key: spec[key] for key in ("zero_temperature", "locality", "local_move")
                                         if key in spec}})


def study(root: Path) -> dict:
    document = json.loads((Path(root) / "study.json").read_text(encoding="utf-8"))
    parts = []
    for record in document.get("campaigns") or []:
        engine = body(Path(root) / str(record.get("bundle") or ""))
        record_section = (engine.get("the_record") or {}).get("compute_by_regime")
        parts.append({"record": record, "name": str(record.get("name") or record.get("campaign_id")),
                      "campaign_id": str(record.get("campaign_id")), "engine": engine,
                      "ledger": (engine.get("law_ledger") or {}).get("rows") or [],
                      "every_chain": engine.get("every_chain") or {},
                      "failed_sections": {name: why
                                          for name, why in (("every_chain", _failed(engine.get("every_chain"))),
                                                            ("compute_by_regime", _failed(record_section))) if why},
                      "arm": (record.get("study_design") or {}).get("arm"),
                      "drawn": bool(record.get("law_budget")) and not (record.get("study_design") or {}).get("arm")})
    return {"study": document, "parts": parts, "missing": list(document.get("missing") or [])}


def drawn_laws(parts: list[dict]) -> list[dict]:
    from graph_scale_dynamics.reporting.every_chain_report import decided_law
    out = []
    for part in parts:
        if not part["drawn"]:
            continue
        scores = (part["every_chain"] or {}).get("laws") or {}
        last = latest(part["engine"])
        for row in part["ledger"]:
            spec = row.get("spec") or {}
            fate = row.get("fate") or [None, None]
            law = str(row.get("candidate_id"))
            out.append({"campaign": part["name"], "campaign_id": part["campaign_id"], "law": law, "rule": fate[0],
                        "at_n": fate[1], "zero_temperature": bool(spec.get("zero_temperature")),
                        "regime": regime_of(spec), "beta": spec.get("beta"),
                        "ops": [term[0] for term in spec.get("terms") or [] if term],
                        "drawn_utc": row.get("admitted_utc"), "score": scores.get(law),
                        "decided": decided_law(last[law]) if law in last else fate[0] is not None,
                        "failed": fate[0] == "failed"})
    return out
