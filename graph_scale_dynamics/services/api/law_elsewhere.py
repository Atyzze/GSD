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
    held = {int(n): int(v) for n, v in have.items()} if isinstance(have, dict) else {int(n): None for n in have}
    best: dict[int, dict] = {}
    for other in others(repo, candidate_id, campaign_id):
        for row in repo.rung_summaries(str(candidate_id), _version(repo, other), other):
            n = int(row["n"])
            if n in held and (held[n] is None or _seeds(row) <= held[n]):
                continue
            if n not in best or _seeds(row) > _seeds(best[n]):
                best[n] = dict(row, read_in=other)
    return [best[n] for n in sorted(best)]


def _public(row: dict) -> dict:
    from graph_scale_dynamics.services.api.overview import _published_channels, public_row
    return public_row(row, "summary_json") | {"channels": _published_channels(row["summary"]), "read_in": row["read_in"],
                                              "compute": {"n": row["n"], "jobs": 0, "attempts": 0, "core_seconds": 0.0,
                                                          "read_in": row["read_in"]}}


def rungs(repo, candidate_id: str, campaign_id: str, have) -> list[dict]:
    return [_public(row) for row in rung_rows(repo, candidate_id, campaign_id, have)]


def richer(repo, candidate_id: str, campaign_id: str, payload: list[dict]) -> list[dict]:
    own = {int(r["n"]): r for r in payload}
    seeds = {n: _seeds(r) for n, r in own.items()}
    taken = {int(r["n"]): _public(r) for r in rung_rows(repo, candidate_id, campaign_id, seeds)}
    return [taken.get(n) or own[n] for n in sorted(set(own) | set(taken))]


def measurements(repo, candidate_id: str, campaign_id: str, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    here: dict[int, list[dict]] = {}
    for row in rows:
        here.setdefault(int(row["n"]), []).append(row)
    best: dict[int, tuple[str, list[dict]]] = {}
    for other in others(repo, candidate_id, campaign_id):
        by: dict[int, list[dict]] = {}
        for row in repo.measurements(str(candidate_id), _version(repo, other), other):
            by.setdefault(int(row["n"]), []).append(row)
        for n, found in by.items():
            if len(found) > len(here.get(n, [])) and (n not in best or len(found) > len(best[n][1])):
                best[n] = (other, found)
    if not best:
        return list(rows), []
    kept = [row for row in rows if int(row["n"]) not in best]
    added = [row for n in sorted(best) for row in best[n][1]]
    said = [{"n": n, "campaign": best[n][0], "rows": len(best[n][1]), "here": len(here.get(n, []))}
            for n in sorted(best)]
    return kept + added, said


def pushed_as(repo, spec: dict | None, law: str) -> dict | None:
    from graph_scale_dynamics.operations import focus, push, push_ladder
    if not push_ladder.is_push(spec or {}):
        return None
    return push.home_of(focus.load(repo), str(law))


__all__ = ["CONTRACT", "measurements", "others", "pushed_as", "richer", "rung_rows", "rungs"]
