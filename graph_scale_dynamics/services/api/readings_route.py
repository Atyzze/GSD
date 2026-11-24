from __future__ import annotations

from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
from graph_scale_dynamics.observability import evidence_sources, law_score
from graph_scale_dynamics.observability.starts_reading import hold_structure, law_reading as starts_reading
from graph_scale_dynamics.observability.space_score import space_score
from graph_scale_dynamics.observability.two_chains import stopping_numbers, two_chains
from graph_scale_dynamics.research.what_happened import law_story
from graph_scale_dynamics.services.api import gate_route, study_route
from graph_scale_dynamics.services.api.answer_cache import ANSWERS

PREFIXES = (["api", "structure"], ["api", "gate"], ["api", "study-bundles"], ["api", "runtime-imports"],
            ["api", "curves"])
BLOBS_ROOT = None
CURVES_MAX_BYTES = 64 * 1024 * 1024


def handles(parts: list[str]) -> bool:
    return parts[:2] in PREFIXES and len(parts) <= (5 if parts[1] == "curves" else 4)


def _version(repo, campaign_id: str) -> str:
    return str(((repo.campaign(str(campaign_id)) or {}).get("spec") or {}).get("analysis_version") or ANALYSIS_VERSION)


def structure(repo, campaign_id: str, candidate_id: str) -> dict | None:
    rows = repo.measurements(candidate_id, _version(repo, campaign_id), campaign_id)
    if not rows and repo.candidate(candidate_id, campaign_id) is None:
        memberships = repo.candidate_campaign_ids(candidate_id)
        if len(memberships) != 1:
            return None
        campaign_id = str(memberships[0])
        rows = repo.measurements(candidate_id, _version(repo, campaign_id), campaign_id)
    decisions = repo.engine_decisions(campaign_id, candidate_id) or []
    latest = decisions[-1] if decisions else None
    from graph_scale_dynamics.observability.every_chain_graph import every_chain
    given_start = _given_start(repo, campaign_id, candidate_id)
    starts = _starts(repo, campaign_id, candidate_id)
    chains = two_chains(rows, given_start=given_start, policy=_stopping_policy(repo, campaign_id), starts=starts)
    law = repo.candidate(str(candidate_id), str(campaign_id)) or {}
    campaign_spec = (repo.campaign(str(campaign_id)) or {}).get("spec")
    structure = hold_structure(campaign_spec)
    read = starts_reading(chains, starts, structure=structure)
    return {"campaign_id": campaign_id, "candidate_id": candidate_id,
            "what_happened": law_story(rows, latest),
            "every_chain": every_chain(rows, chains, given_start), "given_start": given_start, "chains": chains,
            "space_score": space_score(chains, law.get("spec") if isinstance(law.get("spec"), dict) else None),
            "starts_reading": read,
            "score": law_score.score(chains, read, starts=starts, first_given=law_score.given_family(
                campaign_spec, str(candidate_id), law.get("spec")), structure=structure)}


def _stopping_policy(repo, campaign_id: str) -> dict:
    campaign = repo.campaign(str(campaign_id)) or {}
    return stopping_numbers(campaign.get("spec") or {})


def _first_start(repo, campaign_id: str, candidate_id: str) -> dict | None:
    campaign = repo.campaign(str(campaign_id)) or {}
    try:
        from graph_scale_dynamics.scheduling.job_creation import resolve_given_start
        law = repo.candidate(str(candidate_id), str(campaign_id)) or {}
        return resolve_given_start(campaign.get("spec") or {}, 4096, candidate_id, law.get("spec"))
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _starts(repo, campaign_id: str, candidate_id: str) -> list | None:
    campaign = repo.campaign(str(campaign_id)) or {}
    listed = ((campaign.get("spec") or {}).get("sampling_contract") or {}).get("given_starts")
    if not isinstance(listed, list) or not listed:
        return None
    starts = [dict(s) for s in listed if isinstance(s, dict)]
    first = _first_start(repo, campaign_id, candidate_id)
    if starts and isinstance(first, dict) and first.get("family"):
        starts[0]["family"] = first["family"]
    return starts


def _given_start(repo, campaign_id: str, candidate_id: str) -> str:
    campaign = repo.campaign(str(campaign_id)) or {}
    sampling = (campaign.get("spec") or {}).get("sampling_contract") or {}
    listed = sampling.get("given_starts")
    if isinstance(listed, list) and listed and isinstance(listed[0], dict):
        first = _first_start(repo, campaign_id, candidate_id) or {}
        return f"the {listed[0].get('name')} start, {first.get('family') or listed[0].get('family')}"
    declared = (sampling.get("given_start_by_law") or {}).get(str(candidate_id)) or sampling.get("given_start")
    family = (declared or {}).get("family") if isinstance(declared, dict) else None
    return f"the declared answer, {family}" if family else "a random graph (Erdos-Renyi, mean degree 8)"


def curves(repo, campaign_id: str, candidate_id: str, n: int, blobs_root=None) -> dict | None:
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    from graph_scale_dynamics.observability import every_chain_graph
    rows = repo.measurements(candidate_id, _version(repo, campaign_id), campaign_id)
    if not rows:
        return None
    starts = _starts(repo, campaign_id, candidate_id)
    chains = two_chains([r for r in rows if int(r["n"]) == int(n)], starts=starts)
    listed = every_chain_graph.listed(chains, _given_start(repo, campaign_id, candidate_id))
    store = BlobStore(blobs_root if blobs_root is not None else BLOBS_ROOT)

    def load(digest):
        return store.get_json(digest, verify=False, max_compressed_bytes=CURVES_MAX_BYTES,
                              max_decoded_bytes=4 * CURVES_MAX_BYTES)
    return every_chain_graph.curves_at(rows, int(n), listed, load)


def _curves_now(db_path: str, campaign_id: str, candidate_id: str, n: int) -> dict | None:
    with Repo(db_path) as repo:
        return curves(repo, campaign_id, candidate_id, n)


def _structure_now(db_path: str, campaign_id: str, candidate_id: str) -> dict | None:
    with Repo(db_path) as repo:
        return structure(repo, campaign_id, candidate_id)


def runtime_imports(handler, db_path: str, *, publish: bool) -> None:
    try:
        with Repo(db_path) as repo:
            if publish:
                repo.publish_runtime_imports("api")
            own = [] if publish else [evidence_sources.runtime_import_record("api")]
            payload = evidence_sources.runtime_imports_payload(repo, extra_records=own)
        if own and isinstance(payload.get("services"), list):
            payload["services"] = [r for r in payload["services"] if r.get("service") != "api" or r == own[0]]
        handler._json(payload)
    except Exception as exc:  # noqa: BLE001
        handler._json({"error": f"{type(exc).__name__}: {exc}"}, 500)


def get(handler, db_path: str, parts: list[str]) -> None:
    if parts[1] == "study-bundles":
        return handler._json({"error": "use POST /api/study-bundles/delete"}, 405)
    if parts[1] == "gate":
        return gate_route.get(handler, db_path, parts)
    if parts[1] == "runtime-imports":
        return runtime_imports(handler, db_path, publish=False)
    if parts[1] == "curves":
        if len(parts) != 5 or not parts[4].isdigit() or BLOBS_ROOT is None:
            return handler._json({"error": "use /api/curves/<campaign id>/<candidate id>/<N>"}, 404)
        try:
            payload = ANSWERS.answer(("curves", db_path, parts[2], parts[3], parts[4]),
                                     lambda: _curves_now(db_path, parts[2], parts[3], int(parts[4])))
            return handler._json(payload if payload else {"error": "no such law"}, 200 if payload else 404)
        except Exception as exc:  # noqa: BLE001
            return handler._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
    if len(parts) != 4:
        return handler._json({"error": "use /api/structure/<campaign id>/<candidate id>"}, 404)
    try:
        payload = ANSWERS.answer(("structure", db_path, parts[2], parts[3]),
                                 lambda: _structure_now(db_path, parts[2], parts[3]))
        handler._json(payload if payload else {"error": "no such law"}, 200 if payload else 404)
    except Exception as exc:  # noqa: BLE001
        handler._json({"error": f"{type(exc).__name__}: {exc}"}, 500)


def post(handler, db_path: str, parts: list[str], max_bytes: int) -> None:
    if parts[1] == "gate":
        return gate_route.post(handler, db_path, parts, max_bytes)
    if parts[1] == "study-bundles":
        return study_route.post(handler, parts, max_bytes)
    if parts[1] == "runtime-imports" and len(parts) == 2:
        return runtime_imports(handler, db_path, publish=True)
    return handler._json({"error": "not found"}, 404)
