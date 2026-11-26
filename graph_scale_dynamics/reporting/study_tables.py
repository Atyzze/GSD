from __future__ import annotations

import gzip
import io
import json
import math

TABLES_CONTRACT = "gsd-study-tables-1"
PROBES = ("d_s", "d_V", "d_B", "d_w")
RUNG_MEANS = ("mean_degree", "connected_fraction", "two_core_fraction", "clustering", "half_volume_radius",
              "effective_samples")
PAGE = 2000


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _mean(summary: dict, key: str):
    node = summary.get(key)
    return _finite(node.get("mean")) if isinstance(node, dict) else None


def rung_row(campaign_id: str, candidate_id: str, n: int, version: str, summary: dict) -> dict:
    row = {"campaign_id": campaign_id, "candidate_id": candidate_id, "n": int(n), "analysis_version": version,
           "seeds": summary.get("seeds")}
    for probe in PROBES:
        node = summary.get(probe) if isinstance(summary.get(probe), dict) else {}
        row[probe] = _finite(node.get("mean"))
        row[f"{probe}_se"] = _finite(node.get("se"))
        row[f"{probe}_valid_fraction"] = _finite(summary.get(f"{probe}_valid_fraction"))
    row["small_world_fraction"] = _finite(summary.get("small_world_fraction"))
    for key in RUNG_MEANS:
        row[key] = _mean(summary, key)
    row["log_diameter_flags"] = summary.get("log_diameter_flags")
    row["exponential_growth_flags"] = summary.get("exponential_growth_flags")
    row["probe_refusals"] = summary.get("probe_refusals")
    return row


def _rung_pages(repo, campaign_id: str, version: str):
    after = ("", -1)
    while True:
        rows = repo.conn.execute(
            "SELECT candidate_id,n,summary_json FROM rung_summaries WHERE campaign_id=? AND analysis_version=? "
            "AND (candidate_id>? OR (candidate_id=? AND n>?)) ORDER BY candidate_id,n LIMIT ?",
            (campaign_id, version, after[0], after[0], after[1], PAGE)).fetchall()
        if not rows:
            return
        for row in rows:
            yield str(row["candidate_id"]), int(row["n"]), row["summary_json"]
        after = (str(rows[-1]["candidate_id"]), int(rows[-1]["n"]))


def rung_rows(repo, campaign_ids, points: dict | None = None):
    for cid in campaign_ids:
        cid = str(cid)
        version = repo.campaign_analysis_contract(cid)
        for law, n, summary_json in _rung_pages(repo, cid, version):
            try:
                summary = json.loads(summary_json)
            except (TypeError, ValueError):
                continue
            row = rung_row(cid, law, n, version, summary)
            if points is not None:
                point = points.setdefault((cid, law), {"rungs": []})
                point["rungs"].append(n)
                for probe in PROBES:
                    if row[probe] is not None:
                        point[probe], point[f"{probe}_n"] = round(float(row[probe]), 5), n
                point["small_world_fraction_top"] = row["small_world_fraction"]
            yield row


def _parsed(text) -> dict:
    try:
        found = json.loads(text) if text else {}
    except (TypeError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def law_regime(regime, spec_json) -> str | None:
    if regime:
        return str(regime)
    spec = _parsed(spec_json)
    if not spec:
        return None
    from graph_scale_dynamics.dsl.dsl import dynamics_regime
    return dynamics_regime(spec)


def law_score_of(board: dict, law: str, top_n) -> dict | None:
    from graph_scale_dynamics.observability import law_score, score_board
    if top_n is None or int(top_n) < law_score.LADDER[0]:
        return law_score.zero(top_n)
    return score_board.of(board, law)


def law_rows(repo, campaign_ids, points: dict):
    from graph_scale_dynamics.observability import score_board
    from graph_scale_dynamics.operations import law_code
    for cid in campaign_ids:
        cid = str(cid)
        after = ""
        board = score_board.board(repo, cid)
        study, graphs = law_code.study_of(repo, cid), law_code.graphs(repo, cid)
        while True:
            rows = repo.conn.execute(
                "SELECT c.candidate_id,c.candidate_number,c.state,c.state_reason,d.rule,d.action,d.at_n,d.next_n,"
                "d.priority,d.reason,s.regime,s.spec_json "
                "FROM campaign_candidates c LEFT JOIN engine_decisions_latest d "
                "ON d.campaign_id=c.campaign_id AND d.candidate_id=c.candidate_id "
                "LEFT JOIN candidate_specs s ON s.candidate_id=c.candidate_id "
                "WHERE c.campaign_id=? AND c.candidate_id>? ORDER BY c.candidate_id LIMIT ?",
                (cid, after, PAGE)).fetchall()
            if not rows:
                break
            for row in rows:
                law = str(row["candidate_id"])
                point = points.get((cid, law)) or {"rungs": []}
                yield {"campaign_id": cid, "candidate_id": law, "candidate_number": row["candidate_number"],
                       "code": law_code.code(study, cid, graphs.get(law), law), "graph": graphs.get(law),
                       "state": row["state"], "state_reason": row["state_reason"],
                       "decision": {"rule": row["rule"], "action": row["action"], "at_n": row["at_n"],
                                    "next_n": row["next_n"], "priority": row["priority"], "reason": row["reason"]},
                       "regime": law_regime(row["regime"], row["spec_json"]),
                       "rungs": point["rungs"], "top_n": max(point["rungs"]) if point["rungs"] else None,
                       **{key: point.get(key) for probe in PROBES for key in (probe, f"{probe}_n")},
                       "small_world_fraction_top": point.get("small_world_fraction_top"),
                       "spec": _parsed(row["spec_json"]) or None,
                       "law_score": law_score_of(board, law, max(point["rungs"]) if point["rungs"] else None)}
            after = str(rows[-1]["candidate_id"])


def draw_rows(repo, campaign_ids):
    from graph_scale_dynamics.research.strata import stratum_of
    for cid in campaign_ids:
        cid, last = str(cid), (-1, -1)
        while True:
            rows = repo.conn.execute(
                "SELECT stream_index,draw_index,outcome,candidate_id,law_json FROM proposal_draws WHERE campaign_id=? "
                "AND (stream_index>? OR (stream_index=? AND draw_index>?)) ORDER BY stream_index,draw_index LIMIT ?",
                (cid, last[0], last[0], last[1], PAGE)).fetchall()
            if not rows:
                break
            for row in rows:
                try:
                    law = json.loads(row["law_json"] or "null")
                except ValueError:
                    law = None
                yield {"campaign_id": cid, "stream_index": int(row["stream_index"]),
                       "draw_index": int(row["draw_index"]), "outcome": str(row["outcome"]),
                       "candidate_id": row["candidate_id"],
                       "stratum": stratum_of(law) if isinstance(law, dict) else None}
            last = (int(rows[-1]["stream_index"]), int(rows[-1]["draw_index"]))


DECISION_COLUMNS = ("candidate_id", "decision_id", "at_n", "next_n", "action", "rule", "reason", "priority",
                    "queue_order", "jobs_created", "rows_changed", "released_hold", "jobs_seen", "engine",
                    "created_utc", "facts_json", "inputs_json", "context_json")


def decision_rows(repo, campaign_ids):
    for cid in campaign_ids:
        cid, after = str(cid), ""
        while True:
            rows = repo.conn.execute(
                f"SELECT {','.join(DECISION_COLUMNS)} FROM engine_decisions WHERE campaign_id=? AND decision_id>? "
                "ORDER BY decision_id LIMIT ?", (cid, after, PAGE)).fetchall()
            if not rows:
                break
            for row in rows:
                yield {"campaign_id": cid, **{key: row[key] for key in DECISION_COLUMNS}}
            after = str(rows[-1]["decision_id"])


CHAIN_FIELDS = ("campaign_id", "candidate_id", "job_id", "n", "seed", "replicate", "sweeps_multiplier", "audit",
                "chain", "init", "ran", "ended_at_cap", "termination", "final_edges", "final_mean_degree",
                "peak_edges", "peak_mean_degree", "max_degree", "moves", "accepted_moves", "work_units",
                "work_parts", "seconds", "seed_peak_memory_bytes", "evidence")


def _degree(edges, n):
    return round(2.0 * float(edges) / float(n), 4) if isinstance(edges, (int, float)) and n else None


def _termination(value):
    return value.get("reason") if isinstance(value, dict) else value


def work_weights_of(repo, campaign_id: str) -> dict | None:
    from graph_scale_dynamics.scheduling.limits import work_unit
    campaign = repo.campaign(str(campaign_id))
    try:
        return dict(work_unit((campaign or {}).get("spec") or {})["weights"])
    except (KeyError, TypeError, ValueError):
        return None


def chain_work(chain: dict, weights: dict | None) -> dict:
    from graph_scale_dynamics.scaleflow.one_shot import WORK_PARTS, units_of
    parts = (chain.get("accounting") or {}).get("parts")
    if chain.get("skipped") or not isinstance(parts, dict):
        return {"moves": None, "accepted_moves": None, "work_units": None, "work_parts": None}
    counted = {name: int(parts.get(name) or 0) for name in WORK_PARTS}
    accepted = chain.get("accepted_moves")
    return {"moves": counted["moves"], "accepted_moves": int(accepted) if isinstance(accepted, int) else None,
            "work_units": units_of(counted, weights) if weights else None, "work_parts": counted}


def chain_rows(repo, campaign_ids, store):
    from graph_scale_dynamics.artifact_store.retention import COMPACT_SCHEMAS
    from graph_scale_dynamics.domain.model import INTERRUPTED_ATTEMPT_CLASSES
    interrupted = ",".join(f"'{name}'" for name in INTERRUPTED_ATTEMPT_CLASSES)
    for cid in campaign_ids:
        cid, after = str(cid), ""
        weights = work_weights_of(repo, cid)
        while True:
            rows = repo.conn.execute(
                "SELECT j.job_id,j.candidate_id,j.n,j.seed,j.replicate,j.exec_sweeps_multiplier AS multiplier,"
                "j.exec_sampler_audit AS audit,ar.compact_artifact,"
                "(SELECT COALESCE(a.peak_pss_bytes,a.peak_uss_bytes,a.peak_rss_bytes) FROM attempts a "
                f"WHERE a.job_id=j.job_id AND a.wall_seconds IS NOT NULL AND (a.error_class IS NULL OR a.error_class "
                f"NOT IN ({interrupted})) ORDER BY a.finished_utc DESC LIMIT 1) AS memory "
                "FROM jobs j LEFT JOIN artifact_retention ar ON ar.artifact_hash=j.result_artifact "
                "WHERE j.campaign_id=? AND j.kind='simulate' AND j.status='done' AND j.job_id>? "
                "ORDER BY j.job_id LIMIT ?", (cid, after, PAGE)).fetchall()
            if not rows:
                break
            for row in rows:
                n = int(row["n"])
                job = {"campaign_id": cid, "candidate_id": str(row["candidate_id"]), "job_id": str(row["job_id"]),
                       "n": n, "seed": row["seed"], "replicate": row["replicate"],
                       "sweeps_multiplier": row["multiplier"], "audit": bool(row["audit"]),
                       "seed_peak_memory_bytes": row["memory"]}
                compact, why = None, None
                if not row["compact_artifact"]:
                    why = "no compact evidence is recorded for this run"
                else:
                    try:
                        compact = store.get_json(str(row["compact_artifact"]), verify=True)
                    except (OSError, ValueError) as exc:
                        why = f"its compact evidence is not readable: {type(exc).__name__}"
                    if compact is not None and (str(compact.get("schema")) not in COMPACT_SCHEMAS
                                                or int(compact.get("n", -1)) != n):
                        compact, why = None, "its compact evidence is not this run's"
                if compact is None:
                    yield {**{key: None for key in CHAIN_FIELDS}, **job, "evidence": why}
                    continue
                for chain in compact.get("chains") or []:
                    final = chain.get("final") if isinstance(chain.get("final"), dict) else {}
                    yield {**job, "chain": chain.get("start"), "init": chain.get("init"),
                           "ran": not chain.get("skipped"), "ended_at_cap": bool(chain.get("ended")),
                           "termination": _termination(chain.get("termination")),
                           "final_edges": final.get("edge_count"),
                           "final_mean_degree": _degree(final.get("edge_count"), n),
                           "peak_edges": final.get("peak_edge_count"),
                           "peak_mean_degree": _degree(final.get("peak_edge_count"), n),
                           "max_degree": final.get("max_degree"), **chain_work(chain, weights),
                           "seconds": (chain.get("seconds") if not chain.get("skipped")
                                       and isinstance(chain.get("seconds"), (int, float)) else None),
                           "evidence": "compact"}
            after = str(rows[-1]["job_id"])


def gzip_ndjson(rows) -> tuple[bytes, int]:
    buffer, count = io.BytesIO(), 0
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=6, mtime=0) as out:
        for row in rows:
            out.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
                      .encode("utf-8") + b"\n")
            count += 1
    return buffer.getvalue(), count


def tables(repo, campaign_ids, blobs=None) -> dict:
    points: dict = {}
    rungs, rung_count = gzip_ndjson(rung_rows(repo, campaign_ids, points))
    laws, law_count = gzip_ndjson(law_rows(repo, campaign_ids, points))
    draws, draw_count = gzip_ndjson(draw_rows(repo, campaign_ids))
    decisions, decision_count = gzip_ndjson(decision_rows(repo, campaign_ids))
    readme = {"contract": TABLES_CONTRACT, "format": "newline-delimited JSON, gzip-compressed, one object per line",
              "tables": {"rungs.ndjson.gz": {"rows": rung_count, "one_row_per": "law and rung",
                                             "source": "rung_summaries, under each campaign's analysis contract"},
                         "laws.ndjson.gz": {"rows": law_count, "one_row_per": "law",
                                            "source": "campaign_candidates, engine_decisions_latest and the rung "
                                                      "rows (the landscape's point: each probe's reading at the "
                                                      "largest rung that has one); regime from candidate_specs "
                                                      "(dsl.dynamics_regime: zero_temperature or equilibrium); the "
                                                      "law's code (`code`, SnCnGn: the study, the campaign and its "
                                                      "first graph's number, `graph`; the study and the campaign and "
                                                      "the start of its id where no graph has run); the "
                                                      "law itself (`spec`, as candidate_specs holds it: its terms, "
                                                      "couplings and dynamics, whose fingerprint is its id), so a "
                                                      "study can start from the bundle's laws; and the folder's own "
                                                      "score of it (`law_score`, the score board the controller keeps "
                                                      "under the score in force, its seeds counted only where their "
                                                      "chain stopped changing; null where the board has not reached "
                                                      "the law yet)"},
                         "draws.ndjson.gz": {"rows": draw_count, "one_row_per": "draw",
                                             "source": "proposal_draws, each law's stratum read from it "
                                                       "(research/strata.stratum_of): what a stratified study's "
                                                       "rates per draw are reweighted by"},
                         "decisions.ndjson.gz": {"rows": decision_count, "one_row_per": "engine decision",
                                                 "source": "engine_decisions, every row of every campaign, its "
                                                           "facts, inputs and context as the decider stored them "
                                                           "(JSON text): what tools/replay_bundle.py replays "
                                                           "every decision from"}},
              "read_with": {"pandas": "pandas.read_json('rungs.ndjson.gz', lines=True)",
                            "duckdb": "SELECT * FROM read_json_auto('rungs.ndjson.gz')"}}
    found = {"rungs.ndjson.gz": rungs, "laws.ndjson.gz": laws, "draws.ndjson.gz": draws,
             "decisions.ndjson.gz": decisions}
    chain_source = ("every simulation that finished (jobs, kind simulate, status done), one row for each of its chains, "
                    "read from the run's compact evidence in the folder's blob store: the chain's final and peak edge "
                    "count and mean degree (2 x edges / N), its largest degree, whether it ended at the mean degree "
                    "cap and why it ended; its moves, the moves it accepted (each one changes an edge: a chain with "
                    "none changed nothing), its work in the campaign's unit and the six counts the unit weighs "
                    "(`work_parts`), all counted from the chain's first move across its chunks, and its seconds in "
                    "the engine; the seed's peak memory as report 28 reads it (the last finished attempt "
                    "that was not interrupted: PSS, else USS, else RSS); a run whose evidence cannot be read is one "
                    "row with `evidence` saying why")
    if blobs is not None:
        from graph_scale_dynamics.artifact_store.blobstore import BlobStore
        try:
            chains, chain_count = gzip_ndjson(chain_rows(repo, campaign_ids, BlobStore(blobs)))
        except Exception as exc:  # noqa: BLE001
            readme["tables"]["chains.ndjson.gz"] = {"rows": 0, "one_row_per": "seed and chain",
                                                    "source": chain_source,
                                                    "unavailable": f"{type(exc).__name__}: {str(exc)[:300]}"}
        else:
            found["chains.ndjson.gz"] = chains
            readme["tables"]["chains.ndjson.gz"] = {"rows": chain_count, "one_row_per": "seed and chain",
                                                    "source": chain_source}
    return dict(found, **{"README.json": json.dumps(readme, indent=1, sort_keys=True).encode("utf-8")})
