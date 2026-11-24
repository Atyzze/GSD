from __future__ import annotations

import json
import time

MEMORY_HOLD_CONTRACT = "gsd-memory-hold-1"
HOLD_KEY = "memory_hold"
HOLD_MAX_SECONDS = 3600
HOLD_REST_SECONDS = 1800
HOLD_REST_MAX_SECONDS = 8 * 3600
HOLDING_REFUSALS = ("transient_memory_floor", "transient_host_pressure")
SCRATCH_KEY = "scratch_relief"
SCRATCH_FRESH_SECONDS = 60.0
UNFIT_REWRITE_SECONDS = 30.0
UNFIT_SHOWN_SECONDS = 120.0
REACH_PARTS = ("reach_bytes", "available_bytes", "children_bytes", "movable_bytes", "floor_bytes")


def _stamp(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def scratch_room(conn, *, now: float | None = None) -> dict | None:
    row = conn.execute("SELECT value FROM control WHERE key=?", (SCRATCH_KEY,)).fetchone()
    try:
        value = json.loads(row["value"]) if row else None
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    clock = time.time() if now is None else float(now)
    return value if clock - float(value.get("at_epoch") or 0) <= SCRATCH_FRESH_SECONDS else None


def reach_bytes(*, available_bytes: int, children_bytes: int, movable_bytes: int, floor_bytes: int) -> int:
    return max(0, int(available_bytes) + int(children_bytes) + int(movable_bytes) - int(floor_bytes))


def reach(conn, *, snapshot=None, observations: list[dict] | None = None, now: float | None = None) -> dict:
    from graph_scale_dynamics.scheduling.memory import (
        admitted, host_available_floor_bytes, lease_memory_observations, system_memory)
    mem = snapshot or system_memory()
    rows = lease_memory_observations(conn) if observations is None else observations
    scratch = scratch_room(conn, now=now)
    parts = {"available_bytes": max(0, int(mem.available)),
             "children_bytes": sum(int(row.get("current_bytes") or 0) for row in rows if admitted(row)),
             "movable_bytes": int((scratch or {}).get("movable_bytes") or 0),
             "floor_bytes": host_available_floor_bytes(int(mem.total))}
    return dict(parts, reach_bytes=reach_bytes(**parts), scratch_read=scratch is not None)


def _out_of_reach(reach_of, requested_bytes: int) -> dict | None:
    room = reach_of() if callable(reach_of) else reach_of
    if not room or int(requested_bytes) <= int(room.get("reach_bytes") or 0):
        return None
    return {k: int(room.get(k) or 0) for k in REACH_PARTS}


def _unfit(job_id: str, campaign_id: str, n: int, requested_bytes: int, room: dict, now: float) -> dict:
    return {"job_id": str(job_id), "campaign_id": str(campaign_id), "n": int(n),
            "requested_bytes": int(requested_bytes), **room, "at_epoch": now, "at_utc": _stamp(now)}


def _note_unfit(conn, raw: str | None, hold: dict | None, unfit: dict, now: float) -> None:
    seen = (hold or {}).get("unfit") or {}
    if (now - float(seen.get("at_epoch") or 0) < UNFIT_REWRITE_SECONDS
            and int(unfit["requested_bytes"]) <= int(seen.get("requested_bytes") or 0)):
        return
    base = hold if hold is not None else {"contract": MEMORY_HOLD_CONTRACT, "state": "unheld", "run_outs": 0}
    _swap(conn, raw, hold, dict(base, unfit=unfit))


def rest_seconds(run_outs: int) -> int:
    return int(min(HOLD_REST_MAX_SECONDS, HOLD_REST_SECONDS * 2 ** max(0, int(run_outs) - 1)))


def _read_raw(conn) -> tuple[str | None, dict | None]:
    row = conn.execute("SELECT value FROM control WHERE key=?", (HOLD_KEY,)).fetchone()
    if not row:
        return None, None
    try:
        value = json.loads(row["value"] or "{}")
    except (TypeError, ValueError):
        return row["value"], None
    return row["value"], value if isinstance(value, dict) else None


def read(conn) -> dict | None:
    return None if conn is None else _read_raw(conn)[1]


def _swap(conn, raw: str | None, hold: dict | None, value: dict) -> dict | None:
    written = dict(value, rev=int((hold or {}).get("rev") or 0) + 1)
    text = json.dumps(written, sort_keys=True)
    if raw is None:
        cursor = conn.execute("INSERT INTO control(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING",
                              (HOLD_KEY, text))
    else:
        cursor = conn.execute("UPDATE control SET value=? WHERE key=? AND value=?", (text, HOLD_KEY, raw))
    return written if cursor.rowcount else None


def _event(conn, topic: str, hold: dict, **extra) -> None:
    payload = {k: hold.get(k) for k in ("job_id", "campaign_id", "n", "requested_bytes", "since_utc")}
    conn.execute("INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                 (topic, json.dumps(dict(payload, contract=MEMORY_HOLD_CONTRACT, **extra)), _stamp(time.time())))


def _holding(hold: dict | None, now: float) -> bool:
    return bool(hold) and hold.get("state") == "holding" and now < float(hold.get("until_epoch") or 0)


def _ran_out(conn, raw: str | None, hold: dict, now: float) -> None:
    run_outs = int(hold.get("run_outs") or 0) + 1
    rest_until = now + rest_seconds(run_outs)
    if _swap(conn, raw, hold, dict(hold, state="rested", ended="ran out", ended_utc=_stamp(now), run_outs=run_outs,
                                   rest_until_epoch=rest_until)):
        _event(conn, "memory_hold_ended", hold, why="ran out", run_outs=run_outs, rest_until_utc=_stamp(rest_until))


def _ended(conn, raw: str | None, hold: dict, why: str, now: float, unfit: dict | None = None) -> None:
    ended = dict(hold, state="ended", ended=why, ended_utc=_stamp(now))
    if why == "admitted":
        ended["run_outs"] = 0
    if unfit is not None:
        ended["unfit"] = unfit
    if _swap(conn, raw, hold, ended):
        _event(conn, "memory_hold_ended", hold, why=why,
               **({"reach_bytes": unfit["reach_bytes"]} if unfit is not None else {}))


def seed_state(conn, job_id: str) -> str:
    from graph_scale_dynamics.db.lane_yield import PARKED_FROM
    from graph_scale_dynamics.db.repo import candidate_may_run_job
    row = conn.execute(
        "SELECT j.status,j.memory_reservation_bytes,j.next_attempt_utc,c.status campaign_status,"
        "c.workers_target,cc.state FROM jobs j JOIN campaigns c ON c.campaign_id=j.campaign_id JOIN "
        "campaign_candidates cc ON cc.campaign_id=j.campaign_id AND cc.candidate_id=j.candidate_id WHERE j.job_id=?",
        (str(job_id),)).fetchone()
    if (row is None or row["campaign_status"] != "active" or row["workers_target"] == 0
            or not candidate_may_run_job(str(row["state"]))):
        return "gone"
    if row["status"] == "queued":
        return "gone" if str(row["next_attempt_utc"] or "") >= PARKED_FROM else "waiting"
    if row["status"] == "leased":
        return "admitted" if int(row["memory_reservation_bytes"] or 0) > 0 else "waiting"
    return "gone"


def active(conn, *, now: float | None = None) -> dict | None:
    if conn is None:
        return None
    raw, hold = _read_raw(conn)
    if not hold or hold.get("state") != "holding":
        return None
    now = time.time() if now is None else float(now)
    if not _holding(hold, now):
        _ran_out(conn, raw, hold, now)
        return None
    state = seed_state(conn, hold["job_id"])
    if state != "waiting":
        _ended(conn, raw, hold, "admitted" if state == "admitted" else "not waiting", now)
        return None
    return hold


def start(conn, *, job_id: str, campaign_id: str, n: int, requested_bytes: int,
          reach=None, now: float | None = None) -> dict | None:
    now = time.time() if now is None else float(now)
    raw, hold = _read_raw(conn)
    if _holding(hold, now):
        if str(hold.get("job_id")) != str(job_id):
            return None
        room = _out_of_reach(reach, requested_bytes)
        if room is not None:
            _ended(conn, raw, hold, "cannot fit", now, _unfit(job_id, campaign_id, n, requested_bytes, room, now))
            return None
        if int(requested_bytes) <= int(hold.get("requested_bytes") or 0):
            return hold
        return _swap(conn, raw, hold, dict(hold, requested_bytes=int(requested_bytes)))
    if hold and hold.get("state") == "holding":
        _ran_out(conn, raw, hold, now)
        return None
    if hold and hold.get("state") == "rested" and now < float(hold.get("rest_until_epoch") or 0):
        return None
    room = _out_of_reach(reach, requested_bytes)
    if room is not None:
        _note_unfit(conn, raw, hold, _unfit(job_id, campaign_id, n, requested_bytes, room, now), now)
        return None
    if (hold and str(hold.get("job_id")) == str(job_id) and hold.get("state") == "ended"
            and now < float(hold.get("until_epoch") or 0)):
        resumed = {k: v for k, v in hold.items() if k not in ("ended", "ended_utc", "unfit")}
        resumed.update(state="holding", requested_bytes=max(int(hold.get("requested_bytes") or 0),
                                                            int(requested_bytes)))
        written = _swap(conn, raw, hold, resumed)
        if written is not None:
            _event(conn, "memory_hold_started", written, until_utc=_stamp(float(written["until_epoch"])),
                   resumed=True)
        return written
    value = {"contract": MEMORY_HOLD_CONTRACT, "state": "holding", "job_id": str(job_id),
             "campaign_id": str(campaign_id), "n": int(n), "requested_bytes": int(requested_bytes),
             "since_epoch": now, "since_utc": _stamp(now), "until_epoch": now + HOLD_MAX_SECONDS,
             "run_outs": int((hold or {}).get("run_outs") or 0)}
    written = _swap(conn, raw, hold, value)
    if written is None:
        return None
    _event(conn, "memory_hold_started", written, until_utc=_stamp(written["until_epoch"]))
    return dict(written, new=True)


def end(conn, job_id: str, why: str, *, now: float | None = None) -> None:
    raw, hold = _read_raw(conn)
    if hold and hold.get("state") == "holding" and str(hold.get("job_id")) == str(job_id):
        _ended(conn, raw, hold, str(why), time.time() if now is None else float(now))


def held_bytes(conn, *, job_id: str | None = None, now: float | None = None) -> int:
    hold = read(conn)
    if not _holding(hold, time.time() if now is None else float(now)):
        return 0
    if job_id is not None and str(job_id) == str(hold.get("job_id")):
        return 0
    if seed_state(conn, hold["job_id"]) != "waiting":
        return 0
    return max(0, int(hold.get("requested_bytes") or 0))


def reading(conn, *, limit: int = 500) -> dict:
    record = {"contract": MEMORY_HOLD_CONTRACT, "now": None, "events": [], "started": 0, "resumed": 0,
              "ended_by_why": {}, "held_seconds": 0.0}
    try:
        record["now"] = read(conn)
        rows = conn.execute("SELECT created_utc,topic,payload_json FROM events WHERE topic IN "
                            "('memory_hold_started','memory_hold_ended') ORDER BY event_id DESC LIMIT ?",
                            (int(limit),)).fetchall()
    except Exception as exc:  # noqa: BLE001
        record["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return record
    since: dict = {}
    for row in reversed(rows):
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        event = {"created_utc": row["created_utc"], "topic": row["topic"],
                 **{k: payload.get(k) for k in ("job_id", "campaign_id", "n", "requested_bytes", "since_utc",
                                                 "until_utc", "why", "resumed", "run_outs", "rest_until_utc",
                                                 "reach_bytes")
                    if payload.get(k) is not None}}
        record["events"].append(event)
        stamp = _epoch(row["created_utc"])
        if row["topic"] == "memory_hold_started":
            record["resumed" if payload.get("resumed") else "started"] += 1
            since[str(payload.get("job_id"))] = stamp
        else:
            why = str(payload.get("why") or "unrecorded")
            record["ended_by_why"][why] = record["ended_by_why"].get(why, 0) + 1
            begun = since.pop(str(payload.get("job_id")), None)
            if begun is not None and stamp is not None:
                record["held_seconds"] += max(0.0, stamp - begun)
    record["events"].reverse()
    record["held_seconds"] = round(record["held_seconds"], 1)
    record["reading"] = ("One hold at a time, folder-wide: `now` is the row as it stands (holding, ended or rested "
                         "after a hold ran out; its `unfit` is the last seed refused a hold because its ask passed "
                         "`reach_bytes`, available + running children's PSS + what the scratch relief may move - "
                         "the floor); `events` its starts and ends, newest first (the last "
                         f"{int(limit)}); held_seconds sums each start to its end among them.")
    return record


def _epoch(stamp) -> float | None:
    try:
        import calendar
        return float(calendar.timegm(time.strptime(str(stamp)[:19], "%Y-%m-%dT%H:%M:%S")))
    except (TypeError, ValueError):
        return None
