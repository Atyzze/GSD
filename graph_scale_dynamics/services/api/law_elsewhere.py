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


def being_read(repo, law: str) -> list[dict]:
    from datetime import datetime, timedelta
    runs: dict[tuple[str, int], dict] = {}
    for row in repo.conn.execute(
            "SELECT campaign_id, n, status, COUNT(*) AS c FROM jobs WHERE candidate_id=? AND kind='simulate' "
            "GROUP BY campaign_id, n, status", (str(law),)).fetchall():
        held = runs.setdefault((str(row["campaign_id"]), int(row["n"])), {"runs": 0, "done": 0, "running": 0})
        key = {"done": "done", "leased": "running"}.get(str(row["status"]))
        held["runs"] += int(row["c"])
        if key:
            held[key] += int(row["c"])
    probes: dict[tuple[str, int], dict] = {}
    for row in repo.conn.execute(
            "SELECT campaign_id, n, status, COUNT(*) AS c, MIN(updated_utc) AS since FROM analysis_queue "
            "WHERE candidate_id=? AND status IN ('queued','leased') GROUP BY campaign_id, n, status",
            (str(law),)).fetchall():
        held = probes.setdefault((str(row["campaign_id"]), int(row["n"])), {"probing": 0, "waiting": 0, "since": None})
        held["probing" if row["status"] == "leased" else "waiting"] += int(row["c"])
        if row["status"] == "leased":
            held["since"] = row["since"]
    read = {(str(r["campaign_id"]), int(r["n"])): int(r["c"]) for r in repo.conn.execute(
        "SELECT campaign_id, n, COUNT(*) AS c FROM measurements WHERE candidate_id=? GROUP BY campaign_id, n",
        (str(law),)).fetchall()}
    out = []
    for (campaign, n), held in sorted(runs.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        probe = probes.get((campaign, n)) or {}
        if not (probe.get("probing") or probe.get("waiting")):
            continue
        took = repo.conn.execute("SELECT AVG(wall_seconds) AS s FROM analysis_queue WHERE n=? AND status='done' "
                                 "AND wall_seconds IS NOT NULL", (int(n),)).fetchone()
        seconds = None if took is None or took["s"] is None else round(float(took["s"]), 1)
        due = None
        if seconds is not None and probe.get("since"):
            try:
                begun = datetime.strptime(str(probe["since"])[:19], "%Y-%m-%dT%H:%M:%S")
                due = (begun + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                due = None
        out.append({"n": n, "campaign": campaign, "runs": held["runs"], "done": held.get("done", 0),
                    "running": held.get("running", 0), "read": read.get((campaign, n), 0),
                    "probing": int(probe.get("probing") or 0), "waiting": int(probe.get("waiting") or 0),
                    "probe_seconds": seconds, "first_due_utc": due})
    return out


def pushed_as(repo, spec: dict | None, law: str) -> dict | None:
    from graph_scale_dynamics.operations import focus, push, push_ladder
    if not push_ladder.is_push(spec or {}):
        return None
    return push.home_of(focus.load(repo), str(law))


__all__ = ["CONTRACT", "being_read", "measurements", "others", "pushed_as", "richer", "rung_rows", "rungs"]
