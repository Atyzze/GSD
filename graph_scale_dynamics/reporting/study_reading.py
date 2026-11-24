from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.research.degree_prediction import KIND_DEGREES

READING_CONTRACT = "gsd-study-reading-3"
READABLE_CONTRACTS = (READING_CONTRACT,)
COMPARISON_CONTRACT = "gsd-study-comparison-1"
MEAN_DEGREE_BANDS = ((0, 2), (2, 4), (4, 8), (8, 12), (12, 16), (16, 24), (24, 33))

GEOMETRY = G.REFUSAL_GEOMETRY
LIMITS = G.REFUSAL_LIMITS
SAMPLING = G.REFUSAL_SAMPLING
KINDS = ("read", "geometry", "limits", "sampling", "other refusal")

DEEP_RUNGS = (16384, 65536, 262144, 1048576)
STANDINGS = ("named", "ambiguous", "none", "unranked")


def kind_of(bucket) -> str:
    if bucket is None:
        return "read"
    bucket = str(bucket)
    if bucket in GEOMETRY:
        return "geometry"
    if bucket in LIMITS:
        return "limits"
    if bucket in SAMPLING:
        return "sampling"
    return "other refusal" if bucket.startswith("REFUSED_") else "read"


def _body(part: Path | None, code: str):
    if part is None:
        return None
    for path in sorted(Path(part).glob(f"{code}-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data.get("body", data) if isinstance(data, dict) else data
    return None


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _share(part, whole):
    return round(part / whole, 4) if whole else None


def _utc(text):
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _hours(start, end):
    a, b = _utc(start), _utc(end)
    return round((b - a).total_seconds() / 3600.0, 3) if a and b else None


def short_label(quadrant: dict | None, campaign_id=None) -> str:
    quadrant = quadrant or {}
    temperature = {True: "T0", False: "finite"}.get(quadrant.get("zero_temperature"))
    cap = quadrant.get("dense_cap")
    if temperature is None or cap is None:
        return f"campaign {campaign_id}"
    return f"{temperature}/{float(cap):g}"


def read_study(root: Path) -> dict:
    root = Path(root)
    study = json.loads((root / "study.json").read_text(encoding="utf-8"))
    parts = {path.parent.name: path.parent for path in root.glob("*/manifest.json")}
    campaigns = [read_campaign(record, parts.get(str(record.get("bundle") or "")))
                 for record in study.get("campaigns") or []]
    gates = _gates_ledger(root)
    totals = _totals(campaigns)
    if gates:
        totals.pop("salt_ledger", None)
    return {"contract": READING_CONTRACT, "study_id": study.get("study_id"), "folder": study.get("folder"),
            "built_utc": study.get("built_utc"), "build_number": study.get("build_number"),
            "campaigns": campaigns, "study": totals, **({"gates_ledger": gates} if gates else {}),
            "missing": [{"campaign_id": m.get("campaign_id"), "why": m.get("why")} for m in study.get("missing") or []]}


def _gates_ledger(root: Path) -> dict:
    try:
        document = json.loads((Path(root) / "gates_ledger.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if document.get("unavailable"):
        return {"unavailable": document["unavailable"]}
    return {"from_n": document.get("from_n"), "confirm_after": document.get("confirm_after"),
            "gates": document.get("gates") or {},
            "signatures_known": sum(1 for row in document.get("signatures") or [] if row.get("known", row.get("seen_enough"))),
            "signatures": document.get("signatures_total")}


def read_campaign(record: dict, part: Path | None) -> dict:
    engine = _body(part, "28") or {}
    ranking = _body(part, "22") or {}
    decisions = [d for d in ((_body(part, "10") or {}).get("decisions") or []) if isinstance(d, dict)]
    flow = _body(part, "04") or {}
    tree = engine.get("gate_tree") or {}
    policy = engine.get("policy") or {}
    the_record = engine.get("the_record") or {}
    quadrant = record.get("quadrant") or {}
    created, reported = record.get("created_utc"), (record.get("report") or {}).get("finished_utc")
    hours = _hours(created, reported)
    held = _int(record.get("laws_held"))
    decided = _int(tree.get("laws")) or _int(engine.get("laws_decided"))
    families, standing = _families(ranking, decisions)
    replay = the_record.get("decision_record") or {}
    draws = the_record.get("draw_ledger") or {}
    return {
        "campaign_id": str(record.get("campaign_id")), "label": quadrant.get("label"),
        "short": short_label(quadrant, record.get("campaign_id")), "quadrant": quadrant,
        "d_s_shape": the_record.get("d_s_shape"),
        "law_budget": record.get("law_budget"), "laws_held": held, "state": record.get("state"),
        "laws_drawn": _int(record.get("laws_drawn", record.get("laws_held"))),
        "created_utc": created, "reported_utc": reported, "hours": hours,
        "laws_per_hour": round(held / hours) if hours and held is not None else None,
        "part": part.name if part is not None else None,
        "policy": {k: policy.get(k) for k in ("base_sizes", "deep_sizes", "deep_lane_widths", "plateau_from_n",
                                              "audit_fraction", "second_rung") if k in policy},
        "decisions": {"total": _int(engine.get("decisions")), "in_report_10": len(decisions),
                      "replayed": _int(replay.get("sampled")),
                      "mismatches": len(replay.get("mismatches") or []) if replay else None},
        "draws": {"draws": draws.get("draws"), "admitted_share": draws.get("admitted_share"),
                  "refused": {k: (v or {}).get("share") for k, v in (draws.get("refused_by_reason") or {}).items()}},
        "laws_decided": decided,
        "gates": _gates(tree, decided),
        "rungs": {str(r.get("n")): {k: r.get(k) for k in ("finished", "went_on", "went_on_by", "stopped", "held",
                                                           "salted_past", "done")}
                  for r in tree.get("rungs") or [] if isinstance(r, dict)},
        "base_block": _base_block(tree, flow, policy, decided),
        "families": families,
        "deep": _deep(tree, decisions, policy),
        "lanes": _lanes(policy, decisions, engine.get("laws") or [], standing),
        "seconds_per_seed": _seeds(engine.get("seeds") or {}),
        "core_hours_by_rung": _core_hours(the_record),
        "structure_gate": the_record.get("structure_gate"),
        "pace": _pace(decisions, reported),
        "admission": _admission(engine, _body(part, "14") or {}, policy),
        "deep_routes": _deep_routes(engine),
        "d_s_by_mean_degree": _d_s_by_mean_degree(_body(part, "05") or {}),
        "three_readings": _three_readings(the_record),
        "longer_chains": _longer_chains(decisions),
        "curvature": _curvature(engine),
        "predicted": _predicted(engine),
    }


def _predicted(engine: dict) -> dict | None:
    ledger = engine.get("law_ledger")
    if not (isinstance(ledger, dict) and ledger.get("prediction")):
        return None
    kinds = ledger.get("by_kind") or {}
    return {"source": "report 28's law ledger", "laws": ledger.get("laws"), "by_kind": kinds,
            "degree_only": kinds.get(KIND_DEGREES, 0), "prediction": ledger["prediction"]}


def _latest_by_law(decisions: list[dict]) -> dict:
    latest = {}
    for d in sorted(decisions, key=lambda d: (str(d.get("created_utc") or ""), str(d.get("decision_id") or ""))):
        latest[str(d.get("candidate_id"))] = d
    return latest


def _gates(tree: dict, decided) -> dict:
    gates = {}
    for gate in tree.get("gates") or []:
        withheld, through = int(gate.get("withheld") or 0), int(gate.get("let_through") or 0)
        if not (withheld or through):
            continue
        gates[str(gate.get("gate"))] = {
            "stage": gate.get("stage"), "salted": bool(gate.get("salted")),
            "withheld": withheld, "let_through": through, "judged": withheld + through,
            "share_of_decided": _share(withheld + through, decided),
            "let_through_share": _share(through, withheld + through),
            "by_rung": gate.get("by_rung") or {},
            "let_through_later": gate.get("let_through_later") or {},
            "settled_later_share": gate.get("settled_later_share"),
            "unsalted_settled_later_share": gate.get("unsalted_settled_later_share_at_the_same_rungs"),
            **{key: gate[key] for key in ("salt_next_rung", "salt_next_rung_reading", "salt_spent", "salt_ledger")
               if key in gate},
        }
    return gates


def _study_ledger(campaigns: list[dict]) -> dict:
    from graph_scale_dynamics.research import gate_tree as T
    summed: dict = defaultdict(lambda: defaultdict(Counter))
    for campaign in campaigns:
        for name, gate in (campaign.get("gates") or {}).items():
            for cost, entry in (gate.get("salt_ledger") or {}).items():
                summed[name][cost].update({key: int(entry.get(key) or 0)
                                           for key in (T.CLEAN, T.MISSED, T.OPEN, T.BOUGHT_NOTHING,
                                                       T.UNTESTED)})
    out = {}
    for name, costs in sorted(summed.items()):
        out[name] = {}
        for cost, c in costs.items():
            needed = T.CONFIRM_AFTER.get(cost, T.CONFIRM_AFTER[T.CHEAP])
            confirmed = not c[T.MISSED] and c[T.CLEAN] >= needed
            out[name][cost] = {"salted": sum(c.values()), T.CLEAN: c[T.CLEAN], T.MISSED: c[T.MISSED],
                               T.OPEN: c[T.OPEN], T.BOUGHT_NOTHING: c[T.BOUGHT_NOTHING],
                               T.UNTESTED: c[T.UNTESTED], "needed": needed,
                               "label": "confirmed" if confirmed else "testing"}
    return out


def _pace(decisions: list[dict], reported) -> dict:
    starts = Counter(str(d.get("created_utc") or "")[:13] for d in decisions if d.get("rule") == "start")
    starts.pop("", None)
    if not starts:
        return {}
    hours = sorted(starts)
    end = _utc(reported) or _utc(max(hours) + ":59:59Z")
    top = end.replace(minute=0, second=0, microsecond=0)
    last = [(top - timedelta(hours=k)).strftime("%Y-%m-%dT%H") for k in range(6, 0, -1)]
    return {"first_hour": hours[0], "first_hour_laws": starts[hours[0]],
            "last_six_hours": [last[0], last[-1]],
            "last_six_hours_laws_an_hour": round(sum(starts.get(h, 0) for h in last) / 6.0, 1),
            "by_hour": dict(sorted(starts.items()))}


def _admission(engine: dict, compute: dict, policy: dict) -> dict:
    from graph_scale_dynamics.scheduling.admission import SLOT_BASE_BLOCK, admission_slot
    top = max([n for n in (_int(s) for s in policy.get("base_sizes") or []) if n] or [4096])
    laws = [law for law in engine.get("laws") or [] if isinstance(law, dict)]
    in_block = sum(1 for law in laws if admission_slot("BASE_BLOCK_RUNNING", law.get("action"), law.get("next_n"),
                                                      top) == SLOT_BASE_BLOCK)
    supply = compute.get("work_supply_health") or {}
    queued = (((compute.get("queued_simulation_claimability") or {}).get("by_reason") or {})
              .get("claimable") or {}).get("by_n") or {}
    return {"laws_in_their_base_block": in_block if laws else None,
            "laws_with_live_work": supply.get("candidates_with_live_job_analysis_or_rebuild"),
            "queued_by_n": {str(k): v for k, v in sorted(queued.items(), key=lambda kv: _int(kv[0]) or 0)}}


def _deep_routes(engine: dict) -> dict:
    return dict(engine["lanes"], source="report 28") if isinstance(engine.get("lanes"), dict) else {}


def _d_s_by_mean_degree(phenotypes: dict) -> dict:
    rows = []
    for specimen in phenotypes.get("specimens") or []:
        phenotype = (specimen or {}).get("phenotype") or {}
        cells = dict(phenotype.get("per_n") or {})
        cells.update(phenotype.get("extension_per_n") or {})
        for cell in cells.values():
            degree = (cell or {}).get("mean_degree")
            if not isinstance(degree, (int, float)):
                continue
            value = cell.get("d_s")
            refused = str(cell.get("d_s_bucket") or "").startswith("REFUSED")
            rows.append((float(degree), float(value) if isinstance(value, (int, float)) and not refused else None))
    out = {}
    for lo, hi in MEAN_DEGREE_BANDS:
        band = [v for d, v in rows if lo <= d < hi]
        read = sorted(v for v in band if v is not None)
        if not band:
            continue
        out[f"{lo}-{hi}"] = {"law_rungs": len(band), "read_share": _share(len(read), len(band)),
                             "median": round(statistics.median(read), 3) if read else None,
                             "p95": round(read[min(len(read) - 1, int(0.95 * len(read)))], 3) if read else None}
    return out


def _three_readings(the_record: dict) -> dict:
    structure = the_record.get("structure_by_the_committed_rule") or {}
    if isinstance(structure.get("three_readings"), dict):
        return dict(structure["three_readings"], source="report 28")
    return {}


def _curvature(engine: dict) -> dict:
    rungs = (engine.get("graphs_by_rung") or {}).get("rungs") or []
    return {str(r.get("n")): {"median": r.get("median_curvature"), "graphs": r.get("curvature_read")}
            for r in rungs if isinstance(r, dict) and r.get("curvature_read")}


def _longer_chains(decisions: list[dict]) -> dict:
    rows = sorted(decisions, key=lambda d: (str(d.get("created_utc") or ""), str(d.get("decision_id") or "")))
    by_law: dict[str, list] = defaultdict(list)
    for d in rows:
        by_law[str(d.get("candidate_id"))].append(d)
    outcome = Counter()
    bought = 0
    for law_rows in by_law.values():
        for i, d in enumerate(law_rows):
            if d.get("rule") != "longer_chain":
                continue
            bought += 1
            later = next((e for e in law_rows[i + 1:] if e.get("rule") not in ("longer_chain", "complete_rung")), None)
            outcome["not decided yet" if later is None else "parked: still no reading" if later.get("rule") == "no_reading"
                    else f"read, then {later.get('action') or 'decided'}: {later.get('rule') or 'unrecorded'}"] += 1
    return {"bought": bought, "next": dict(outcome)} if bought else {}


def _base_block(tree: dict, flow: dict, policy: dict, decided) -> dict:
    sizes = [n for n in (_int(s) for s in policy.get("base_sizes") or []) if n] or [64, 256, 1024, 4096]
    top = max(sizes)
    rung = next((r for r in tree.get("rungs") or [] if _int(r.get("n")) == top), None) or {}
    finished = int(rung.get("finished") or 0)
    no_reading = next((g for g in tree.get("gates") or [] if g.get("gate") == "no_reading"), None) or {}
    at_top = (no_reading.get("by_rung") or {}).get(str(top)) or {}
    by_rung: dict[int, Counter] = defaultdict(Counter)
    top_buckets: Counter = Counter()
    complete = 0
    for law in flow.get("trajectories") or []:
        if not isinstance(law, dict):
            continue
        law_sizes = [_int(n) for n in law.get("sizes") or []]
        buckets = list(((law.get("probe_buckets") or {}).get("d_s")) or [])
        if not law_sizes or len(buckets) != len(law_sizes):
            continue
        complete += 1
        for n, bucket in zip(law_sizes, buckets, strict=True):
            by_rung[n][kind_of(bucket)] += 1
        if top in law_sizes:
            top_buckets[buckets[law_sizes.index(top)] or "read"] += 1
    kinds = Counter()
    for bucket, count in top_buckets.items():
        kinds[kind_of(None if bucket == "read" else bucket)] += count
    return {"top_rung": top, "finished": finished, "share_of_decided": _share(finished, decided),
            "no_d_s_reading": int(at_top.get("withheld") or 0) + int(at_top.get("let_through") or 0),
            "d_s_settled": int((rung.get("went_on_by") or {}).get("d_s_settled") or 0),
            "laws_with_a_complete_block": complete,
            "d_s_at_the_top_rung": {"kinds": {k: kinds[k] for k in KINDS if kinds.get(k)},
                                    "buckets": dict(top_buckets.most_common())},
            "d_s_read_share_by_rung": {str(n): _share(c.get("read", 0), sum(c.values()))
                                       for n, c in sorted(by_rung.items())}}


def _standing(entry: dict) -> tuple[str, str | None]:
    family = entry.get("control_family") or {}
    if family.get("family"):
        return "named", str(family["family"])
    if family.get("ambiguous_with"):
        return "ambiguous", None
    return "none", None


def _families(ranking: dict, decisions: list[dict]) -> tuple[dict, dict]:
    from graph_scale_dynamics.research.every_law import every_law_families
    standing = {law: _standing({"control_family": family}) for law, family in every_law_families(ranking).items()}
    matched = dict((ranking.get("control_families") or {}).get("matched") or {})
    settled = {str(d.get("candidate_id")) for d in decisions if d.get("rule") == "d_s_settled"}
    counts = Counter(standing.get(law, ("unranked", None))[0] for law in settled)
    return ({"matched": matched, "matched_total": sum(int(v or 0) for v in matched.values()),
             "laws_scored": ranking.get("laws_scored"), "laws_ranked": len(standing),
             "d_s_settled_laws": {"laws": len(settled), **{k: counts[k] for k in STANDINGS if counts.get(k)}}},
            standing)


def _deep(tree: dict, decisions: list[dict], policy: dict) -> dict:
    top = max([n for n in (_int(s) for s in policy.get("base_sizes") or []) if n] or [4096])
    bought: dict[int, set] = defaultdict(set)
    for d in decisions:
        n = _int(d.get("next_n"))
        if d.get("action") == "run_next" and n and n > top:
            bought[n].add(str(d.get("candidate_id")))
    finished = {str(r.get("n")): int(r.get("finished") or 0) for r in tree.get("rungs") or []
                if (_int(r.get("n")) or 0) > top}
    deepest = max((int(n) for n, k in finished.items() if k), default=None)
    return {"bought": {str(n): len(laws) for n, laws in sorted(bought.items())}, "finished": finished,
            "deepest_finished": deepest}


def _lanes(policy: dict, decisions: list[dict], latest: list, standing: dict) -> dict:
    widths = {}
    for entry in policy.get("deep_lane_widths") or []:
        try:
            widths[int(entry[0])] = int(entry[1])
        except (TypeError, ValueError, IndexError):
            continue
    order = sorted(decisions, key=lambda d: (str(d.get("created_utc") or ""), str(d.get("decision_id") or "")))

    def kind(law):
        return standing.get(law, ("unranked", None))[0]

    def by_standing(laws) -> dict:
        counts = Counter(kind(law) for law in laws)
        return {"laws": len(laws), **{k: counts[k] for k in STANDINGS if counts.get(k)}}

    lanes = {}
    for n, width in sorted(widths.items()):
        waiting, waited, entered = {}, set(), []
        contested = family_ahead = 0
        for d in order:
            law, next_n = str(d.get("candidate_id")), _int(d.get("next_n"))
            if next_n == n and d.get("action") == "hold" and d.get("rule") == "deep_lane_full":
                waiting.setdefault(law, d.get("created_utc"))
                waited.add(law)
                continue
            if next_n == n and d.get("action") == "run_next":
                others = [w for w in waiting if w != law]
                if others:
                    contested += 1
                    if kind(law) == "named" and any(kind(w) != "named" for w in others):
                        family_ahead += 1
                entered.append(law)
            waiting.pop(law, None)
        now_in = {str(l.get("candidate_id")) for l in latest if isinstance(l, dict)
                  and _int(l.get("next_n")) == n and l.get("action") == "run_next"}
        now_waiting = {str(l.get("candidate_id")) for l in latest if isinstance(l, dict)
                       and _int(l.get("next_n")) == n and l.get("action") == "hold" and l.get("rule") == "deep_lane_full"}
        families = sorted({standing[law][1] for law in set(entered) | now_in if kind(law) == "named"})
        lanes[str(n)] = {"width": width, "entered": by_standing(set(entered)), "waited": by_standing(waited),
                         "in_lane_now": by_standing(now_in), "waiting_now": by_standing(now_waiting),
                         "entries_while_others_waited": contested, "family_ahead_of_a_non_family": family_ahead,
                         "families_through": families}
    return lanes


def _seeds(table: dict) -> dict:
    columns = list(table.get("columns") or [])
    if "n" not in columns or "simulation_seconds" not in columns:
        return {}
    i_n, i_s = columns.index("n"), columns.index("simulation_seconds")
    by_rung: dict[int, list] = defaultdict(list)
    for row in table.get("rows") or []:
        try:
            n, seconds = int(row[i_n]), row[i_s]
        except (TypeError, ValueError, IndexError):
            continue
        if isinstance(seconds, (int, float)):
            by_rung[n].append(float(seconds))
    return {str(n): {"seeds": len(v), "median_seconds": round(statistics.median(v), 2), "max_seconds": round(max(v), 1)}
            for n, v in sorted(by_rung.items())}


def _core_hours(the_record: dict) -> dict:
    total: dict[int, float] = defaultdict(float)
    for cells in (((the_record.get("compute_by_regime") or {}).get("by_rung")) or {}).values():
        for key, cell in (cells or {}).items():
            n = _int(str(key).partition(":")[2])
            if n is not None:
                total[n] += float((cell or {}).get("core_seconds") or 0.0)
    return {str(n): round(seconds / 3600.0, 3) for n, seconds in sorted(total.items())}


def _totals(campaigns: list[dict]) -> dict:
    gates: dict[str, Counter] = defaultdict(Counter)
    for campaign in campaigns:
        for name, gate in (campaign.get("gates") or {}).items():
            gates[name].update({"withheld": gate["withheld"], "let_through": gate["let_through"]})
            gates[name]["salted"] = gates[name]["salted"] or int(gate.get("salted", False))
    salted = [g for g in gates.values() if g["salted"]]
    judged = sum(g["withheld"] + g["let_through"] for g in salted)
    through = sum(g["let_through"] for g in salted)

    def total(path):
        values = [_dig(c, path) for c in campaigns]
        values = [v for v in values if isinstance(v, (int, float))]
        return sum(values) if values else None

    return {"campaigns": len(campaigns), "laws_held": total(("laws_held",)), "laws_decided": total(("laws_decided",)),
            "through_the_base_block": total(("base_block", "finished")),
            "d_s_settled_at_the_top_of_the_base_block": total(("base_block", "d_s_settled")),
            "calibration_families_matched": total(("families", "matched_total")),
            "salted_gates": {"judged": judged, "let_through": through, "let_through_share": _share(through, judged)},
            "gates": {name: {"withheld": g["withheld"], "let_through": g["let_through"], "salted": bool(g["salted"]),
                             "let_through_share": _share(g["let_through"], g["withheld"] + g["let_through"])}
                      for name, g in sorted(gates.items())},
            "salt_ledger": _study_ledger(campaigns)}


def _dig(value, path):
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


ROWS = (
    ("laws_held", "laws held", "int"),
    ("laws_per_hour", "laws an hour, since it was created", "int"),
    ("laws_decided", "laws decided", "int"),
    ("empty", "empty", "pct"),
    ("too_dense", "too dense", "pct"),
    ("disconnected", "disconnected", "pct"),
    ("let_through", "let through, every gate that lets a share through", "pct"),
    ("base_block", "through the base block", "int"),
    ("base_block_share", "  of the laws decided", "pct"),
    ("no_d_s", "  no d_s at its top two rungs", "int"),
    ("settled", "  d_s settled at its top rung", "int"),
    ("refused_geometry", "  d_s refused at the top: geometry", "int"),
    ("refused_limits", "  ... the search limits", "int"),
    ("refused_sampling", "  ... the sampling", "int"),
    ("families", "reproduce a calibration family", "int"),
    *((f"bought_{n}", f"bought N={n:,}", "int") for n in DEEP_RUNGS),
    ("lane_1048576", "in the 1M lane / waiting now", "pair"),
    ("family_ahead", "a family ahead of a non-family", "int"),
    ("core_hours", "core hours", "num"),
    ("new_first_hour", "new laws, first hour", "int"),
    ("new_last_six", "new laws an hour, last six hours", "num"),
    ("in_base_block", "laws in their base block now", "int"),
    ("queued_65536", "simulations queued at 65,536", "int"),
    ("audit_share_deep", "audit traffic, core hours from 262,144", "pct"),
    ("finite_three", "finite by the rule / all three agree", "pair"),
    ("longer_chains", "longer chains bought (B2)", "int"),
    ("degree_only", "laws that see only degrees", "int"),
    ("predicted_quarter", "  predicted in advance, within 0.25", "pct"),
)


def metrics(campaign: dict | None) -> dict:
    if not campaign:
        return {key: None for key, _, _ in ROWS}
    gates, base = campaign.get("gates") or {}, campaign.get("base_block") or {}
    kinds = (base.get("d_s_at_the_top_rung") or {}).get("kinds") or {}
    salted = [g for g in gates.values() if g.get("salted")]
    judged = sum(g["judged"] for g in salted)
    lanes = campaign.get("lanes") or {}
    bought = (campaign.get("deep") or {}).get("bought") or {}
    hours = campaign.get("core_hours_by_rung") or {}

    def lane(n):
        entry = lanes.get(str(n))
        return None if entry is None else (entry["in_lane_now"]["laws"], entry["waiting_now"]["laws"])

    return {
        "laws_held": campaign.get("laws_held"), "laws_per_hour": campaign.get("laws_per_hour"),
        "laws_decided": campaign.get("laws_decided"),
        "empty": (gates.get("empty") or {}).get("share_of_decided", 0.0 if gates else None),
        "too_dense": (gates.get("too_dense") or {}).get("share_of_decided", 0.0 if gates else None),
        "disconnected": (gates.get("disconnected") or {}).get("share_of_decided", 0.0 if gates else None),
        "let_through": _share(sum(g["let_through"] for g in salted), judged),
        "base_block": base.get("finished"), "base_block_share": base.get("share_of_decided"),
        "no_d_s": base.get("no_d_s_reading"), "settled": base.get("d_s_settled"),
        "refused_geometry": kinds.get("geometry", 0) if base else None,
        "refused_limits": kinds.get("limits", 0) if base else None,
        "refused_sampling": kinds.get("sampling", 0) if base else None,
        "families": (campaign.get("families") or {}).get("matched_total"),
        **{f"bought_{n}": int(bought.get(str(n), 0)) for n in DEEP_RUNGS},
        "lane_1048576": lane(1048576),
        "family_ahead": sum(int(entry.get("family_ahead_of_a_non_family") or 0) for entry in lanes.values()),
        "core_hours": round(sum(hours.values()), 2) if hours else None,
        **_metrics_537(campaign),
        **_metrics_538(campaign),
    }


def _metrics_538(campaign: dict) -> dict:
    predicted = campaign.get("predicted") or {}
    every = (predicted.get("prediction") or {}).get("all") or {}
    return {"degree_only": predicted.get("degree_only"),
            "predicted_quarter": every.get("within_a_quarter") if every.get("compared") else None}


def _metrics_537(campaign: dict) -> dict:
    pace, admission = campaign.get("pace") or {}, campaign.get("admission") or {}
    routes, three = campaign.get("deep_routes") or {}, (campaign.get("three_readings") or {}).get("counts") or {}
    longer = campaign.get("longer_chains")
    return {"new_first_hour": pace.get("first_hour_laws"), "new_last_six": pace.get("last_six_hours_laws_an_hour"),
            "in_base_block": admission.get("laws_in_their_base_block"),
            "queued_65536": ((admission.get("queued_by_n") or {}).get("65536", 0) if admission else None),
            "audit_share_deep": routes.get("audit_share_of_core_hours"),
            "finite_three": ((three.get("finite by the rule", 0), three.get("all three agree", 0))
                             if "three_readings" in campaign else None),
            "longer_chains": (longer or {}).get("bought", 0) if "longer_chains" in campaign else None}


def _standings(counts: dict | None) -> str:
    counts = counts or {}
    words = {"named": "a family", "ambiguous": "ambiguous", "none": "none", "unranked": "unranked"}
    parts = [f"{counts[k]} {words[k]}" for k in STANDINGS if counts.get(k)]
    return f"{counts.get('laws', 0)}" + (f" ({', '.join(parts)})" if parts else "")


def _fmt(value, form: str) -> str:
    if value is None:
        return "-"
    if form == "pct":
        return f"{100 * value:.1f}%"
    if form == "pair":
        return f"{value[0]} / {value[1]}"
    if form == "num":
        return f"{value:,.1f}"
    return f"{int(value):,}"


def compare(before: dict, after: dict) -> dict:
    earlier = list(before.get("campaigns") or [])
    campaigns = []
    for campaign in after.get("campaigns") or []:
        prior = next((c for c in earlier if campaign.get("label") and c.get("label") == campaign.get("label")), None)
        if prior is None and not campaign.get("label"):
            prior = next((c for c in earlier if c.get("campaign_id") == campaign.get("campaign_id")), None)
        a, b = metrics(prior), metrics(campaign)
        campaigns.append({"campaign_id": campaign.get("campaign_id"), "short": campaign.get("short"),
                          "label": campaign.get("label"), "matched": prior is not None,
                          "before_campaign_id": prior.get("campaign_id") if prior else None,
                          "rows": {key: [a.get(key), b.get(key)] for key, _, _ in ROWS}})
    return {"contract": COMPARISON_CONTRACT,
            "before": {k: before.get(k) for k in ("study_id", "built_utc", "build_number")},
            "after": {k: after.get(k) for k in ("study_id", "built_utc", "build_number")},
            "hours_between": _hours(before.get("built_utc"), after.get("built_utc")),
            "campaigns": campaigns,
            "study": {"before": before.get("study") or {}, "after": after.get("study") or {}}}


def _table(header: list[str], rows: list[tuple[str, list[str]]], width: int) -> list[str]:
    lines = [f"{'':<36}" + "".join(f"{h:>{width}}" for h in header)]
    lines += [f"{label:<36}" + "".join(f"{cell:>{width}}" for cell in cells) for label, cells in rows]
    return lines


def render(reading: dict) -> str:
    campaigns = reading.get("campaigns") or []
    values = [metrics(c) for c in campaigns]
    lines = [f"study {reading.get('study_id')} as read ({reading.get('contract')}): build {reading.get('build_number')}, "
             f"bundle built {reading.get('built_utc')}"]
    lines += _table([c.get("short") or c.get("campaign_id") for c in campaigns],
                    [(label, [_fmt(v.get(key), form) for v in values]) for key, label, form in ROWS], 12)
    lines.append("")
    for campaign in campaigns:
        families = campaign.get("families") or {}
        matched = ", ".join(f"{name} {count}" for name, count in (families.get("matched") or {}).items()) or "none"
        lines.append(f"{campaign.get('short')}: calibration families {matched}; laws whose d_s settled "
                     f"{_standings(families.get('d_s_settled_laws'))}")
        for n, lane in (campaign.get("lanes") or {}).items():
            if lane["entered"]["laws"] or lane["waited"]["laws"]:
                lines.append(f"  lane N={int(n):,} (width {lane['width']}): entered {_standings(lane['entered'])}, "
                             f"waited {_standings(lane['waited'])}; {lane['entries_while_others_waited']} entries while "
                             f"others waited, {lane['family_ahead_of_a_non_family']} of them a family ahead of a "
                             f"non-family")
    lines += _render_537(campaigns)
    for campaign in campaigns:
        predicted = campaign.get("predicted") or {}
        by_regime = predicted.get("prediction") or {}
        if (by_regime.get("all") or {}).get("compared"):
            cells = "; ".join(f"{regime} {v['compared']} laws, R^2 {v.get('r2')}, within 0.25 {_fmt(v.get('within_a_quarter'), 'pct')}"
                              for regime, v in by_regime.items() if v.get("compared"))
            lines.append(f"{campaign.get('short')}: predicted before running ({predicted.get('source')}): {cells}")
    study_gates = (reading.get("study") or {}).get("gates") or {}
    salted = {name: g for name, g in study_gates.items() if g.get("salted")}
    if salted:
        lines.append("the let-through, the whole study (withheld / let through, share): " + ", ".join(
            f"{name} {g['withheld']}/{g['let_through']} ({_fmt(g['let_through_share'], 'pct')})"
            for name, g in salted.items()))
        lines.append("what the let-through found (Q): settled d_s later, let through against on their own reading from the same rungs")
        for name in salted:
            cells = []
            for campaign in campaigns:
                gate = (campaign.get("gates") or {}).get(name)
                if gate and gate.get("let_through"):
                    cells.append(f"{campaign.get('short')} {_fmt(gate.get('settled_later_share'), 'pct')} vs "
                                 f"{_fmt(gate.get('unsalted_settled_later_share'), 'pct')} "
                                 f"(of {gate['let_through']}: {gate.get('let_through_later') or {}})")
            if cells:
                lines.append(f"  {name}: " + "; ".join(cells))
    gates = reading.get("gates_ledger") or {}
    if gates.get("gates"):
        lines.append(f"every gate at every size, from this study's own decisions (784): let through, clean one size up "
                     f"(same gate), missed, open; confirmed after {gates.get('confirm_after')} clean in a row; below "
                     f"N={gates.get('from_n'):,} every verdict recorded and every law on:")
        for name, by_size in sorted(gates["gates"].items()):
            lines.append(f"  {name}: " + "; ".join(
                f"N={int(n):,} {v['let_through']} through, {v['clean']} clean ({v['same_gate']}), {v['missed']} missed, "
                f"{v['open']} open: {v['label']}" for n, v in sorted(by_size.items(), key=lambda kv: int(kv[0]))))
        lines.append(f"  known results: {gates.get('signatures_known')} of {gates.get('signatures')} signatures")
    elif gates.get("unavailable"):
        lines.append(f"the gates' ledger was not read: {gates['unavailable']}")
    ledger = (reading.get("study") or {}).get("salt_ledger") or {}
    if ledger:
        lines.append("the let-through ledger (552), every law let through to its end, and the label 554's rule gives the gate:")
        for name, costs in ledger.items():
            lines.append(f"  {name}: " + "; ".join(
                f"{cost} {v['clean']} clean, {v['missed']} missed, {v.get('ended_untested', 0)} ended untested, "
                f"{v['open']} open of {v['salted']}: {v['label']}"
                f" ({v['needed']} clean needed)" for cost, v in costs.items()))
    from graph_scale_dynamics.research.d_s_shape_reading import render as render_shape
    shapes = [line for c in campaigns for line in render_shape(c.get("d_s_shape") or {}, c.get("short") or "")]
    if shapes:
        lines.append("d_s as a flow (563): whether its error covers its seeds, per rung, and how flat it is")
        lines += shapes
    for missing in reading.get("missing") or []:
        lines.append(f"campaign {missing.get('campaign_id')} is missing from the bundle: {missing.get('why')}")
    return "\n".join(lines)


def _render_537(campaigns: list[dict]) -> list[str]:
    lines = []
    for campaign in campaigns:
        routes = campaign.get("deep_routes") or {}
        if routes.get("entries_by_route"):
            entries = "; ".join(f"N={int(n):,}: " + ", ".join(f"{k} {v}" for k, v in by.items())
                                for n, by in routes["entries_by_route"].items())
            hours = ", ".join(f"{k} {v:.1f} h" for k, v in (routes.get("core_hours_by_route") or {}).items())
            lines.append(f"{campaign.get('short')}: deep entries by route ({routes.get('source')}): {entries}; "
                         f"core hours {hours or '-'}")
        for n, lane in (routes.get("lanes") or {}).items():
            if lane.get("in_lane_now") or lane.get("waiting_now") or lane.get("gave_up"):
                lines.append(f"  lane N={int(n):,}: in it {lane.get('in_lane_now') or {}}, waiting "
                             f"{lane.get('waiting_now') or {}}, gave it up {lane.get('gave_up', 0)}, took it back "
                             f"{lane.get('resumed', 0)}")
        three = campaign.get("three_readings") or {}
        if three.get("counts"):
            agreeing = ", ".join(f"{str(t.get('candidate_id'))[:10]} (local {t.get('local_d_s')}, gap "
                                 f"{t.get('gap_implied_d_s')}, bulk {t.get('bulk_implied_dimension')}"
                                 + (f", kappa {t['kappa_mean']}" if t.get("kappa_mean") is not None else "") + ")"
                                 for t in (three.get("all_three_agree") or [])[:5])
            lines.append(f"  three readings ({three.get('source')}): {three['counts']}"
                         + (f"; all three agree: {agreeing}" if agreeing else ""))
        for name, gate in (campaign.get("gates") or {}).items():
            if gate.get("salt_next_rung"):
                reading = gate.get("salt_next_rung_reading")
                lines.append(f"  let through past {name}, at the next rung: {gate['salt_next_rung']}"
                             + (f", the gate's own reading there {reading}" if reading else "")
                             + (f"; spent {gate['salt_spent']}" if gate.get("salt_spent") else ""))
        if campaign.get("longer_chains"):
            lines.append(f"  longer chains (B2): {campaign['longer_chains']}")
        if campaign.get("curvature"):
            lines.append("  curvature (544), the median graph's mean kappa: " + ", ".join(
                f"N={int(n):,} {cell['median']:+.3f} ({cell['graphs']})"
                for n, cell in campaign["curvature"].items() if cell.get("median") is not None))
    table: dict = defaultdict(lambda: [0, 0])
    medians: dict = defaultdict(list)
    for campaign in campaigns:
        for band, cell in (campaign.get("d_s_by_mean_degree") or {}).items():
            table[band][0] += int(cell.get("law_rungs") or 0)
            table[band][1] += round(float(cell.get("read_share") or 0.0) * int(cell.get("law_rungs") or 0))
            if cell.get("median") is not None:
                medians[band].append(f"{campaign.get('short')} {cell['median']:.2f}")
    if table:
        lines.append("d_s by mean degree at the rung, every law through the base block (law-rungs, read, median):")
        for band, (count, read) in table.items():
            lines.append(f"  {band:>6}: {count:6,} law-rungs, {_fmt(_share(read, count), 'pct'):>6} read; "
                         + ("; ".join(medians[band]) or "no reading"))
    return lines


def render_comparison(comparison: dict) -> str:
    before, after = comparison.get("before") or {}, comparison.get("after") or {}
    hours = comparison.get("hours_between")
    lines = [f"study {after.get('study_id')} at {after.get('built_utc')} (build {after.get('build_number')}) against "
             f"study {before.get('study_id')} at {before.get('built_utc')} (build {before.get('build_number')})"
             + (f", {hours:.1f} hours later" if isinstance(hours, (int, float)) else "")]
    campaigns = comparison.get("campaigns") or []
    lines += _table([c.get("short") or c.get("campaign_id") for c in campaigns],
                    [(label, [f"{_fmt(c['rows'][key][0], form)} -> {_fmt(c['rows'][key][1], form)}" for c in campaigns])
                     for key, label, form in ROWS], 22)
    for campaign in campaigns:
        if not campaign.get("matched"):
            lines.append(f"{campaign.get('short')}: no quadrant with its label in the earlier reading")
    earlier, later = (comparison.get("study") or {}).get("before") or {}, (comparison.get("study") or {}).get("after") or {}
    a, b = earlier.get("salted_gates") or {}, later.get("salted_gates") or {}
    if a or b:
        lines.append(f"let through, every gate of the study that lets a share through: {a.get('let_through')} of {a.get('judged')} "
                     f"({_fmt(a.get('let_through_share'), 'pct')}) -> {b.get('let_through')} of {b.get('judged')} "
                     f"({_fmt(b.get('let_through_share'), 'pct')})")
    return "\n".join(lines)


def load_reading(path: Path) -> dict:
    path = Path(path)
    if path.is_file() and path.suffix == ".json":
        reading = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(reading, dict) or reading.get("contract") not in READABLE_CONTRACTS:
            raise ValueError(f"{path.name} is not a study reading ({', '.join(READABLE_CONTRACTS)})")
        return reading
    return read_study(path)
