from __future__ import annotations

EVERY_LAW_COLUMNS = ("candidate_id", "control_family", "ambiguous_with", "top_measured_rung")


def every_law_table(rows: list[dict]) -> dict:
    def family(r: dict) -> dict:
        return r.get("control_family") or {}

    return {"columns": list(EVERY_LAW_COLUMNS),
            "rows": [[r["candidate_id"], family(r).get("family"), list(family(r).get("ambiguous_with") or []),
                      r.get("top_measured_rung")] for r in rows]}


def every_law_families(body: dict) -> dict:
    table = (body or {}).get("every_law") or {}
    at = {name: i for i, name in enumerate(table.get("columns") or [])}
    return {str(r[at["candidate_id"]]): {"family": r[at["control_family"]],
                                         "ambiguous_with": r[at["ambiguous_with"]] or []}
            for r in table.get("rows") or []}
