from __future__ import annotations

import time
from pathlib import Path

from graph_scale_dynamics.domain.model import utc_now
from graph_scale_dynamics.operations import zone_choice as Z

CONTRACT = "gsd-dex-check-1"
STATE, ZONE = "dex_check", "zone_chosen"
EVERY_SECONDS = 60.0
KEPT = ("law", "n", "seed", "replicate", "chain", "init", "moves", "ran", "science", "source")
_RECORDED: dict[str, tuple[list, dict[str, list[dict]]]] = {}
_LAST: dict[str, float] = {}


def first(state: dict | None) -> bool:
    return bool((state or {}).get("dex_first"))


def records(state: dict | None) -> list[dict]:
    from graph_scale_dynamics.operations import study_seed
    return [r for r in study_seed.records(state) if study_seed.selected(r) and r.get("laws") is not None]


def laws_held(repo, campaign_id: str | None) -> list[str]:
    if campaign_id is None:
        return []
    return sorted(str(row["candidate_id"]) for row in repo.conn.execute(
        "SELECT candidate_id FROM campaign_candidates WHERE campaign_id=?", (str(campaign_id),)).fetchall())


def owed(repo, state: dict | None) -> list[str]:
    from graph_scale_dynamics.operations import study_seed
    if not first(state) or (state or {}).get(ZONE):
        return []
    gone = study_seed.let_go(state)
    judged = ((state or {}).get(STATE) or {}).get("laws") or {}
    return [law for law in laws_held(repo, study_seed.campaign_of(state))
            if law not in gone and (judged.get(law) or {}).get("verdict") is None]


def waiting(state: dict | None) -> bool:
    return first(state) and not (state or {}).get(ZONE) and bool(records(state))


def _stamp(path: Path) -> list:
    if path.is_file():
        found = path.stat()
        return [found.st_size, found.st_mtime_ns]
    inner = sorted(path.rglob("chains.ndjson.gz"))
    return [[p.stat().st_size, p.stat().st_mtime_ns] for p in inner]


def path_of(folder: Path | None, name: str) -> Path | None:
    from graph_scale_dynamics.operations import dex, imports
    if folder is None or not Path(folder).is_dir():
        return None
    return next((p for p in sorted(Path(folder).iterdir(), key=lambda p: p.name)
                 if imports.is_bundle(p) and dex.name_of(p) == name), None)


def recorded(path: Path) -> dict[str, list[dict]]:
    from graph_scale_dynamics.operations import dex
    stamp = _stamp(path)
    kept = _RECORDED.get(str(path))
    if kept is not None and kept[0] == stamp:
        return kept[1]
    by_law: dict[str, list[dict]] = {}
    for row in dex.read_part(path).get("chains") or []:
        by_law.setdefault(str(row.get("law")), []).append({k: row.get(k) for k in KEPT + dex.RUN_AGAIN})
    _RECORDED[str(path)] = (stamp, by_law)
    return by_law


def chains_here(repo, campaign_id: str, blobs: Path | None, laws: set[str], *, study: str, science: str | None
                ) -> list[dict]:
    from graph_scale_dynamics.operations import dex
    from graph_scale_dynamics.reporting import study_tables as T
    if blobs is None or not Path(blobs).is_dir() or not laws:
        return []
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    name = by_of(study)
    return [dex._chain(row, str(row["candidate_id"]), name, science, study)
            for row in T.chain_rows(repo, [str(campaign_id)], BlobStore(Path(blobs)), laws=set(laws))
            if row.get("candidate_id") is not None]


def by_of(study: str) -> str:
    return f"study {study}'s folder"


def decided(repo, campaign_id: str, law: str) -> bool:
    from graph_scale_dynamics.operations import study_map
    return study_map.decided(repo, str(campaign_id), str(law))


def verdict_of(check: dict | None) -> str:
    if check and int(check.get("differ") or 0):
        return Z.DENIED
    if check and int(check.get("agree") or 0):
        return Z.CONFIRMED
    return Z.UNMATCHED


def judged(recorded_rows: list[dict], own: list[dict], laws: list[str], *, by: str, science: str | None
           ) -> dict[str, dict]:
    from graph_scale_dynamics.operations import dex
    checks = dex.verify(recorded_rows, own, by=by, science=science)
    kept = [row for row in recorded_rows if row.get("science") == science and row.get("source") != by and row.get("ran")]
    likes, starts = {dex.like(row) for row in kept}, {dex.like(row)[:6] for row in kept}
    ran: dict[str, int] = {}
    other: dict[str, int] = {}
    for row in own:
        if row.get("ran"):
            ran[str(row["law"])] = ran.get(str(row["law"]), 0) + 1
            if dex.like(row) not in likes and dex.like(row)[:6] in starts:
                other[str(row["law"])] = other.get(str(row["law"]), 0) + 1
    out = {}
    for law in laws:
        check = checks.get(law) or {"agree": 0, "differ": 0, "other_length": 0, "sizes": [], "against": []}
        out[law] = {"verdict": verdict_of(check), "agree": int(check.get("agree") or 0),
                    "differ": int(check.get("differ") or 0), "other_length": other.get(law, 0),
                    "sizes": list(check.get("sizes") or []), "against": list(check.get("against") or []),
                    "chains": ran.get(law, 0), "at": utc_now(),
                    **({"first_differ": check["first_differ"]} if check.get("first_differ") else {})}
    return out


def _codes(state: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for record in records(state):
        for law, entry in (record.get("laws") or {}).items():
            out.setdefault(str(law), {"code": entry.get("code"), "score": entry.get("score"),
                                      "bundle": record.get("bundle")})
        for law, code in (record.get("laws_only") or {}).items():
            out.setdefault(str(law), {"code": code, "score": None, "bundle": record.get("bundle")})
    return out


def controls() -> set[str]:
    from graph_scale_dynamics.operations import standing_controls as S
    found = S.load_criterion()
    return {law["candidate_id"] for law in S.laws(found)} if found else set()


def choose(repo, state: dict) -> dict:
    from graph_scale_dynamics.operations import focus, study_seed
    campaign_id = study_seed.campaign_of(state)
    radius = float(state["plan"]["neighbourhood"]["confirm_radius"])
    known, held, off = _codes(state), controls(), study_seed.let_go(state)
    laws = {}
    for law, check in ((state.get(STATE) or {}).get("laws") or {}).items():
        if law in off:
            continue
        laws[law] = {"spec": focus._spec_of(repo, campaign_id, law), "verdict": check.get("verdict"),
                     "code": (known.get(law) or {}).get("code") or check.get("code"),
                     "score": (known.get(law) or {}).get("score"), "control": law in held}
    found = Z.first(laws, radius=radius)
    chosen = found["chosen"]
    return dict(found, at=utc_now(), campaign=campaign_id,
                **({"centre": chosen["centre"], "code": chosen["code"]} if chosen else {}))


def keep(repo, root: Path | None, *, blobs: Path | None, now: float | None = None, force: bool = False
         ) -> dict | None:
    from graph_scale_dynamics.operations import focus, imports, study_seed
    from graph_scale_dynamics.reporting import science_contract
    state = focus.load(repo)
    if not first(state) or state.get(ZONE) or not records(state):
        return None
    clock = time.monotonic() if now is None else float(now)
    if not force and clock - _LAST.get(str(state["study"]), -1e18) < EVERY_SECONDS:
        return None
    _LAST[str(state["study"])] = clock
    campaign_id = study_seed.campaign_of(state)
    pending = owed(repo, state)
    check = state.setdefault(STATE, {"contract": CONTRACT, "began_utc": utc_now(), "laws": {}})
    check["campaign"] = campaign_id
    check["bundles"] = [r["bundle"] for r in records(state)]
    science = science_contract.science()[0].get("sha256")
    ready = [law for law in pending if decided(repo, campaign_id, law)]
    added = 0
    if ready:
        folder = None if root is None else Path(root) / imports.FOLDER
        rows: list[dict] = []
        for record in records(state):
            path = path_of(folder, str(record["bundle"]))
            if path is not None:
                found = recorded(path)
                rows += [row for law in ready for row in found.get(law) or []]
        own = chains_here(repo, campaign_id, blobs, set(ready), study=str(state["study"]), science=science)
        known = _codes(state)
        for law, entry in judged(rows, own, ready, by=by_of(str(state["study"])), science=science).items():
            check["laws"][law] = dict(entry, code=(known.get(law) or {}).get("code"),
                                      score=(known.get(law) or {}).get("score"),
                                      bundle=(known.get(law) or {}).get("bundle"))
            added += 1
    check["counts"] = dict(Z.counts(check["laws"]), owed=len(pending) - added,
                           held=len(laws_held(repo, campaign_id)))
    chosen = None
    if not owed(repo, state):
        chosen = state[ZONE] = choose(repo, state)
        check["done_utc"] = utc_now()
        state["events"].append({"at": utc_now(), "zone_chosen": chosen.get("code"), "why": chosen["why"][:300]})
    elif added:
        state["events"].append({"at": utc_now(), "dex_checked": added, "owed": check["counts"]["owed"]})
    focus.save(repo, state)
    return {"checked": added, "owed": check["counts"]["owed"], "chosen": (chosen or {}).get("code"),
            "none": chosen is not None and chosen.get("chosen") is None}


def taken(state: dict) -> dict | None:
    zone = (state or {}).get(ZONE) or {}
    if not zone.get("chosen") or zone.get("taken_utc"):
        return None
    return zone


def words(state: dict) -> str | None:
    if not first(state):
        return None
    check = (state or {}).get(STATE) or {}
    zone = (state or {}).get(ZONE)
    if zone is None and not records(state):
        return None
    tally = check.get("counts") or {}
    said = (f"{tally.get('confirmed', 0):,} confirmed, {tally.get('denied', 0):,} denied, "
            f"{tally.get('unmatched', 0):,} with no chain to compare")
    held = tally.get("held") or len({law for r in records(state) for law in list((r.get("laws") or {}))
                                     + list((r.get("laws_only") or {}))})
    if zone is None:
        return (f"verifying the dex first: {len(check.get('laws') or {}):,} of {held:,} laws read "
                f"again ({said}); no law is taken into focus before every law has read")
    if zone.get("chosen") is None:
        return f"the dex verified ({said}); {zone['why']}"
    return None


def reading(state: dict | None) -> dict | None:
    if not first(state):
        return None
    check = (state or {}).get(STATE) or {}
    rows = [dict(entry, law=law) for law, entry in (check.get("laws") or {}).items()]
    order = {Z.DENIED: 0, Z.UNMATCHED: 1, Z.CONFIRMED: 2}
    rows.sort(key=lambda r: (order.get(r.get("verdict"), 3), -int(r.get("score") or 0), str(r.get("code") or "")))
    return {"contract": CONTRACT, "campaign": check.get("campaign"), "bundles": check.get("bundles") or [],
            "counts": check.get("counts") or {}, "began_utc": check.get("began_utc"), "done_utc": check.get("done_utc"),
            "laws": rows, "zone": (state or {}).get(ZONE), "words": words(state or {})}


__all__ = ["CONTRACT", "STATE", "ZONE", "by_of", "chains_here", "choose", "controls", "decided", "first", "judged",
           "keep", "laws_held", "owed", "path_of", "reading", "recorded", "records", "taken", "verdict_of", "waiting",
           "words"]
