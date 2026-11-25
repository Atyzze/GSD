from __future__ import annotations

from graph_scale_dynamics.domain.model import ensemble_code
from graph_scale_dynamics.dsl.dsl import dynamics_record
from graph_scale_dynamics.scaleflow.flow import summary_dimensions as _summary_dims
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path

from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.research.landscape_audit import CONNECTIVITY_FLOOR
from graph_scale_dynamics.research.stability_score import (
    STABILITY_SCORE_CONTRACT, contracting_probes, metric_class_diagnostic,
)
from graph_scale_dynamics.scaleflow.probes import PROBES
from graph_scale_dynamics.scheduling.base_block import (
    BASE_BLOCK_CONTRACT,
    DEFAULT_BASE_SIZES, base_sizes as _spec_base_sizes,
    extension_sizes as _spec_extension_sizes)
from graph_scale_dynamics.domain.model import content_hash
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION

OP_SHORT = {"edge_count": "E", "degree_anchor": "(d-{k})²", "degree_anchor_abs": "|d-{k}|",
            "degree_square_sum": "Σd²", "degree_cube_sum": "Σd³", "degree_fourth_sum": "Σd⁴",
            "degree_neighbor_gradient": "Σₑ(Δd)²", "wedge_count": "Λ",
            "triangle_count": "△", "triangle_edge_overlap": "△overlap",
            "square_count": "□", "induced_square_count": "□ind",
            "square_edge_overlap": "□overlap", "ollivier_curvature": "κ"}
SCALE_SHORT = {"one": "", "log_N": "·lnN", "inv_log_N": "/lnN", "inv_N": "/N",
               "inv_sqrt_N": "/√N"}

from graph_scale_dynamics.observability import live_panel as _live_panel
from graph_scale_dynamics.services.api import landscape_chains as _chains
from graph_scale_dynamics.services.api.law_order import LATTICE_WHO, campaign_number, graph_number, law_rank


def _law_label(spec: dict) -> str:
    parts = []
    for term in spec.get("terms", []):
        op = OP_SHORT.get(term.get("op"), term.get("op", "?")).format(**term.get("params", {}))
        coeff = term.get("coeff") or {}
        scale = SCALE_SHORT.get(coeff.get("scale"), f"·N^{coeff.get('p', '?')}")
        try:
            c0 = f"{float(coeff.get('c0', 0)):+g}"
        except (TypeError, ValueError):
            c0 = str(coeff.get("c0", "?"))
        parts.append(f"{c0}{scale} {op}")
    return "  ".join(parts) or "?"


def _latest_dimension(entry: dict, metric: str):
    for row in reversed(entry.get("rungs") or []):
        if row.get(metric) is not None:
            n = row.get("n")
            return round(float(row[metric]), 3), "latest_rung", (int(n) if n is not None else None)
    return None, None, None


def reading_support(entry: dict, metric: str, n) -> dict | None:
    rows = sorted(entry.get("rungs") or [], key=lambda r: int(r.get("n") or 0))
    at = next((r for r in rows if r.get("n") == n), None)
    if at is None:
        return None
    summary = at.get("summary") or {}
    of = int(summary.get("seeds") or 0)
    share = summary.get(f"{metric}_valid_fraction")
    above = []
    for row in rows:
        found = row.get("summary") or {}
        if int(row.get("n") or 0) > int(n) and not found.get(f"{metric}_valid_fraction"):
            reasons = ((found.get("probe_refusals") or {}).get(metric)) or {}
            above.append([int(row["n"]), max(reasons, key=lambda k: (reasons[k], k)) if reasons else None])
    return {"n": int(n), "seeds": round(float(share) * of) if isinstance(share, (int, float)) and of else None,
            "of": of or None, "refused_above": above}


def _score_candidate(entry: dict, *, floors: dict, phenotype: dict | None = None,
                     base_rungs: frozenset[int] | None = None,
                     floors_by_n: dict | None = None,
                     connectivity_floor: float | None = None,
                     control_reference: dict | None = None) -> dict:
    from graph_scale_dynamics.research.score_door import score_evidence
    if phenotype and phenotype.get("contract") == BASE_BLOCK_CONTRACT:
        scored = score_evidence(phenotype=phenotype, floors=floors, floors_by_n=floors_by_n,
                                 connectivity_floor=connectivity_floor,
                                 control_reference=control_reference)
        return {"score_status": "base", "score_model": STABILITY_SCORE_CONTRACT,
                "source": "phenotype", "blocks": scored["blocks"], "buckets": scored["buckets"],
                "control_family": scored.get("control_family") or {},
                "plateau_break": scored.get("plateau_break") or {},
                "valid_rungs": scored["valid_rungs"], "evidence": {"measured_base_rungs": len(phenotype.get("base_sizes") or []),
                                                             "top_rung": _top_rung(
                                                                 list(phenotype.get("per_n") or phenotype.get("base_sizes") or [])
                                                                 + list(phenotype.get("extension_sizes") or [])
                                                                 + [r.get("n") for r in entry.get("rungs") or []])}}
    base_rungs = base_rungs or frozenset(DEFAULT_BASE_SIZES)
    rows = sorted((r for r in entry.get("rungs") or [] if r.get("n") in base_rungs),
                  key=lambda r: int(r["n"]))
    scored = score_evidence(
        rows=[{"n": r["n"], "summary": r.get("summary") or {},
          "terminal_classification": r.get("terminal_classification"),
          "chains_verdict": r.get("chains_verdict")} for r in rows],
        floors=floors, connectivity_floor=(CONNECTIVITY_FLOOR if connectivity_floor is None else connectivity_floor),
        floors_by_n=floors_by_n, control_reference=control_reference,
    )
    depth = len(rows)
    return {
        "score_status": "base" if depth >= len(base_rungs) else "partial",
        "score_model": STABILITY_SCORE_CONTRACT,
        "source": "rung_summaries",
        "blocks": scored["blocks"],
        "buckets": scored["buckets"],
        "valid_rungs": scored["valid_rungs"],
        "control_family": scored.get("control_family") or {},
        "plateau_break": scored.get("plateau_break") or {},
        "evidence": {"measured_base_rungs": depth,
                     "top_rung": _top_rung([r.get("n") for r in entry.get("rungs") or []])},
    }

def stability_fields(score: dict) -> dict:
    return {
        "stability_valid_rungs": score["valid_rungs"],
        "stability_control_family": (score.get("control_family") or {}).get("family"),
        "stability_plateau_break": ((score.get("plateau_break") or {}).get("breaks") or [None])[-1],
        "stability_top_rung": (score.get("evidence") or {}).get("top_rung"),
        "stability_contracting_probes": contracting_probes(score.get("buckets")),
        "stability_contracting_tier": len(contracting_probes(score.get("buckets"))),
    }


def in_contracting_band(point: dict) -> bool:
    return bool(point.get("stability_contracting_probes"))


ENGINE_CLASSES = ("priority_1", "running", "held", "undecided", "finished")


def engine_class(decision: dict | None) -> int:
    if not decision:
        return ENGINE_CLASSES.index("undecided")
    action = decision.get("action")
    if action == "run_next":
        return ENGINE_CLASSES.index("priority_1" if decision.get("priority") == 1 else "running")
    if action == "hold":
        return ENGINE_CLASSES.index("held")
    return ENGINE_CLASSES.index("finished")


BAND_EINSTEIN = "einstein"
BAND_TIER4 = "tier4"
BAND_TIER3 = "tier3"
BAND_TIER2 = "tier2"
BAND_CONTRACTING = "contracting"
BAND_FLOWING = "flowing"
LANDSCAPE_BANDS: tuple[str, ...] = (BAND_EINSTEIN, BAND_TIER4, BAND_TIER3, BAND_TIER2, BAND_CONTRACTING, BAND_FLOWING)

SETTLED_BANDS = frozenset({BAND_EINSTEIN, BAND_TIER4, BAND_TIER3, BAND_TIER2, BAND_CONTRACTING})


def withheld_readings(entry: dict, point: dict) -> dict:
    out = {}
    keys = {"d_s": "d_s_estimate", "d_V": "d_v_estimate", "d_B": "d_b_estimate", "d_w": "d_w_estimate"}
    for probe, key in keys.items():
        if point.get(key) is not None:
            continue
        for row in reversed(entry.get("rungs") or []):
            found = ((row.get("summary") or {}).get("withheld") or {}).get(probe) or {}
            mean = found.get("mean")
            if isinstance(mean, (int, float)) and not isinstance(mean, bool) and math.isfinite(mean):
                out[probe] = {"value": round(float(mean), 3), "n": row.get("n"), "seeds": found.get("seeds"),
                              "reasons": dict(found.get("reasons") or {})}
                break
    return out


TOP_BAND_MIN_TIER = 3
ALL_PROBES_TIER = 4


def contracting_tier(point: dict) -> int:
    return len(point.get("stability_contracting_probes") or ())


def einstein_reading(point: dict) -> dict | None:
    from graph_scale_dynamics.observability import law_score as _law_score
    values = {"d_s": point.get("d_s_estimate"), "d_V": point.get("d_v_estimate"),
              "d_B": point.get("d_b_estimate"), "d_w": point.get("d_w_estimate")}
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(float(v)) for v in values.values()):
        return None
    off = _law_score.residual({k: float(v) for k, v in values.items()})
    if off is None:
        return None
    allowed = _law_score.tau()
    return {"residual": round(off, 4), "tau": allowed, "agree": off <= allowed}


def band_of_items(items: dict | None) -> str:
    from graph_scale_dynamics.observability import law_score as _law_score
    if not items:
        return BAND_FLOWING
    settled, einstein = _law_score.settled_items(items)
    if settled >= ALL_PROBES_TIER:
        return BAND_EINSTEIN if einstein else BAND_TIER4
    return {3: BAND_TIER3, 2: BAND_TIER2, 1: BAND_CONTRACTING}.get(settled, BAND_FLOWING)


def settled_probes(items: dict | None) -> list[str]:
    from graph_scale_dynamics.observability import law_score as _law_score
    return [probe for probe in _law_score.PROBES if int((items or {}).get(probe) or 0) >= 2]


def score_bands(point: dict) -> None:
    from graph_scale_dynamics.observability import law_score as _law_score
    found = point.get("law_score") or {}
    twins, every = _law_score.best_items(found, lattices=False), _law_score.best_items(found, lattices=True)
    point["landscape_band"] = band_of_items(twins)
    point["landscape_band_with_lattices"] = band_of_items(every)
    point["settled_probes"] = settled_probes(twins)
    point["settled_probes_with_lattices"] = settled_probes(every)
    point["contracting_band"] = point["landscape_band"] in SETTLED_BANDS


def landscape_band(point: dict) -> str:
    if (point.get("law_score") or {}).get("parts") is not None:
        score_bands(point)
        return point["landscape_band"]
    tier = contracting_tier(point)
    if tier >= ALL_PROBES_TIER:
        found = einstein_reading(point)
        point["einstein"] = found
        return BAND_EINSTEIN if found and found["agree"] else BAND_TIER4
    if tier >= TOP_BAND_MIN_TIER:
        return BAND_TIER3
    if tier == 2:
        return BAND_TIER2
    if in_contracting_band(point):
        return BAND_CONTRACTING
    return BAND_FLOWING


def gates_ledger(repo, spec: dict, *, campaign_id: str | None = None, top: list | None = None) -> dict | None:
    from graph_scale_dynamics.decisions.engine import Policy
    try:
        policy = Policy.from_spec(spec)
    except ValueError:
        return None
    if not policy.let_through_rule:
        return None
    from graph_scale_dynamics.db.decision_store import let_through_ledger
    key = str(getattr(repo, "db_target", "") or id(repo)) + ":landscape"
    priced = bool(policy.ledger_counts_priced)
    if campaign_id is None or top is None:
        return let_through_ledger(repo.conn, key, counts_priced=priced).document(policy)
    scores = {(str(row.get("campaign_id") or campaign_id), str(row["candidate_id"])):
              (row.get("law_score") or {}).get("score") for row in top if row.get("candidate_id")}
    lowest = min((v for v in scores.values() if isinstance(v, (int, float))), default=0)
    return dict(let_through_ledger(repo.conn, key, counts_priced=priced).document(policy, scores=scores),
                scored_from=[str(campaign_id)], scored_at_least=bool(len(top) >= TOP_LIMIT and lowest > 0))


NO_READING_FROM_EMPTY = "no_reading_from_empty"
TOP_LIMIT = 100


def marked(point: dict, marks: dict) -> dict:
    law = str(point.get("candidate_id"))
    region = (marks.get("regions") or {}).get(law)
    point["kind"] = (marks.get("kinds") or {}).get(law)
    point["group"] = marks.get("group")
    point["batch"] = marks.get("batch")
    point["region"] = None if region is None else {"of": region["region"], "state": region["state"],
                                                    "kind": region.get("kind")}
    return point


def top_candidates_of(scored: list[dict], refused: list[dict], deepest: dict, limit: int = TOP_LIMIT) -> list[dict]:
    def _scores(row: dict) -> bool:
        return int((row.get("law_score") or {}).get("score") or 0) > 0
    listed = sorted(list(scored) + [scored_refusal(row) for row in refused if _scores(row)], key=law_rank)[:limit]
    room = limit - len(listed)
    unscored = sorted((row for row in refused if not _scores(row)),
                      key=lambda row: (-int(deepest.get(row["candidate_id"]) or 0), campaign_number(row),
                                       graph_number(row), row["candidate_id"]))
    return listed + [scored_refusal(row) for row in unscored[:max(room, 0)]]


def scored_refusal(row: dict) -> dict:
    return {"candidate_id": row["candidate_id"], "state": row.get("state"), "law": row.get("law"),
            "ensemble_code": row.get("ensemble_code"), "terms": row.get("terms") or [],
            "regime": row.get("regime") or "equilibrium", "law_dynamics": row.get("law_dynamics"),
            "visual_grammar_version": "hamiltonian-visual-1",
            "d_s_estimate": None, "d_s_source": None, "d_s_estimate_n": None, "d_v_estimate": None,
            "d_v_source": None, "d_b_estimate": None, "d_b_source": None, "d_w_estimate": None, "d_w_source": None,
            "unfiltered": bool(row.get("unfiltered")), "mean_degree": row.get("mean_degree"),
            "limit_hits": row.get("limit_hits") or [], "small_world_fraction": None,
            "stability_contracting_probes": [], "stability_contracting_tier": 0,
            "contracting_band": False, "landscape_band": NO_READING_FROM_EMPTY,
            "law_score": row.get("law_score")}


def reading_lost_at(entry: dict) -> int | None:
    rungs = entry.get("rungs") or []
    if not rungs or rungs[-1].get("n") is None:
        return None
    _, _, read_at = _latest_dimension(entry, "d_s")
    top = int(rungs[-1]["n"])
    return top if read_at is not None and top > read_at else None


SMALL_WORLD_FROM = 1024


def _mean(summary: dict, key: str):
    node = summary.get(key)
    return node.get("mean") if isinstance(node, dict) else None


def small_world(entry: dict, connectivity_floor: float | None = None) -> dict | None:
    rows = [r for r in entry.get("rungs") or []
            if r.get("n") is not None and int(r["n"]) >= SMALL_WORLD_FROM]
    summaries = [r.get("summary") or {} for r in rows]
    found = metric_class_diagnostic([_mean(x, "half_volume_radius") for x in summaries],
                                    [_mean(x, "connected_fraction") for x in summaries],
                                    [int(r["n"]) for r in rows], connectivity_floor=connectivity_floor)
    if found.get("verdict") != "no_metric_structure":
        return None
    return {"sizes": found.get("sizes"), "radius_growth": found.get("radius_growth"),
            "volume_growth": found.get("volume_growth"),
            "reading": "its radius grows like ln N on the rungs its readings come from: a small world, no "
                       "dimension to read, so no probe counts as settled"}


def apply_small_world(point: dict, entry: dict, connectivity_floor: float | None = None) -> dict:
    found = small_world(entry, connectivity_floor)
    if found is not None:
        point["small_world"] = found
        point["stability_contracting_probes"] = []
        point["stability_contracting_tier"] = 0
    return point


def _top_rung(ns) -> int | None:
    values = []
    for value in (ns or []):
        try:
            values.append(int(value))
        except (TypeError, ValueError):
            continue
    return max(values) if values else None


def _classification(summary, limits) -> str | None:
    from graph_scale_dynamics.readmodel.rung_classification import classification_from_summary
    stored = (summary or {}).get("rung_terminal_classification")
    return stored or classification_from_summary(summary or {}, limits)


def chain_point(cid: str, entry: dict, score: dict, meta: dict, law_score: dict | None,
                connectivity_floor: float | None) -> dict:
    point = {"candidate_id": cid, "state": meta.get("state"), "law": meta.get("law"),
             "ensemble_code": meta.get("ensemble_code"), "terms": meta.get("terms") or [],
             "regime": meta.get("regime") or "equilibrium", "law_dynamics": meta.get("law_dynamics"),
             "visual_grammar_version": "hamiltonian-visual-1", "unfiltered": bool(meta.get("unfiltered"))}
    for probe, key in (("d_s", "d_s"), ("d_V", "d_v"), ("d_B", "d_b"), ("d_w", "d_w")):
        value, source, n = _latest_dimension(entry, probe)
        point.update({f"{key}_estimate": value, f"{key}_source": source, f"{key}_estimate_n": n})
    top = ((entry.get("rungs") or [{}])[-1].get("summary")) or {}
    point["mean_degree"] = (top.get("mean_degree") or {}).get("mean") if isinstance(top.get("mean_degree"), dict) else None
    point["small_world_fraction"] = top.get("small_world_fraction")
    point.update(stability_fields(score))
    apply_small_world(point, entry, connectivity_floor)
    point["law_score"] = law_score
    point["contracting_band"] = in_contracting_band(point)
    point["landscape_band"] = landscape_band(point)
    return point


def chain_landscape(rows, spec: dict, by_id: dict, candidate_meta: dict, *, board, floors, base_rungs,
                    floors_by_n, connectivity_floor, control_reference) -> dict:
    from graph_scale_dynamics.observability import law_score as _law_score, score_board as _score_board
    seeds = _chains.chain_seeds(rows)
    names, points, counts = ["empty"], {}, {}
    for key, shown in _chains.chain_names(spec):
        names.append(shown)
        drawn = []
        for cid in sorted(by_id):
            per_n = seeds.get((cid, key)) or {}
            rungs = []
            for n in sorted(per_n):
                summary = _chains.chain_summary(per_n[n])
                rungs.append({"n": n, "summary": summary} | _summary_dims(summary))
            entry = {"rungs": rungs}
            if not any(row.get(probe) is not None for row in rungs for probe in PROBES):
                continue
            score = _score_candidate(entry, floors=floors, base_rungs=base_rungs, floors_by_n=floors_by_n,
                                     connectivity_floor=connectivity_floor, control_reference=control_reference)
            top_n = max((int(r["n"]) for r in by_id[cid].get("rungs") or []), default=None)
            law = (_score_board.of(board, cid) if top_n is not None and top_n >= _law_score.LADDER[0]
                   else _law_score.zero(top_n))
            drawn.append(chain_point(cid, entry, score, candidate_meta.get(cid) or {}, law, connectivity_floor))
        points[shown] = drawn
        counts[shown] = {"measured_candidates": len(drawn),
                         "band_candidates": {band: sum(1 for p in drawn if p["landscape_band"] == band)
                                             for band in LANDSCAPE_BANDS},
                         **{f"{probe}_estimates": sum(1 for p in drawn if p[f"{key}_estimate"] is not None)
                            for probe, key in (("d_s", "d_s"), ("d_V", "d_v"), ("d_B", "d_b"), ("d_w", "d_w"))}}
    return {"contract": _chains.CHAINS_CONTRACT, "names": names, "points": points, "counts": counts}


def build_landscape(repo: Repo, campaign_id: str) -> dict:
    campaign = repo.campaign(campaign_id)
    if not campaign:
        raise ValueError(f"unknown campaign {campaign_id}")
    version = campaign["spec"].get("analysis_version", ANALYSIS_VERSION)
    _spec_limits = (campaign["spec"] or {}).get("limits") or {}
    try:
        base_rungs = frozenset(int(n) for n in (_spec_base_sizes(campaign["spec"]) or DEFAULT_BASE_SIZES))
        base_rungs |= frozenset(int(n) for n in _spec_extension_sizes(campaign["spec"]))
    except ValueError:
        base_rungs = frozenset(DEFAULT_BASE_SIZES)

    by_id: dict[str, dict] = {}
    measured_rung_rows = 0
    valid_dimension_rung_rows = 0
    latest_rung_utc = ""
    for row in repo.conn.execute(
        "SELECT candidate_id,n,summary_json,created_utc FROM rung_summaries "
        "WHERE campaign_id=? AND analysis_version=? ORDER BY candidate_id,n",
        (str(campaign_id), version),
    ):
        measured_rung_rows += 1
        latest_rung_utc = max(latest_rung_utc, str(row["created_utc"] or ""))
        summary = json.loads(row["summary_json"])
        dims = {"n": int(row["n"]), "summary": summary} | _summary_dims(summary)
        entry = by_id.setdefault(str(row["candidate_id"]), {"rungs": []})
        entry["rungs"].append(dims)
        if all(dims.get(probe) is None for probe in PROBES):
            continue
        valid_dimension_rung_rows += 1

    latest_decisions = repo.latest_engine_decisions(str(campaign_id))
    from graph_scale_dynamics.observability import law_score as _law_score, score_board as _score_board
    board = _score_board.board(repo, str(campaign_id))
    from graph_scale_dynamics.operations import study_map as _study_map
    marks = {"kinds": board.get("kinds") or {}, "regions": _study_map.regions_of_laws(repo),
             "group": ((campaign.get("spec") or {}).get("study_design") or {}).get("group"),
             "batch": str(campaign_id)}
    latest_decision_utc = max((str(d.get("created_utc") or "") for d in latest_decisions.values()), default="")

    ordinals: dict[str, dict[int, int]] = {}
    for row in repo.conn.execute(
        "SELECT candidate_id,n,MIN(graph_ordinal) AS ordinal FROM jobs "
        "WHERE campaign_id=? AND kind='simulate' AND graph_ordinal IS NOT NULL "
        "GROUP BY candidate_id,n", (str(campaign_id),)
    ):
        ordinals.setdefault(str(row["candidate_id"]), {})[int(row["n"])] = int(row["ordinal"])

    unfiltered_ids = repo.unfiltered_candidate_ids(str(campaign_id))
    candidate_meta = {}
    for row in repo.conn.execute(
        "SELECT candidate_id,state,spec_json FROM candidates WHERE campaign_id=?",
        (str(campaign_id),)
    ):
        spec = json.loads(row["spec_json"] or "{}")
        cid = str(row["candidate_id"])
        candidate_meta[cid] = {
            "state": row["state"],
            "law": _law_label(spec),
            "terms": spec.get("terms") or [],
            "law_dynamics": (record := dynamics_record(spec)),
            "regime": record["regime"],
            "ensemble_code": ensemble_code(ordinals.get(cid) or {}),
            "unfiltered": cid in unfiltered_ids,
        }

    from graph_scale_dynamics.research.stability_score import noise_floors, noise_floors_by_n, TOLERANCE_MULTIPLIER
    from graph_scale_dynamics.calibration import durable_artifact_path, load_table
    from graph_scale_dynamics.scheduling.limits import connectivity_floor as _limits_conn_floor
    _spec_conn_floor = _limits_conn_floor(campaign["spec"])
    _table = load_table(durable_artifact_path())
    floors = noise_floors(_table)
    floors_by_n = noise_floors_by_n(_table)
    from graph_scale_dynamics.research.stability_score import control_family_reference
    _control_reference = control_family_reference(_table)
    phenotype_by_id: dict[str, dict] = {}
    for row in repo.conn.execute(
        "SELECT candidate_id,phenotype_json FROM four_rung_phenotypes "
        "WHERE campaign_id=? AND analysis_version=?", (str(campaign_id), version),
    ):
        try:
            phenotype_by_id[str(row["candidate_id"])] = json.loads(row["phenotype_json"])
        except (TypeError, ValueError):
            continue
    from graph_scale_dynamics.scaleflow.probes import LIMIT_TERMINALS
    points: list[dict] = []
    scored: list[dict] = []
    refused: list[dict] = []
    for cid in sorted(by_id):
        entry = by_id[cid]
        ds, ds_source, ds_n = _latest_dimension(entry, "d_s")
        dh, dh_source, dh_n = _latest_dimension(entry, "d_V")
        db, db_source, db_n = _latest_dimension(entry, "d_B")
        dw, dw_source, dw_n = _latest_dimension(entry, "d_w")
        top = (entry.get("rungs") or [{}])[-1]
        top_summary = top.get("summary") or {}
        mean_degree = ((top_summary.get("mean_degree") or {}).get("mean")
                       if isinstance(top_summary.get("mean_degree"), dict) else None)
        limit_hits = sorted({
            int(r["n"]) for r in entry.get("rungs") or []
            if str(_classification(r.get("summary"), _spec_limits) or "") in LIMIT_TERMINALS})
        if ds is None and dh is None and db is None and dw is None:
            top_n = max((int(r["n"]) for r in entry.get("rungs") or []), default=None)
            refused.append({
                "candidate_id": cid,
                "law_score": (_score_board.of(board, cid) if top_n is not None and top_n >= _law_score.LADDER[0]
                              else _law_score.zero(top_n)),
                "state": (candidate_meta.get(cid) or {}).get("state"),
                "law": (candidate_meta.get(cid) or {}).get("law"),
                "terms": (candidate_meta.get(cid) or {}).get("terms") or [],
                "regime": (candidate_meta.get(cid) or {}).get("regime") or "equilibrium",
                "law_dynamics": (candidate_meta.get(cid) or {}).get("law_dynamics"),
                "ensemble_code": (candidate_meta.get(cid) or {}).get("ensemble_code"),
                "measured_rungs": len(entry.get("rungs") or []),
                "unfiltered": bool((candidate_meta.get(cid) or {}).get("unfiltered")),
                "mean_degree": mean_degree,
                "limit_hits": limit_hits,
                "top_classification": _classification(top_summary, _spec_limits),
            })
            continue
        score = _score_candidate(entry, floors=floors, phenotype=phenotype_by_id.get(cid),
                                 base_rungs=base_rungs, floors_by_n=floors_by_n,
                                 connectivity_floor=_spec_conn_floor,
                                 control_reference=_control_reference)
        point = {
            "candidate_id": cid,
            "state": (candidate_meta.get(cid) or {}).get("state"),
            "law": (candidate_meta.get(cid) or {}).get("law"),
            "ensemble_code": (candidate_meta.get(cid) or {}).get("ensemble_code"),
            "terms": (candidate_meta.get(cid) or {}).get("terms") or [],
            "regime": (candidate_meta.get(cid) or {}).get("regime") or "equilibrium",
            "law_dynamics": (candidate_meta.get(cid) or {}).get("law_dynamics"),
            "visual_grammar_version": "hamiltonian-visual-1",
            "d_s_estimate": ds,
            "d_s_source": ds_source,
            "d_s_estimate_n": ds_n,
            "d_v_estimate": dh,
            "d_v_source": dh_source,
            "d_b_estimate": db,
            "d_b_source": db_source,
            "d_w_estimate": dw,
            "d_w_source": dw_source,
            "unfiltered": bool((candidate_meta.get(cid) or {}).get("unfiltered")),
            "mean_degree": mean_degree,
            "limit_hits": limit_hits,
            "small_world_fraction": top_summary.get("small_world_fraction"),
            "readings_from": {probe: reading_support(entry, metric, n) for probe, metric, n in (
                ("d_s", "d_s", ds_n), ("d_V", "d_V", dh_n), ("d_B", "d_B", db_n), ("d_w", "d_w", dw_n))
                if n is not None},
            **stability_fields(score),
        }
        lost_at = reading_lost_at(entry)
        if lost_at is not None:
            point["d_s_reading_lost_at"] = lost_at
            point["stability_contracting_probes"] = [p for p in point["stability_contracting_probes"] if p != "d_s"]
            point["stability_contracting_tier"] = len(point["stability_contracting_probes"])
        apply_small_world(point, entry, _spec_conn_floor)
        top_n = max((int(r["n"]) for r in entry.get("rungs") or []), default=None)
        point["law_score"] = (_score_board.of(board, cid) if top_n is not None and top_n >= _law_score.LADDER[0]
                              else _law_score.zero(top_n))
        point["contracting_band"] = in_contracting_band(point)
        point["landscape_band"] = landscape_band(point)
        if point["landscape_band"] in SETTLED_BANDS and not point.get("small_world"):
            withheld = withheld_readings(entry, point)
            if withheld:
                point["withheld"] = withheld
        points.append(point)
        scored.append(point)
    every_chain = chain_landscape(
        repo.conn.execute(_chains.ROWS_SQL, (str(campaign_id), version)).fetchall(), campaign["spec"], by_id,
        candidate_meta, board=board, floors=floors, base_rungs=base_rungs, floors_by_n=floors_by_n,
        connectivity_floor=_spec_conn_floor, control_reference=_control_reference)
    deepest = {cid: max((int(r["n"]) for r in entry.get("rungs") or []), default=0) for cid, entry in by_id.items()}
    for point in [*points, *refused, *(p for drawn in every_chain["points"].values() for p in drawn)]:
        marked(point, marks)
    top_candidates = top_candidates_of(scored, refused, deepest)
    for row in top_candidates:
        row["engine_decision"] = latest_decisions.get(row["candidate_id"])
        row["engine_class"] = ENGINE_CLASSES[engine_class(row["engine_decision"])]

    exposure = repo.conn.execute(
        "SELECT COUNT(*) AS opportunities,COUNT(DISTINCT dependence_unit_id) AS dependence_units,"
        "COALESCE(SUM(CASE WHEN selected<>0 THEN 1 ELSE 0 END),0) AS selected "
        "FROM proposal_exposures WHERE campaign_id=?",
        (str(campaign_id),),
    ).fetchone() or {}
    counts = {
        "measured_candidates": len(points),
        "unfiltered_measured": sum(1 for p in points if p.get("unfiltered")),
        "refused_candidates": len(refused),
        "limit_hit_candidates": sum(1 for r in refused if r["limit_hits"]) + sum(1 for p in points if p["limit_hits"]),
        "d_s_estimates": sum(1 for p in points if p["d_s_estimate"] is not None),
        "d_V_estimates": sum(1 for p in points if p["d_v_estimate"] is not None),
        "d_B_estimates": sum(1 for p in points if p["d_b_estimate"] is not None),
        "d_w_estimates": sum(1 for p in points if p["d_w_estimate"] is not None),
        "score_contracting_candidates": sum(1 for p in points if p["stability_contracting_probes"]),
        "small_world_candidates": sum(1 for p in points if p.get("small_world")),
        "contracting_band_candidates": sum(1 for p in points if p["contracting_band"]),
        "tier_candidates": {
            str(tier): sum(1 for p in points if contracting_tier(p) == tier)
            for tier in range(len(PROBES) + 1)
        },
        "band_candidates": {
            band: sum(1 for p in points if p["landscape_band"] == band)
            for band in LANDSCAPE_BANDS
        },
        "measured_rung_rows": measured_rung_rows,
        "valid_dimension_rung_rows": valid_dimension_rung_rows,
    }
    revision = content_hash({
        "campaign_id": str(campaign_id), "analysis_version": version,
        "latest_rung_utc": latest_rung_utc, "latest_decision_utc": latest_decision_utc,
        "counts": counts, "exposure": dict(exposure), "points": points, "top_candidates": top_candidates,
        "refused": len(refused), "every_chain": every_chain,
    })[:20]
    return {
        "campaign_id": str(campaign_id),
        "analysis_version": version,
        "revision": revision,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": counts,
        "exposure": {
            "opportunities": int(exposure.get("opportunities", 0) or 0),
            "dependence_units": int(exposure.get("dependence_units", 0) or 0),
            "selected": int(exposure.get("selected", 0) or 0),
        },
        "dimension_points": points,
        "every_chain": every_chain,
        "refused_candidates": [],
        "limits": campaign["spec"].get("limits") or {},
        "selection": _live_panel.selection_summary(campaign["spec"] or {}),
        "gates_ledger": gates_ledger(repo, campaign["spec"] or {}, campaign_id=str(campaign_id), top=top_candidates),
        "top_candidates": top_candidates,
        "lattice_who": list(LATTICE_WHO),
        "score_model": {
            "id": STABILITY_SCORE_CONTRACT,
            "reporting_only": True,
            "search_policy_reads_score": False,
            "definition": ("each probe's and the mean degree's settling over the law's valid rungs and its bucket; "
                           "a gate (metric class, control family, density) relabels a settled "
                           "block"),
            "noise_floors": floors,
            "noise_floors_by_n": floors_by_n,
            "tolerance_multiplier": TOLERANCE_MULTIPLIER,
            "note": "Insight/ranking only. Evaluator, proposer, promoter and scheduler never consult this score.",
        },
        "contract": "gsd-authoritative-landscape-3",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--meta", required=True)
    parser.add_argument("--inputs")
    args = parser.parse_args(argv)
    from graph_scale_dynamics.operations.subprocesses import yield_to_the_fleet
    yield_to_the_fleet()

    with Repo(args.db) as repo:
        repo.publish_runtime_imports("landscape-worker")
        payload = build_landscape(repo, args.campaign)

    target = Path(args.output)
    meta_target = Path(args.meta)
    target.parent.mkdir(parents=True, exist_ok=True)
    body_tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    meta_tmp = meta_target.with_name(f".{meta_target.name}.{os.getpid()}.tmp")
    body_tmp.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    meta_payload = {
        "campaign_id": payload["campaign_id"],
        "revision": payload["revision"],
        "generated_utc": payload["generated_utc"],
        "counts": payload["counts"],
        "exposure": payload["exposure"],
        "score_model": payload["score_model"]["id"],
        "contract": payload["contract"],
        **({"inputs": args.inputs} if args.inputs else {}),
    }
    meta_tmp.write_text(json.dumps(meta_payload, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    os.replace(body_tmp, target)
    os.replace(meta_tmp, meta_target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
