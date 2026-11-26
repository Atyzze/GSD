from __future__ import annotations

import json

from graph_scale_dynamics.domain.model import utc_now

MEMORY_CEILING_CLASS = "memory_hard_cap"
GIVEN_BACK_CLASS = "memory_given_back"
EVENT_TOPIC = "analysis_memory_given_back"
GIVEN_BACK_NOTE = ("given back once after the memory ceiling stopped it (E1): it runs with the deepest rung's "
                   "ceiling, and a second stop there is the law's")
KIND_MEMORY, KIND_RESCUE, KIND_REPLAYED = "memory", "rescue", "replayed"
RAW_LOST_TEXT = "TRANSIENT_RAW_LOST"
NOTES = {
    KIND_MEMORY: GIVEN_BACK_NOTE,
    KIND_RESCUE: ("given back once more: its give-back lost the deepest ceiling on a later attempt (the give-back's rule), "
                  "so it runs again with the ceiling, and a stop now is the law's"),
    KIND_REPLAYED: ("given back once more: its simulation was given back, its raw output was then lost and the "
                    "job run again, and the replay's analysis ran without the ceiling; it runs with it now, and a "
                    "stop now is the law's"),
}


def given_back_events(repo) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for row in repo.conn.execute("SELECT payload_json,created_utc FROM events WHERE topic=? ORDER BY created_utc",
                                 (EVENT_TOPIC,)).fetchall():
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            key = (str(payload.get("campaign_id")), str(payload.get("input_artifact")))
            entry = out.setdefault(key, {"utc": str(row["created_utc"] or ""), "kinds": set()})
            entry["kinds"].add(str(payload.get("kind") or KIND_MEMORY))
    return out


def lost_siblings(repo, campaign_id: str, producer_job, artifact: str) -> list[str]:
    if producer_job is None:
        return []
    rows = repo.conn.execute(
        "SELECT input_artifact FROM analysis_queue WHERE campaign_id=? AND producer_job=? AND input_artifact<>? "
        "AND status='failed' AND error LIKE ?", (str(campaign_id), producer_job, str(artifact), RAW_LOST_TEXT + "%"))
    return [str(r["input_artifact"]) for r in rows.fetchall()]


def is_replay_due(repo, item: dict, events: dict) -> bool:
    if str(item.get("error_class") or "") != MEMORY_CEILING_CLASS:
        return False
    campaign_id, artifact = str(item["campaign_id"]), str(item["input_artifact"])
    if (campaign_id, artifact) in events:
        return False
    lost = lost_siblings(repo, campaign_id, item.get("producer_job"), artifact)
    return any((campaign_id, sibling) in events for sibling in lost)


def is_first_memory_stop(error_class: str | None, campaign_id: str, artifact: str, before) -> bool:
    return str(error_class or "") == MEMORY_CEILING_CLASS and (str(campaign_id), str(artifact)) not in before


def lost_the_room(repo, campaign_id: str, artifact: str, since_utc: str) -> bool:
    row = repo.conn.execute(
        "SELECT 1 FROM analysis_attempts WHERE campaign_id=? AND input_artifact=? AND started_utc>=? "
        "AND error_class IS NOT NULL AND error_class<>? LIMIT 1",
        (campaign_id, artifact, since_utc, MEMORY_CEILING_CLASS)).fetchone()
    return row is not None


def is_rescue_due(repo, error_class: str | None, campaign_id: str, artifact: str, events: dict) -> bool:
    entry = events.get((str(campaign_id), str(artifact)))
    if str(error_class or "") != MEMORY_CEILING_CLASS or entry is None or KIND_RESCUE in entry["kinds"]:
        return False
    return lost_the_room(repo, str(campaign_id), str(artifact), entry["utc"])


def kind_of(item: dict, events: dict) -> str | None:
    key = (str(item["campaign_id"]), str(item["input_artifact"]))
    if is_first_memory_stop(item.get("error_class"), *key, events):
        return KIND_MEMORY
    return None


def mark_given_back(repo, items: list[dict]) -> int:
    marked = 0
    for item in items:
        kind = item.get("giveback")
        if kind is None and str(item.get("error_class") or "") == MEMORY_CEILING_CLASS:
            kind = KIND_MEMORY
        if kind not in NOTES:
            continue
        changed = repo.conn.execute(
            "UPDATE analysis_queue SET error_class=?,error=? WHERE campaign_id=? AND input_artifact=? "
            "AND analysis_version=? AND status='queued'",
            (GIVEN_BACK_CLASS, NOTES[kind], item["campaign_id"], item["input_artifact"],
             item["analysis_version"])).rowcount or 0
        if changed:
            marked += 1
            repo.conn.execute("INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)", (EVENT_TOPIC, json.dumps(
                {"campaign_id": item["campaign_id"], "candidate_id": item.get("candidate_id"), "n": item.get("n"),
                 "seed": item.get("seed"), "input_artifact": item["input_artifact"],
                 "analysis_version": item["analysis_version"], "kind": kind}), utc_now()))
    return marked


def is_given_back(repo, job: dict, artifact: str) -> bool:
    conn = getattr(repo, "conn", None)
    if conn is None:
        return False
    row = conn.execute(
        "SELECT error_class FROM analysis_queue WHERE campaign_id=? AND input_artifact=? AND status='leased' LIMIT 1",
        (job["campaign_id"], artifact)).fetchone()
    if row is not None and str(row["error_class"] or "") == GIVEN_BACK_CLASS:
        return True
    artifacts = [str(artifact), *lost_siblings(repo, job["campaign_id"], job.get("job_id"), artifact)]
    markers = ["%" + json.dumps({"input_artifact": a})[1:-1] + "%" for a in artifacts]
    found = conn.execute("SELECT payload_json FROM events WHERE topic=? AND ("
                         + " OR ".join("payload_json LIKE ?" for _ in markers) + ")", (EVENT_TOPIC, *markers))
    for row in found.fetchall():
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and str(payload.get("campaign_id")) == str(job["campaign_id"]) \
                and str(payload.get("input_artifact")) in artifacts:
            return True
    return False


def analysis_stop_bytes(repo, job: dict, artifact: str) -> tuple[int, str]:
    from graph_scale_dynamics.scheduling.memory import given_back_limit_bytes, process_stop_bytes
    spec = job.get("spec") or {}
    if is_given_back(repo, job, artifact):
        return given_back_limit_bytes(), "given back: deepest ceiling"
    return process_stop_bytes(spec, int(job["n"]), job.get("memory_reservation_bytes"))
