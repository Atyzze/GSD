from __future__ import annotations

import json

from graph_scale_dynamics.research.hamiltonian_preflight import PREFLIGHT_VERSION, equilibrium_identity

_FUNCTION: dict[tuple[str, str], str | None] = {}
_CAMPAIGN_VERSION: dict[str, str] = {}


def identity_version_of(spec: dict | None) -> str:
    from graph_scale_dynamics.services.proposer.blind import identity_version
    return identity_version(((spec or {}).get("search_policy") or {}).get("grid"))


def campaign_version(repo, campaign_id: str | None) -> str:
    if campaign_id is None:
        return PREFLIGHT_VERSION
    key = str(campaign_id)
    if key not in _CAMPAIGN_VERSION:
        stored = repo.campaign(key) if repo is not None else None
        if stored is None:
            return PREFLIGHT_VERSION
        _CAMPAIGN_VERSION[key] = identity_version_of(stored.get("spec"))
    return _CAMPAIGN_VERSION[key]


def function_hash(candidate_id: str, spec: dict | None, version: str = PREFLIGHT_VERSION) -> str | None:
    key = (str(candidate_id), str(version))
    if key not in _FUNCTION:
        try:
            _FUNCTION[key] = equilibrium_identity(spec or {}, version=version)[0]
        except Exception:
            _FUNCTION[key] = None
    return _FUNCTION[key]


def shared_laws(repo) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in repo.conn.execute(
            "SELECT candidate_id,campaign_id FROM candidates WHERE candidate_id IN "
            "(SELECT candidate_id FROM candidates GROUP BY candidate_id HAVING COUNT(*)>1)"):
        out.setdefault(str(row["candidate_id"]), []).append(str(row["campaign_id"]))
    return {law: sorted(held, key=_campaign_order) for law, held in out.items()}


def _campaign_order(campaign_id: str):
    return (0, int(campaign_id)) if str(campaign_id).isdigit() else (1, str(campaign_id))


def identity_context(repo, campaign_id: str, wanted: bool) -> tuple[dict, dict]:
    if not wanted:
        return {}, {}
    from graph_scale_dynamics.domain.model import candidate_numbers
    campaign_version(repo, campaign_id)
    return candidate_numbers(repo, campaign_id), shared_laws(repo)


def node_identity(candidate_id: str, spec: dict | None, shared: dict, campaign_id: str | None = None) -> dict:
    held = [c for c in shared.get(str(candidate_id), []) if c != str(campaign_id)] if shared else []
    version = PREFLIGHT_VERSION if campaign_id is None else _CAMPAIGN_VERSION.get(str(campaign_id), PREFLIGHT_VERSION)
    return {"function_hash": function_hash(candidate_id, spec, version), **({"also_in": held} if held else {})}


def _all_functions(repo) -> dict[str, list[tuple[str, str]]]:
    rows = [(str(r["campaign_id"]), str(r["candidate_id"]))
            for r in repo.conn.execute("SELECT campaign_id,candidate_id FROM candidates")]
    versions = {campaign: campaign_version(repo, campaign) for campaign in {c for c, _ in rows}}
    missing = sorted({(law, versions[campaign]) for campaign, law in rows
                      if (law, versions[campaign]) not in _FUNCTION})
    laws = sorted({law for law, _ in missing})
    specs: dict[str, dict] = {}
    for start in range(0, len(laws), 500):
        chunk = laws[start:start + 500]
        marks = ",".join("?" for _ in chunk)
        for r in repo.conn.execute(
                f"SELECT DISTINCT ON (candidate_id) candidate_id,spec_json FROM candidates "
                f"WHERE candidate_id IN ({marks})", tuple(chunk)):
            try:
                specs[str(r["candidate_id"])] = json.loads(r["spec_json"] or "{}")
            except (TypeError, ValueError):
                specs[str(r["candidate_id"])] = {}
    for law, version in missing:
        if law in specs:
            function_hash(law, specs[law], version)
    by_function: dict[str, list[tuple[str, str]]] = {}
    for campaign, law in rows:
        fn = _FUNCTION.get((law, versions[campaign]))
        if fn:
            by_function.setdefault(fn, []).append((campaign, law))
    return by_function


def identity_for(repo, campaign_id: str, candidate_id: str, spec: dict | None, *, limit: int = 20) -> dict:
    from graph_scale_dynamics.domain.model import ensemble_code
    fn = function_hash(candidate_id, spec, campaign_version(repo, campaign_id))
    same_law = [c for c in repo.candidate_campaign_ids(candidate_id) if str(c) != str(campaign_id)]
    others = [] if fn is None else [
        (c, law) for c, law in _all_functions(repo).get(fn, []) if law != str(candidate_id)]
    same_function = []
    for c, law in sorted(others, key=lambda pair: (_campaign_order(pair[0]), pair[1]))[:limit]:
        by_n = {int(r["n"]): int(r["ordinal"]) for r in repo.conn.execute(
            "SELECT n,MIN(graph_ordinal) AS ordinal FROM jobs WHERE campaign_id=? AND candidate_id=? "
            "AND kind='simulate' AND graph_ordinal IS NOT NULL GROUP BY n", (c, law))}
        same_function.append({"campaign_id": c, "candidate_id": law, "ensemble_code": ensemble_code(by_n)})
    return {"law_hash": str(candidate_id), "function_hash": fn,
            "same_law_in": sorted((str(c) for c in same_law), key=_campaign_order),
            "same_function": same_function, "same_function_count": len(others),
            "reading": ("the law's hash is its normalised law's fingerprint, the same in every campaign; the "
                        "function's hash is its energy with exact redundancies folded and the dynamics that shape a "
                        "finite run, so a law with another hash and this function hash is this function written "
                        "another way")}
