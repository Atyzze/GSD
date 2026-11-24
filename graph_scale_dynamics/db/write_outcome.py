from __future__ import annotations


def job_commit_landed(repo, job_id: str, owner: str, lease_generation: int, digest: str) -> bool | None:
    row = repo.conn.execute(
        "SELECT status,lease_owner,lease_generation,result_artifact FROM jobs WHERE job_id=?", (job_id,),
    ).fetchone()
    if row is None:
        return False
    if row["status"] == "done" and str(row["result_artifact"] or "") == str(digest):
        return True
    if (row["status"] == "leased" and row["lease_owner"] == owner
            and int(row["lease_generation"] or 0) == int(lease_generation)):
        return None
    return False


def analysis_claim_state(repo, campaign_id: str, artifact: str, analysis_version: str, owner: str,
                         claim_token: str) -> dict | None:
    row = repo.conn.execute(
        "SELECT status,lease_owner,claim_token,attempts,max_attempts,next_attempt_utc,error_class "
        "FROM analysis_queue WHERE campaign_id=? AND input_artifact=? AND analysis_version=?",
        (campaign_id, artifact, analysis_version),
    ).fetchone()
    if row is None:
        return None
    measured = repo.conn.execute(
        "SELECT 1 FROM measurements WHERE campaign_id=? AND input_artifact=? AND analysis_version=? LIMIT 1",
        (campaign_id, artifact, analysis_version),
    ).fetchone() is not None
    return dict(row) | {"held": bool(row["status"] == "leased" and row["lease_owner"] == owner
                                      and row["claim_token"] == claim_token),
                        "measured": measured}


def rebuild_landed(repo, campaign_id: str, candidate_id: str, analysis_version: str, owner: str,
                   claim_token: str) -> bool | None:
    row = repo.conn.execute(
        "SELECT status,lease_owner,claim_token FROM candidate_evidence_rebuilds "
        "WHERE campaign_id=? AND candidate_id=? AND analysis_version=?",
        (campaign_id, candidate_id, analysis_version),
    ).fetchone()
    if (row is not None and row["status"] == "leased" and row["lease_owner"] == owner
            and row["claim_token"] == claim_token):
        return None
    return bool(row is not None and row["status"] == "done")


def give_back_unseen_claims(repo, owner: str) -> dict:
    jobs = repo.conn.execute("SELECT job_id,lease_generation FROM jobs WHERE status='leased' AND lease_owner=?",
                             (owner,)).fetchall()
    given = {"jobs": sum(1 for row in jobs if repo.release_job(row["job_id"], owner, int(row["lease_generation"])))}
    analyses = repo.conn.execute(
        "SELECT campaign_id,input_artifact,analysis_version,claim_token FROM analysis_queue "
        "WHERE status='leased' AND lease_owner=?", (owner,)).fetchall()
    given["analyses"] = sum(1 for row in analyses if repo.release_analysis_claim(
        row["campaign_id"], row["input_artifact"], row["analysis_version"], owner, row["claim_token"]))
    return given


__all__ = ["analysis_claim_state", "give_back_unseen_claims", "job_commit_landed", "rebuild_landed"]
