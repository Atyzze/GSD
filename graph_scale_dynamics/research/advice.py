from __future__ import annotations

import json
import math
from urllib.parse import quote

CONTRACT = "gsd-study-advice-1"
REASONS = {
    "anchor": (1, "an anchor of the folder", "the operator entered it"),
}
LAWS_AT_MOST = 100
LEADS_AT_MOST = 20
LEAD_AT_LEAST = 0.5
LEAD_MIN_READINGS = 50
NOT_SCANNED = {"n", "d_s_se", "d_V_se", "d_B_se", "d_w_se"}
RELATED = {"family_distance": {"d_s", "d_V", "d_B", "d_w"}, "kappa": {"triangles", "squares", "clustering"}}
TIED = ({"reach", "diameter", "gap"}, {"clustering", "triangles"})
REGIMES = {True: "zero temperature", False: "finite temperature", None: "not set"}


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def regime(record: dict, law: dict | None = None) -> str:
    own = (law or {}).get("zero")
    if isinstance(own, bool):
        return REGIMES[own]
    return REGIMES.get((record.get("quadrant") or {}).get("zero_temperature"), "not set")


def explorer_view(view: dict) -> str:
    return "#" + quote(json.dumps(view, separators=(",", ":")), safe="")


def _fmt(value, digits: int = 2) -> str:
    number = _num(value)
    return "-" if number is None else f"{number:.{digits}f}"


class _Ledger:
    def __init__(self) -> None:
        self.laws: dict[tuple[str, str], dict] = {}

    def add(self, campaign: str, candidate: str, key: str, text: str, **facts) -> None:
        entry = self.laws.setdefault((str(campaign), str(candidate)), {"reasons": {}})
        if key not in entry["reasons"]:
            entry["reasons"][key] = {"key": key, "text": text, **facts}


def _part_reasons(ledger: _Ledger, parts: list[dict]) -> dict:
    from graph_scale_dynamics.reporting.study_explorer import ROW_FIELDS
    keys = [key for key, *_ in ROW_FIELDS]
    at_n = keys.index("n")
    tops: dict[tuple[str, str], int] = {}
    for entry in parts:
        record, part = entry["campaign"], entry["part"]
        cid = str(record.get("campaign_id"))
        laws = part.get("laws") or []
        for index, values, _path in part.get("rows") or []:
            key = (cid, str(laws[index].get("candidate_id") or laws[index].get("id")))
            tops[key] = max(tops.get(key, 0), int(values[at_n] or 0))
    return tops


def _anchor_reasons(ledger: _Ledger, anchors: dict | None) -> None:
    for anchor in (anchors or {}).get("anchors") or []:
        reason = anchor.get("reason") or {}
        if reason.get("rule") == "operator":
            text = f"entered by the operator: {reason.get('note') or anchor.get('note') or 'no note'}"
        else:
            text = f"{reason.get('label') or reason.get('rule') or 'entered'}"
        ledger.add(str(anchor.get("campaign_id")), str(anchor.get("candidate_id")), "anchor", text)


def _ranks(values):
    from scipy.stats import rankdata
    return rankdata(values, method="average")


def _partial(x, y, k) -> float | None:
    import numpy as np
    rx, ry, rk = _ranks(x), _ranks(y), _ranks(k)

    def corr(a, b):
        a, b = a - a.mean(), b - b.mean()
        d = math.sqrt(float((a * a).sum() * (b * b).sum()))
        return float((a * b).sum()) / d if d > 0 else None
    xy, xk, yk = corr(rx, ry), corr(rx, rk), corr(ry, rk)
    if xy is None or xk is None or yk is None:
        return None
    d = math.sqrt(max(0.0, (1 - xk * xk) * (1 - yk * yk)))
    return None if d < 1e-6 else float(np.clip((xy - xk * yk) / d, -1.0, 1.0))


def leads(parts: list[dict]) -> dict:
    import numpy as np

    from graph_scale_dynamics.reporting.study_explorer import ROW_FIELDS
    keys = [key for key, *_ in ROW_FIELDS]
    columns: dict[tuple[str, int], dict[str, list]] = {}
    for entry in parts:
        laws = entry["part"].get("laws") or []
        for index, values, _path in entry["part"].get("rows") or []:
            group = regime(entry["campaign"], laws[index] if 0 <= index < len(laws) else None)
            n = values[keys.index("n")]
            cell = columns.setdefault((group, int(n)), {key: [] for key in keys})
            for key, value in zip(keys, values, strict=True):
                cell[key].append(np.nan if value is None else float(value))
    fields = [key for key in keys if key not in NOT_SCANNED and key != "k"]
    found: dict[tuple, dict] = {}
    tried = 0
    for (group, n), cell in sorted(columns.items()):
        k = np.asarray(cell["k"])
        for i, x in enumerate(fields):
            for y in fields[i + 1:]:
                if y in RELATED.get(x, ()) or x in RELATED.get(y, ()) or any({x, y} <= tie for tie in TIED):
                    continue
                a, b = np.asarray(cell[x]), np.asarray(cell[y])
                ok = np.isfinite(a) & np.isfinite(b) & np.isfinite(k)
                if int(ok.sum()) < LEAD_MIN_READINGS:
                    continue
                if np.ptp(a[ok]) == 0 or np.ptp(b[ok]) == 0:
                    continue
                tried += 1
                partial = _partial(a[ok], b[ok], k[ok])
                if partial is not None:
                    found[(group, x, y, n)] = {"partial": round(partial, 3), "readings": int(ok.sum())}
    out = []
    for (group, x, y, n), here in found.items():
        later = sorted(m for (g, a, b, m) in found if (g, a, b) == (group, x, y) and m > n)
        if not later:
            continue
        there = found[(group, x, y, later[0])]
        if min(abs(here["partial"]), abs(there["partial"])) >= LEAD_AT_LEAST and here["partial"] * there["partial"] > 0:
            panels = [{"x": x, "y": y, "color": "campaign", "camp": -1, "rung": m, "range": "data", "trend": "median"}
                      for m in (n, later[0])]
            out.append({"x": x, "y": y, "group": group, "n": n, "next_n": later[0], "partial": here["partial"],
                        "next_partial": there["partial"], "readings": here["readings"],
                        "next_readings": there["readings"],
                        "explorer": explorer_view({"p": "maps", "m": {"rows": 1, "cols": 2, "panels": panels},
                                                   "f": {"cats": {"regime": [group]}}})})
    out.sort(key=lambda r: (-min(abs(r["partial"]), abs(r["next_partial"])), r["group"], r["x"], r["y"], r["n"]))
    return {"pairs_tried": tried, "found": len(out), "leads": out[:LEADS_AT_MOST]}


def advise(parts: list[dict], *, anchors: dict | None = None) -> dict:
    from graph_scale_dynamics.reporting.study_explorer import label_of
    ledger = _Ledger()
    tops = _part_reasons(ledger, parts)
    _anchor_reasons(ledger, anchors)
    records = {str(e["campaign"].get("campaign_id")): e for e in parts}
    known = {}
    for cid, entry in records.items():
        for law in entry["part"].get("laws") or []:
            known[(cid, str(law.get("candidate_id") or law.get("id")))] = law
    rows = []
    for (cid, candidate), entry in ledger.laws.items():
        reasons = sorted(entry["reasons"].values(), key=lambda r: (-REASONS[r["key"]][0], r["key"]))
        law = known.get((cid, candidate)) or {}
        record = (records.get(cid) or {}).get("campaign") or {}
        rows.append({"campaign_id": cid, "campaign": label_of(record) if record else f"campaign {cid}",
                     "candidate_id": candidate, "id": candidate[:16], "label": law.get("label"),
                     "role": law.get("role"), "score": sum(REASONS[r["key"]][0] for r in reasons),
                     "top_n": tops.get((cid, candidate)), "nearest": law.get("nearest"),
                     "reasons": [{"key": r["key"], "text": r["text"]} for r in reasons],
                     "in_the_explorer": (cid, candidate) in known,
                     "explorer": explorer_view({"p": "laws", "sel": [candidate[:16]]})})
    rows.sort(key=lambda r: ([-REASONS[x["key"]][0] for x in r["reasons"]] + [0], -(r["top_n"] or 0),
                             r["campaign_id"], r["candidate_id"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    counts = {key: sum(1 for r in rows if any(x["key"] == key for x in r["reasons"])) for key in REASONS}
    by_campaign = {}
    for row in rows:
        by_campaign[row["campaign_id"]] = by_campaign.get(row["campaign_id"], 0) + 1
    scan = leads(parts)
    return {"contract": CONTRACT,
            "reasons": {key: {"weight": w, "label": label, "what": what} for key, (w, label, what) in REASONS.items()},
            "laws_with_a_reason": len(rows), "by_reason": counts, "by_campaign": by_campaign,
            "laws_at_most": LAWS_AT_MOST, "laws": rows[:LAWS_AT_MOST],
            "lead_rule": {"partial_at_least": LEAD_AT_LEAST, "readings_at_least": LEAD_MIN_READINGS,
                          "holds_at": "the next rung the pair was read at, with the same sign"},
            "pairs_tried": scan["pairs_tried"], "leads_found": scan["found"], "leads": scan["leads"],
            "reading": ("What deserves a closer look, from this bundle's own reports: each law with its reasons, "
                        "ranked by its strongest reason, then its next, then by the largest rung it read; and the "
                        "leads, pairs of fields whose relation holds beyond the mean degree at one rung and the next. "
                        "A reading, not a verdict: nothing decides on it.")}


def summary(document: dict) -> dict:
    return {"file": "advice.json", "laws_with_a_reason": document.get("laws_with_a_reason"),
            "by_reason": document.get("by_reason"), "leads": len(document.get("leads") or []),
            **({"unavailable": document["unavailable"]} if document.get("unavailable") else {})}
