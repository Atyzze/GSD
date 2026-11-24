from __future__ import annotations

from graph_scale_dynamics.observability import law_score as LS
from graph_scale_dynamics.reporting.every_chain_report import VALUE_COLUMNS

CONTRACT = "gsd-finds-1"
RULE = ("every law scoring above zero on the study's own score (report 28), the controls marked: its spec as the law "
        "ledger keeps it (rebuilt to its own fingerprint), which of its terms scale with N (none: free of N), its score with the dimension read beside it, how it ended, "
        "how its starts ended and every chain's values by size")


FREE_OF_N = ("one", None)


def _scale(term):
    if isinstance(term, (list, tuple)):
        return term[3] if len(term) > 3 else None
    if isinstance(term, dict):
        coeff = term.get("coeff")
        return (coeff.get("scale") if isinstance(coeff, dict) else None) or term.get("scale")
    return None


def scales_with_n(spec) -> list[str] | None:
    terms = (spec or {}).get("terms") if isinstance(spec, dict) else None
    if not terms:
        return None
    return sorted({str(_scale(t)) for t in terms if _scale(t) not in FREE_OF_N})


def n_text(scales) -> str:
    if scales is None:
        return ""
    return "free of N" if not scales else ", ".join(scales)


def _score_of(entry: dict) -> dict:
    return dict(entry.get("score") or {}) if isinstance(entry, dict) else {}


def finds_of_report_28(body: dict, *, campaign: str, name: str | None = None) -> list[dict]:
    body = body if isinstance(body, dict) else {}
    ledger = {str(row.get("candidate_id")): row for row in ((body.get("law_ledger") or {}).get("rows") or [])
              if isinstance(row, dict)}
    decided = {str(row.get("candidate_id")): row for row in body.get("laws") or [] if isinstance(row, dict)}
    control = "controls" in str(name or "")
    out = []
    for law, entry in sorted(((body.get("every_chain") or {}).get("laws") or {}).items()):
        score = _score_of(entry)
        if not (score.get("score") or 0) > 0:
            continue
        row, own = ledger.get(str(law)) or {}, decided.get(str(law)) or {}
        reading = entry.get("starts_reading") or {}
        d = score.get("d")
        out.append({"law": str(law), "campaign": str(campaign), "campaign_name": name, "control": control,
                    "score": score, "d": d, "ring": LS.is_ring(d), "kind": row.get("kind"), "spec": row.get("spec"),
                    "scales_with_n": scales_with_n(row.get("spec")),
                    "predicted": row.get("predicted"),
                    "ended": [own.get("action"), own.get("rule"), own.get("at_n")],
                    "top_n": entry.get("top_n"), "given_family": entry.get("given_family"),
                    "starts": {"class": reading.get("class"), "fates": reading.get("fates")},
                    "values": entry.get("values") or {}})
    return out


def document(study: str, build, built_utc: str | None, finds: list[dict]) -> dict:
    ordered = sorted(finds, key=lambda f: (-int((f.get("score") or {}).get("score") or 0), f["campaign"], f["law"]))
    return {"contract": CONTRACT, "study": str(study), "build": build, "built_utc": built_utc, "rule": RULE,
            "ring_below": LS.RING_BELOW, "columns": list(VALUE_COLUMNS), "finds": ordered,
            "counted": {"finds": len(ordered), "rings": sum(1 for f in ordered if f["ring"]),
                        "controls": sum(1 for f in ordered if f["control"]),
                        "free_of_n": sum(1 for f in ordered if f.get("scales_with_n") == [])}}


__all__ = ["CONTRACT", "FREE_OF_N", "RULE", "document", "finds_of_report_28", "n_text", "scales_with_n"]
