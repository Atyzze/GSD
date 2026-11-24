from __future__ import annotations

import base64
import gzip
import json
import math
from html import escape
from pathlib import Path

CONTRACT = "gsd-study-explorer-1"
RESOURCES = Path(__file__).resolve().parents[1] / "resources" / "explorer"
TREE = Path(__file__).resolve().parents[2]

ROW_FIELDS = (
    ("n", "N", 0, "the rung: the graph's nodes"),
    ("d_s", "d_s (spectral)", 3, "the spectral dimension, from a random walk's return probability"),
    ("d_V", "d_V (volume)", 3, "the volume dimension, from how a ball's volume grows with its radius"),
    ("d_B", "d_B (box counting)", 3, "the box-counting dimension"),
    ("d_w", "d_w (walk)", 3, "the walk dimension, from a walk's mean square distance: 2 is ordinary diffusion"),
    ("k", "k (mean degree)", 3, "the mean degree at this rung"),
    ("d_s_se", "d_s error", 3, "the d_s reading's standard error"),
    ("d_V_se", "d_V error", 3, "the d_V reading's standard error"),
    ("d_B_se", "d_B error", 3, "the d_B reading's standard error"),
    ("d_w_se", "d_w error", 3, "the d_w reading's standard error"),
    ("kappa", "curvature", 4, "the mean Ollivier curvature (report 28's law ledger)"),
    ("clustering", "clustering", 4, "the clustering coefficient"),
    ("reach", "reach (half-volume radius)", 2, "the radius a ball needs to hold half the graph"),
    ("connected", "connected share", 3, "the share of the nodes in the largest component"),
    ("two_core", "2-core share", 3, "the share of the nodes in the 2-core (not on a dangling tree)"),
    ("squares", "squares per node", 3, "four-cycles per node (the structure census, base rungs)"),
    ("triangles", "triangles per node", 3, "triangles per node (the structure census, base rungs)"),
    ("gap", "spectral gap", -4, "the Laplacian's spectral gap (the structure census, base rungs)"),
    ("assortativity", "assortativity", 3, "degree assortativity (the structure census, base rungs)"),
    ("diameter", "diameter", 1, "the largest component's diameter (the structure census, base rungs)"),
    ("max_degree", "max degree", 0, "the largest degree"),
    ("given_d_s", "d_s from its shape", 3, "a growth study's chain from its shape: its d_s"),
    ("given_kappa", "curvature from its shape", 4, "a growth study's chain from its shape: its mean curvature"),
    ("given_reach", "reach from its shape", 2, "a growth study's chain from its shape: its half-volume radius"),
    ("family_distance", "nearest family's distance", 2, "how far the reading sits from the nearest calibration family "
     "at this N, in that family's measured seed spreads (the Classify ranking): 1 or less resembles it"),
)
LAW_FIELDS = (
    ("campaign", "campaign", "the campaign it was drawn in"),
    ("id", "law", "its id, the first 16 hex digits of its fingerprint"),
    ("phenotype", "phenotype", "in report 05 (its base block complete, read by every probe), or in report 28's law "
     "ledger only (its mean degree and curvature by rung, and a growth study's chains)"),
    ("cls", "class", "report 05's dimensional class"),
    ("conn", "connectivity", "report 05's connectivity class"),
    ("fate", "fate", "report 28's fate for the law"),
    ("fate_n", "fate at N", "the rung its fate was given at"),
    ("kind", "kind", "report 28's kind of law (what its terms can see)"),
    ("beta", "beta", "its inverse temperature (a zero-temperature law's sets its scale only)"),
    ("zero", "zero temperature", "the law's own temperature, zero or finite: a designed study draws it a law (its "
     "campaigns' zero_temperature is \"drawn\"), so a campaign alone does not say it"),
    ("locality", "locality", "the share of its moves that are local"),
    ("swap", "swap share", "the share of its moves that swap an edge's end"),
    ("sweeps", "sweeps", "its sweeps a rung"),
    ("move", "local move", "its local move"),
    ("terms", "terms", "its energy: [operator, k, coupling, scale, power] a term"),
    ("label", "label", "a growth study's label for the law"),
    ("role", "role", "a growth study's role for the law (square-rich, anchor, neighbour, a control)"),
    ("start", "given start", "a growth study's given start: the shape its second chain begins from"),
    ("top_n", "top rung", "the largest rung read by the committed rule"),
    ("from_empty_top", "from empty at the top", "the committed rule on the chain from empty at the top rung"),
    ("given_top", "from its shape at the top", "the committed rule on the chain from its shape at the top rung"),
    ("from_empty_implied", "implied d_s from empty", "the d_s the gap of the chain from empty implies at the top rung"),
    ("given_implied", "implied d_s from its shape", "the d_s the gap of the chain from its shape implies at the top rung"),
    ("nearest", "nearest family", "the calibration family nearest the law at its top rung read by two probes or more "
     "(the Classify ranking, 577): a resemblance, not an identification"),
    ("nearest_distance", "distance to it", "how far, in that family's measured seed spreads: 1 or less resembles it"),
)
GROWTH_CONTROLS = "campaign-growth-controls"
AT_CEILING, CEILING_MIN_LAWS = 0.9, 100
WHOLE = 0.02


def ceiling(paths: list) -> dict:
    by_n: dict = {}
    for path in paths:
        for n, d_s, *_rest in path:
            if d_s is not None:
                by_n.setdefault(int(n), []).append(float(d_s))
    out = {}
    for n, values in sorted(by_n.items()):
        values.sort()
        out[str(n)] = {"laws": len(values), "max": round(values[-1], 3),
                       "p99": round(values[min(len(values) - 1, int(0.99 * len(values)))], 3)}
    return out


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value, digits: int):
    number = _num(value)
    if number is None:
        return None
    if digits < 0:
        return float(f"{number:.{-digits}g}")
    return int(round(number)) if digits == 0 else round(number, digits)


def _at(vector, i: int):
    return vector[i] if isinstance(vector, list) and i < len(vector) else None


def _mean(cell):
    return _num(cell.get("mean")) if isinstance(cell, dict) else _num(cell)


def _report(root: Path, code: str) -> Path | None:
    from graph_scale_dynamics.reporting.study_front import report_in
    return report_in(Path(root), code)


def _ledger(root: Path) -> tuple[float | None, dict]:
    import ijson
    engine = _report(root, "28")
    if engine is None:
        return None, {}
    with open(engine, "rb") as handle:
        cap = next(ijson.items(handle, "body.law_ledger.mean_degree_cap", use_float=True), None)
    out = {}
    with open(engine, "rb") as handle:
        for row in ijson.items(handle, "body.law_ledger.rows.item", use_float=True):
            if isinstance(row, dict) and row.get("candidate_id"):
                out[str(row["candidate_id"])] = {"fate": row.get("fate"), "kind": row.get("kind"),
                                                 "spec": row.get("spec") or {}, "kappa": row.get("kappa") or {},
                                                 "mean_degree": row.get("mean_degree") or {}}
    return _num(cap), out


def _placement(law_rows: list[dict], anchors: dict | None) -> dict | None:
    from graph_scale_dynamics.research.classification_report import place
    rungs = [(row["n"], {p: row.get(p) for p in ("d_s", "d_V", "d_B", "d_w")}, _num(row.get("k"))) for row in law_rows]
    return place(rungs, anchors=anchors)


def read_part(root: Path, record: dict, tree: Path = TREE, *, calibration: dict | None = None,
              place: bool = True) -> dict:
    import ijson
    from graph_scale_dynamics.research.measured_anchors import anchors_for_table
    anchors = anchors_for_table(calibration) if calibration else None
    cap, ledger = _ledger(root)
    laws, rows, seen = [], [], set()

    def add(cid: str, specimen: dict | None) -> None:
        entry = ledger.get(cid) or {}
        law_rows = _rows((specimen or {}).get("phenotype") or {}, entry, {}, {})
        if not law_rows:
            return
        placement = _placement(law_rows, anchors) if place and specimen else None
        for row in law_rows:
            row["family_distance"] = ((placement or {}).get("by_n") or {}).get(row["n"], (None, None))[1]
        laws.append(_law(cid, specimen, entry, {}, {}, placement))
        rows.extend((len(laws) - 1, tuple(_round(row.get(key), digits) for key, _label, digits, _what in ROW_FIELDS),
                     row.get("_path")) for row in law_rows)

    report = _report(root, "05")
    if report is not None:
        with open(report, "rb") as handle:
            for specimen in ijson.items(handle, "body.specimens.item", use_float=True):
                cid = str((specimen or {}).get("candidate_id") or "")
                if cid and cid not in seen:
                    seen.add(cid)
                    add(cid, specimen)
    for cid in ledger:
        if cid not in seen:
            seen.add(cid)
            add(cid, None)
    return {"laws": laws, "rows": rows, "cap": cap, "basis": "measured" if anchors else "theory"}


def _rows(ph: dict, ledger: dict, given: dict, from_empty: dict) -> list[dict]:
    per_n = ph.get("per_n") or {}
    kappa, degree = ledger.get("kappa") or {}, ledger.get("mean_degree") or {}
    out: dict[int, dict] = {}
    blocks = ((ph.get("base_sizes") or [], ph.get("probe_vectors") or {}, ph.get("probe_se_vectors") or {}, per_n,
               {"clustering": ph.get("clustering_vector"), "reach": ph.get("half_volume_radius_vector"),
                "connected": ph.get("connected_fraction_vector"), "two_core": ph.get("two_core_fraction_vector")},
               None),
              (ph.get("extension_sizes") or [], ph.get("extension_probe_vectors") or {},
               ph.get("extension_probe_se_vectors") or {}, ph.get("extension_per_n") or {},
               {"clustering": ph.get("extension_clustering_vector"),
                "reach": ph.get("extension_half_volume_radius_vector"),
                "connected": ph.get("extension_connected_fraction_vector")},
               ph.get("extension_mean_degree_vector")))
    for sizes, probes, errors, records, vectors, degrees in blocks:
        for i, n in enumerate(sizes):
            n = int(n)
            record = records.get(str(n)) or {}
            census = record.get("census") or {}
            row = {"n": n}
            for probe in ("d_s", "d_V", "d_B", "d_w"):
                row[probe] = _at(probes.get(probe), i)
                row[f"{probe}_se"] = _at(errors.get(probe), i)
            row["k"] = _at(degrees, i) if degrees is not None else record.get("mean_degree")
            for key, vector in vectors.items():
                row[key] = _at(vector, i)
            row["max_degree"] = record.get("max_degree")
            squares, triangles = _mean(census.get("squares")), _mean(census.get("triangles"))
            row["squares"] = None if squares is None else squares / n
            row["triangles"] = None if triangles is None else triangles / n
            row["gap"] = _mean(census.get("spectral_gap"))
            row["assortativity"] = _mean(census.get("assortativity"))
            row["diameter"] = _mean(census.get("largest_component_diameter"))
            row["_path"] = (n, *(_num(row[key]) for key in ("d_s", "d_V", "d_B", "d_w", "k")))
            out[n] = row
    for n in {int(k) for k in (*degree, *kappa, *from_empty, *given)}:
        row = out.setdefault(n, {"n": n})
        p = from_empty.get(str(n)) or {}
        if _num(row.get("k")) is None:
            row["k"] = _num(degree.get(str(n)))
        if _num(row.get("d_s")) is None:
            row["d_s"] = _mean(p.get("d_s"))
        if _num(row.get("reach")) is None:
            row["reach"] = _mean(p.get("half_volume_radius"))
    for n, row in out.items():
        row["kappa"] = _num(kappa.get(str(n)))
        if row["kappa"] is None:
            row["kappa"] = _mean((from_empty.get(str(n)) or {}).get("kappa"))
        t = given.get(str(n)) or {}
        row["given_d_s"], row["given_kappa"] = _mean(t.get("d_s")), _mean(t.get("kappa"))
        row["given_reach"] = _mean(t.get("half_volume_radius"))
    return [row for n, row in sorted(out.items())
            if any(_num(row.get(key)) is not None for key in ("d_s", "d_V", "d_B", "d_w", "k", "given_d_s"))]


def _law(cid: str, specimen: dict | None, ledger: dict, plan: dict, chain: dict, placement: dict | None = None) -> dict:
    from graph_scale_dynamics.research.measured_anchors import short
    spec, specimen, placement = ledger.get("spec") or {}, specimen or {}, placement or {}
    fate = ledger.get("fate")
    fate = fate if isinstance(fate, list) else [fate, None]
    return {"candidate_id": cid, "id": cid[:16], "phenotype": "in report 05" if specimen else "report 28 only",
            "cls": specimen.get("dimensional_class"), "conn": specimen.get("connectivity_class"),
            "fate": fate[0] if fate else None, "fate_n": fate[1] if len(fate) > 1 else None,
            "kind": ledger.get("kind"), "beta": _round(spec.get("beta"), 4), "locality": _round(spec.get("locality"), 3),
            "zero": spec.get("zero_temperature") if isinstance(spec.get("zero_temperature"), bool) else None,
            "swap": _round(spec.get("swap_share"), 3), "sweeps": _round(spec.get("sweeps"), 0),
            "move": spec.get("local_move"),
            "terms": [[t[0], t[1], _round(t[2], 4), t[3], t[4]] for t in spec.get("terms") or []
                      if isinstance(t, list) and len(t) >= 5] or None,
            "label": plan.get("label"), "role": plan.get("role"),
            "start": (plan.get("given_start") or {}).get("family"),
            "top_n": chain.get("top_n"), "from_empty_top": chain.get("empty"), "given_top": chain.get("given"),
            "from_empty_implied": _round(chain.get("from_empty_implied_d_s"), 3),
            "given_implied": _round(chain.get("given_implied_d_s"), 3),
            "nearest": short(placement["nearest"]) if placement.get("nearest") else None,
            "nearest_distance": _round(placement.get("distance"), 2),
            "classify_n": placement.get("n")}


def families(table: dict | None) -> dict:
    if not table:
        return {}
    from graph_scale_dynamics.research.measured_anchors import family_degrees, measured_anchors, short
    anchors, degrees = measured_anchors(table), family_degrees(table)
    out = {}
    for family, rungs in sorted(anchors.items()):
        points = []
        for n in sorted(rungs, key=int):
            cell = rungs[n] or {}
            point = {"n": int(n), "k": _round((degrees.get(family) or {}).get(int(n)), 3)}
            for probe in ("d_s", "d_V", "d_B", "d_w"):
                reading = cell.get(probe) or {}
                point[probe] = _round(reading.get("mean"), 3)
                point[f"{probe}_sd"] = _round(reading.get("spread"), 3)
            points.append(point)
        if points:
            out[family] = {"short": short(family), "points": points}
    return out


def papers(tree: Path = TREE) -> list[dict]:
    out = []
    for path in sorted((Path(tree) / "graph_scale_dynamics" / "resources" / "readings").glob("replication_*.json")):
        if "_criterion" in path.name:
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        degrees = {}
        for row in document.get("rows") or []:
            if isinstance(row, dict) and row.get("model") is not None:
                degrees[(row["model"], row.get("n"))] = row.get("degree")
        for cell in document.get("cells") or []:
            if not isinstance(cell, dict):
                continue
            out.append({"paper": str(document.get("paper") or path.stem.split("_")[1]).upper(), "file": path.name, "model": cell.get("model"), "dimension": cell.get("dimension"),
                        "n": cell.get("vertices") or cell.get("n"), "d_s": _round(cell.get("d_s"), 3), "kappa": _round(cell.get("curvature"), 4),
                        **{probe: _round(cell.get(probe), 3) for probe in ("d_V", "d_B", "d_w")},
                        "reach": _round(cell.get("half_volume_radius"), 2),
                        "giant": _round(cell.get("giant_share"), 3),
                        "k": _round(cell.get("mean_degree") or degrees.get((cell.get("model"), cell.get("n"))), 3)})
    return out


def paths(part: dict) -> list[list[tuple]]:
    by_law: dict[int, list[tuple]] = {}
    for index, _values, path in part.get("rows") or []:
        if path is not None and any(v is not None for v in path[1:5]):
            by_law.setdefault(index, []).append(path)
    return [sorted(rows) for _, rows in sorted(by_law.items())]


def label_of(record: dict) -> str:
    quadrant = (record.get("quadrant") or {}).get("label")
    if record.get("label"):
        return str(record["label"])
    if quadrant and "not set" not in quadrant:
        return str(quadrant).replace("_", " ")
    return str(record.get("name") or f"campaign {record.get('campaign_id')}")


def document(parts: list[dict], *, title: str, study: dict, calibration: dict | None = None,
             tree: Path = TREE) -> dict:
    campaigns, laws, rows = [], {key: [] for key, *_ in LAW_FIELDS}, {"law": []}
    rows.update({key: [] for key, *_ in ROW_FIELDS})
    for c, entry in enumerate(parts):
        record, part = entry["campaign"], entry["part"]
        quadrant = record.get("quadrant") or {}
        campaigns.append({"id": str(record.get("campaign_id")), "label": label_of(record), "name": record.get("name"),
                          "zero_temperature": quadrant.get("zero_temperature"),
                          "cap": _num(quadrant.get("dense_cap")) or part.get("cap"),
                          "laws": len(part.get("laws") or [])})
        offset = len(laws["id"])
        for law in part.get("laws") or []:
            laws["campaign"].append(c)
            for key, *_ in LAW_FIELDS[1:]:
                laws[key].append(law.get(key))
        for index, values, _path in part.get("rows") or []:
            rows["law"].append(offset + index)
            for (key, *_rest), value in zip(ROW_FIELDS, values, strict=True):
                rows[key].append(value)
    present = [key for key, *_ in ROW_FIELDS if key == "n" or any(v is not None for v in rows[key])]
    law_present = [key for key, *_ in LAW_FIELDS if any(v is not None for v in laws[key])]
    every = [path for entry in parts for path in paths(entry["part"])]
    bases = {entry["part"].get("basis") for entry in parts} - {None}
    return {"contract": CONTRACT, "title": title, "study": study, "campaigns": campaigns,
            "classify_basis": "measured" if "measured" in bases else ("theory" if bases else None),
            "row_fields": [{"key": k, "label": label, "what": what} for k, label, _d, what in ROW_FIELDS
                           if k in present],
            "law_fields": [{"key": k, "label": label, "what": what} for k, label, what in LAW_FIELDS
                           if k in law_present],
            "rows": {"law": rows["law"], **{k: rows[k] for k in present}},
            "laws": {k: laws[k] for k in law_present},
            "families": families(calibration), "papers": papers(tree), "ceiling": ceiling(every),
            "rules": {"whole": WHOLE, "at_ceiling": AT_CEILING,
                      "ceiling_min_laws": CEILING_MIN_LAWS}}


def encode(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode("ascii")


def render(data: dict) -> str:
    css = (RESOURCES / "explorer.css").read_text(encoding="utf-8")
    script = (RESOURCES / "explorer.js").read_text(encoding="utf-8")
    title = escape(str(data.get("title") or "Study explorer"))
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{title}</title>\n'
            f'<style>\n{css}\n</style>\n</head>\n<body>\n'
            f'<div id="app" data-contract="{CONTRACT}"><p class="loading">Opening {title}...</p></div>\n'
            f'<script type="application/octet-stream" id="explorer-data" data-encoding="gzip+base64">'
            f'{encode(data)}</script>\n<script>\n{script}\n</script>\n</body>\n</html>\n')


def unavailable(title: str, why: str) -> str:
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<title>{escape(title)}</title>\n'
            f'</head>\n<body>\n<h1>{escape(title)}</h1>\n<p>The explorer could not be made: {escape(why)}</p>\n'
            f'</body>\n</html>\n')
