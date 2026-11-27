from __future__ import annotations

from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION

CONTRACT = "gsd-law-elsewhere-1"


def _version(repo, campaign_id: str) -> str:
    return str(((repo.campaign(str(campaign_id)) or {}).get("spec") or {}).get("analysis_version") or ANALYSIS_VERSION)


def others(repo, candidate_id: str, campaign_id: str) -> list[str]:
    held = getattr(repo, "candidate_campaign_ids", None)
    return [str(c) for c in (held(str(candidate_id)) if callable(held) else []) or [] if str(c) != str(campaign_id)]


def _seeds(row: dict) -> int:
    summary = row.get("summary") or {}
    return int(summary.get("seeds") or summary.get("measurement_seeds") or 0)


def rung_rows(repo, candidate_id: str, campaign_id: str, have) -> list[dict]:
    held = {int(n) for n in have}
    best: dict[int, dict] = {}
    for other in others(repo, candidate_id, campaign_id):
        for row in repo.rung_summaries(str(candidate_id), _version(repo, other), other):
            n = int(row["n"])
            if n in held:
                continue
            if n not in best or _seeds(row) > _seeds(best[n]):
                best[n] = dict(row, read_in=other)
    return [best[n] for n in sorted(best)]


def rungs(repo, candidate_id: str, campaign_id: str, have) -> list[dict]:
    from graph_scale_dynamics.services.api.overview import _published_channels, public_row
    return [public_row(row, "summary_json") | {"channels": _published_channels(row["summary"]), "read_in": row["read_in"],
                                               "compute": {"n": row["n"], "jobs": 0, "attempts": 0, "core_seconds": 0.0,
                                                           "read_in": row["read_in"]}}
            for row in rung_rows(repo, candidate_id, campaign_id, have)]


def measurements(repo, candidate_id: str, campaign_id: str, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    held = {int(r["n"]) for r in rows}
    best: dict[int, tuple[str, list[dict]]] = {}
    for other in others(repo, candidate_id, campaign_id):
        by: dict[int, list[dict]] = {}
        for row in repo.measurements(str(candidate_id), _version(repo, other), other):
            if int(row["n"]) not in held:
                by.setdefault(int(row["n"]), []).append(row)
        for n, found in by.items():
            if n not in best or len(found) > len(best[n][1]):
                best[n] = (other, found)
    added = [row for n in sorted(best) for row in best[n][1]]
    said = [{"n": n, "campaign": best[n][0], "rows": len(best[n][1])} for n in sorted(best)]
    return list(rows) + added, said


__all__ = ["CONTRACT", "measurements", "others", "rung_rows", "rungs"]
