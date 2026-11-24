from __future__ import annotations

import os
import re
import time
from pathlib import Path

from graph_scale_dynamics.domain.model import utc_now

SCRATCH_RELIEF_CONTRACT = "gsd-scratch-relief-1"
HIGH_WATER = 0.60
LOW_WATER = 0.40
CLAIM_RESERVE_FRACTION = 0.10
CLAIM_RESERVE_FLOOR_BYTES = 2 << 30
ANALYSIS_RESERVE_BYTES = 256 << 20
TICK_BUDGET_BYTES = 4 << 30
DISK_KEEP_FREE_BYTES = 20 << 30
PROGRESS_BYTES = 2 << 30
SAVED_STATE_MIN_AGE_SECONDS = 600.0
SHORT_SECONDS = 300.0
KINDS =("resume_checkpoint", "raw_not_analysed", "raw_waiting", "saved_state")
WORDS = {"resume_checkpoint": "saved chain copies", "raw_not_analysed": "results nothing will analyse",
         "raw_waiting": "results waiting for analysis", "saved_state": "saved states of stopped chains"}

_ROOM: dict[str, tuple[float, dict | None]] = {}
_ROOM_SECONDS = 1.0
_PID_LOG = re.compile(r"^.+-(\d+)\.jsonl(\.\d+)?$")


def gib(value) -> str:
    return f"{max(0, int(value or 0)) / (1 << 30):.1f} GiB"


def usage(path) -> dict | None:
    try:
        stat = os.statvfs(str(path))
    except OSError:
        return None
    total = int(stat.f_blocks) * int(stat.f_frsize)
    free = int(stat.f_bavail) * int(stat.f_frsize)
    used = total - int(stat.f_bfree) * int(stat.f_frsize)
    return {"total_bytes": total, "used_bytes": used, "free_bytes": free,
            "fraction": (used / total) if total > 0 else 0.0}


def reserve_bytes(total: int, kind: str) -> int:
    want = (max(CLAIM_RESERVE_FLOOR_BYTES, int(CLAIM_RESERVE_FRACTION * total)) if kind == "simulation"
            else ANALYSIS_RESERVE_BYTES)
    return min(want, max(0, int(total) // 2))


def room(path, *, kind: str = "simulation") -> tuple[bool, str | None]:
    key = str(path)
    now = time.monotonic()
    cached = _ROOM.get(key)
    if cached is None or now - cached[0] >= _ROOM_SECONDS:
        cached = (now, usage(path))
        _ROOM[key] = cached
    seen = cached[1]
    if not seen or not seen["total_bytes"]:
        return True, None
    need = reserve_bytes(seen["total_bytes"], kind)
    if seen["free_bytes"] >= need:
        return True, None
    return False, (f"the RAM scratch has {gib(seen['free_bytes'])} free of {gib(seen['total_bytes'])}, "
                   f"under the {gib(need)} a new {kind} needs")


_WHERE = {
    "resume_checkpoint": "ar.storage_class='resume_checkpoint'",
    "raw_not_analysed": ("ar.storage_class='raw_simulation' AND NOT EXISTS (SELECT 1 FROM analysis_queue q "
                         "WHERE q.input_artifact=ar.artifact_hash AND q.status IN ('queued','leased','done'))"),
    "raw_waiting": ("ar.storage_class='raw_simulation' AND EXISTS (SELECT 1 FROM analysis_queue q "
                    "WHERE q.input_artifact=ar.artifact_hash AND q.status='queued') AND NOT EXISTS ("
                    "SELECT 1 FROM analysis_queue q WHERE q.input_artifact=ar.artifact_hash AND q.status='done')"),
}


def _candidates(repo, kind: str, limit: int, after: tuple[int, str] | None = None) -> list[dict]:
    if kind not in _WHERE:
        raise ValueError(kind)
    where = _WHERE[kind]
    cursor, args = "", ()
    if after is not None:
        cursor = " AND (a.size_bytes < ? OR (a.size_bytes = ? AND ar.artifact_hash > ?))"
        args = (int(after[0]), int(after[0]), str(after[1]))
    rows = repo.conn.execute(
        "SELECT ar.artifact_hash,a.size_bytes FROM artifact_retention ar JOIN artifacts a "
        f"ON a.artifact_hash=ar.artifact_hash WHERE ar.body_state='transient' AND {where}{cursor} "
        "ORDER BY a.size_bytes DESC,ar.artifact_hash LIMIT ?", (*args, int(limit))).fetchall()
    return [{"digest": str(row["artifact_hash"]), "size": int(row["size_bytes"] or 0)} for row in rows]


def _mark_spilled(repo, digest: str) -> bool:
    import json
    row = repo.conn.execute("SELECT detail_json FROM artifact_retention WHERE artifact_hash=? "
                            "AND body_state='transient'", (digest,)).fetchone()
    if row is None:
        return False
    try:
        detail = json.loads(row["detail_json"] or "{}")
    except ValueError:
        detail = {}
    detail = dict(detail if isinstance(detail, dict) else {}, storage_tier="durable",
                  spilled_from_ram_utc=utc_now(), spilled_by=SCRATCH_RELIEF_CONTRACT)
    repo.begin_transaction(attempts=12)
    try:
        moved = repo._write("UPDATE artifact_retention SET body_state='present',detail_json=?,updated_utc=? "
                            "WHERE artifact_hash=? AND body_state='transient'",
                            (json.dumps(detail, sort_keys=True), utc_now(), digest))
        repo.commit_durably()
    except Exception:
        repo.conn.rollback_if_open()
        raise
    return moved


def _spill_blob(repo, store, digest: str, phantoms: dict | None = None) -> int:
    moved = store.spill_transient(digest)
    if not moved:
        if store.verify_durable(digest) and _mark_spilled(repo, digest):
            if phantoms is not None:
                phantoms["durable"] = phantoms.get("durable", 0) + 1
        elif phantoms is not None:
            phantoms["lost"] = phantoms.get("lost", 0) + 1
        return 0
    if not _mark_spilled(repo, digest):
        return 0
    store.delete_transient(digest)
    return moved


def _saved_states(repo, store) -> list[dict]:
    directory = Path(store.volatile_root) / "resume"
    if not directory.is_dir():
        return []
    clock = time.time()
    files = []
    for entry in directory.iterdir():
        if not entry.name.endswith(".json.gz") or not entry.is_file():
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        if clock - stat.st_mtime >= SAVED_STATE_MIN_AGE_SECONDS:
            files.append({"path": entry, "job": entry.name[:-len(".json.gz")], "size": int(stat.st_size)})
    if not files:
        return []
    leased = {str(row["job_id"]) for row in repo.conn.execute(
        "SELECT job_id FROM jobs WHERE status='leased' AND job_id IN (" + ",".join("?" for _ in files) + ")",
        tuple(f["job"] for f in files)).fetchall()}
    return sorted((f for f in files if f["job"] not in leased), key=lambda f: -f["size"])


def disk_free(store) -> int | None:
    import shutil
    try:
        return int(shutil.disk_usage(Path(store.root)).free)
    except OSError:
        return None


def disk_room(store, size: int) -> bool:
    free = disk_free(store)
    return free is not None and free >= int(size) + DISK_KEEP_FREE_BYTES


def _spill_state(store, entry: dict) -> int:
    import shutil
    from graph_scale_dynamics.artifact_store.resume_state import resume_note_path
    source = Path(entry["path"])
    target = Path(store.root) / "resume" / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not disk_room(store, int(entry["size"])):
        raise OSError(f"no room on the disk root for a saved state of {int(entry['size']):,} bytes")
    for src, dst in ((source, target), (resume_note_path(source), resume_note_path(target))):
        if not src.exists():
            continue
        temporary = dst.with_name(dst.name + f".{os.getpid()}.spill")
        try:
            shutil.copyfile(src, temporary)
            with temporary.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary, dst)
        finally:
            temporary.unlink(missing_ok=True)
    for src in (source, resume_note_path(source)):
        src.unlink(missing_ok=True)
    return int(entry["size"])


def spill(repo, store, *, target_fraction: float = LOW_WATER, budget_bytes: int | None = None,
          batch: int = 64, progress=None) -> dict:
    root = Path(store.volatile_root)
    before = usage(root)
    moved = {kind: {"items": 0, "bytes": 0} for kind in KINDS}
    refused: dict[str, int] = {}
    spent = 0
    reported = 0

    def done() -> bool:
        now = usage(root)
        return (now is None or now["fraction"] <= target_fraction
                or (budget_bytes is not None and spent >= budget_bytes))

    phantoms: dict = {}
    floor = None
    for kind in KINDS:
        after = None
        while floor is None and not done():
            entries = (_saved_states(repo, store) if kind == "saved_state"
                       else _candidates(repo, kind, batch, after=after))
            if not entries:
                break
            if kind != "saved_state":
                after = (entries[-1]["size"], entries[-1]["digest"])
            progressed = False
            for entry in entries[:batch]:
                if done():
                    break
                if not disk_room(store, int(entry.get("size") or 0)):
                    refused["disk_floor"] = refused.get("disk_floor", 0) + 1
                    floor = {"free_bytes": disk_free(store), "keep_free_bytes": DISK_KEEP_FREE_BYTES}
                    break
                try:
                    size = _spill_state(store, entry) if kind == "saved_state" else _spill_blob(
                        repo, store, entry["digest"], phantoms)
                except (OSError, ValueError) as exc:
                    refused[type(exc).__name__] = refused.get(type(exc).__name__, 0) + 1
                    continue
                if size:
                    progressed = True
                    moved[kind]["items"] += 1
                    moved[kind]["bytes"] += size
                    spent += size
                    if progress is not None and spent - reported >= PROGRESS_BYTES:
                        reported = spent
                        progress(spent)
            if not progressed and kind == "saved_state":
                break
    return {"contract": SCRATCH_RELIEF_CONTRACT, "before": before, "after": usage(root),
            "moved": {k: v for k, v in moved.items() if v["items"]}, "moved_bytes": spent,
            "refused": refused, "bodies_not_in_ram": phantoms, "target_fraction": target_fraction,
            **({"disk_floor": floor} if floor else {})}


DEAD_LOG_KEEP_SECONDS = 6 * 3600.0


def prune_dead_logs(log_dir, *, keep_seconds: float = DEAD_LOG_KEEP_SECONDS) -> dict:
    removed, freed = 0, 0
    directory = Path(log_dir)
    if not directory.is_dir():
        return {"removed": 0, "bytes": 0}
    clock = time.time()
    for entry in directory.iterdir():
        match = _PID_LOG.match(entry.name)
        if match is None or not entry.is_file():
            continue
        try:
            stat = entry.stat()
            if clock - stat.st_mtime < keep_seconds:
                continue
            os.kill(int(match.group(1)), 0)
            continue
        except ProcessLookupError:
            pass
        except (OSError, OverflowError, ValueError):
            continue
        try:
            entry.unlink()
        except OSError:
            continue
        removed, freed = removed + 1, freed + int(stat.st_blocks) * 512
    return {"removed": removed, "bytes": freed}


def _tree_bytes(path: Path) -> int:
    total = 0
    for current, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.lstat(os.path.join(current, name)).st_blocks * 512
            except OSError:
                continue
    return total


def breakdown(repo, store) -> dict:
    root = Path(store.volatile_root)
    parts: dict[str, int] = {}
    for row in repo.conn.execute(
            "SELECT ar.storage_class,COALESCE(SUM(a.size_bytes),0) b,COUNT(*) c FROM artifact_retention ar "
            "JOIN artifacts a ON a.artifact_hash=ar.artifact_hash WHERE ar.body_state='transient' "
            "GROUP BY ar.storage_class").fetchall():
        parts[str(row["storage_class"])] = int(row["b"] or 0)
    for name, sub in (("saved_states", "resume"), ("staging", "staging"), ("logs", "runtime/log")):
        parts[name] = _tree_bytes(root / sub) if (root / sub).exists() else 0
    runtime = _tree_bytes(root / "runtime") if (root / "runtime").exists() else 0
    parts["runtime_other"] = max(0, runtime - parts["logs"])
    seen = usage(root) or {}
    parts["everything_else"] = max(0, int(seen.get("used_bytes") or 0) - sum(parts.values()))
    return {"usage": seen, "parts": parts}


def at_fleet_start(repo, store, *, say=print, var=None) -> dict:
    from graph_scale_dynamics.operations import (
        failure_repair, queue_ranks, scratch_repair, standing_controls, stranded_laws, study)
    controls = ("study", "controls")
    repaired = True
    out: dict = {"study": None, "repair": None, "failures": None, "stranded": None, "ranks": None, "controls": None,
                 "relief": None}
    for key, step, words in (("study", study, "study: the rest of its first start was not made"),
                             ("repair", scratch_repair, "repair: not done"),
                             ("failures", failure_repair, "repair: the fleet's failures were not given back"),
                             ("stranded", stranded_laws, "repair: the laws running with no work were not looked at"),
                             ("ranks", queue_ranks, "queue: the base block's rank was not restored"),
                             ("controls", standing_controls, "controls: the standing controls were not created")):
        try:
            out[key] = step.repair(repo, var=var) if key in controls else step.repair(repo)
            for line in step.render(out[key]):
                say(line)
        except Exception as exc:  # noqa: BLE001
            repaired = False
            say(f"{words} ({type(exc).__name__}: {str(exc)[:200]}); "
                + ("nothing was changed" if key != "ranks" and key not in controls else "the next start tries again"))
    try:
        from graph_scale_dynamics.artifact_store.resume_state import prune_resume_states
        keep = {"keep": ("queued", "leased")} if repaired else {}
        for root in (store.volatile_root, store.root):
            prune_resume_states(repo.conn, root, **keep)
    except Exception as exc:  # noqa: BLE001
        say(f"scratch: saved states not pruned ({type(exc).__name__}: {str(exc)[:200]}); the next start tries again")
    try:
        seen = usage(store.volatile_root)
        described = bool(seen and seen["fraction"] > HIGH_WATER)
        if described:
            say(render({"usage": seen})[0])
            say(render_breakdown(breakdown(repo, store)))
        out["relief"] = relieve(repo, store, at_start=True,
                                progress=lambda moved: say(f"scratch: {gib(moved)} moved to disk so far"))
        for line in render(out["relief"], destination=str(Path(store.root) / "blobs"))[1 if described else 0:]:
            say(line)
    except Exception as exc:  # noqa: BLE001
        say(f"scratch: the relief stopped ({type(exc).__name__}: {str(exc)[:200]}); maintenance goes on with it")
    return out


PART_WORDS = {"resume_checkpoint": "saved chain copies", "raw_simulation": "results not yet analysed or evicted",
              "saved_states": "saved states of stopped chains", "staging": "staging", "logs": "service logs",
              "runtime_other": "other runtime files", "everything_else": "everything else (report snapshots, the "
              "database's temporary files, bodies no row names)"}


def render_breakdown(found: dict) -> str:
    parts = sorted(((k, v) for k, v in (found.get("parts") or {}).items() if v), key=lambda kv: -kv[1])
    return "scratch holds: " + (", ".join(f"{PART_WORDS.get(k, k)} {gib(v)}" for k, v in parts) or "nothing")


def tmpfs(store) -> bool:
    return bool((getattr(store, "staging_backend", None) or {}).get("tmpfs"))


def shortage(conn, deferred_at: float | None = None, *, now: float | None = None) -> dict:
    from graph_scale_dynamics.scheduling import memory_hold
    from graph_scale_dynamics.scheduling.memory import memory_deferred_simulations
    clock = time.time() if now is None else float(now)
    hold = memory_hold.read(conn) or {}
    if memory_deferred_simulations(conn):
        deferred_at = clock
    why = None
    if hold.get("state") == "holding" and clock < float(hold.get("until_epoch") or 0):
        why = f"a hold for a {int(hold.get('n') or 0):,} seed asking {gib(hold.get('requested_bytes'))}"
    elif deferred_at is not None and clock - float(deferred_at) <= SHORT_SECONDS:
        why = f"seeds refused for memory {int(clock - float(deferred_at))} s ago"
    return {"why": why, "deferred_at": deferred_at}


def spillable_bytes(repo, store) -> int:
    row = repo.conn.execute(
        "SELECT COALESCE(SUM(a.size_bytes),0) b FROM artifact_retention ar JOIN artifacts a "
        "ON a.artifact_hash=ar.artifact_hash WHERE ar.body_state='transient' AND ("
        + " OR ".join(f"({where})" for where in _WHERE.values()) + ")").fetchone()
    return int(row["b"] or 0) + sum(int(entry["size"]) for entry in _saved_states(repo, store))


def movable_bytes(repo, store, seen: dict | None) -> int:
    if not seen or not seen.get("total_bytes") or not tmpfs(store):
        return 0
    above = int(seen["used_bytes"]) - int(LOW_WATER * int(seen["total_bytes"]))
    free = disk_free(store)
    if above <= 0 or free is None or free <= DISK_KEEP_FREE_BYTES:
        return 0
    return max(0, min(above, free - DISK_KEEP_FREE_BYTES, spillable_bytes(repo, store)))


def doing(result: dict) -> str:
    seen = result.get("after") or result.get("usage") or {}
    moved = int((result.get("spilled") or {}).get("moved_bytes") or 0)
    pressed = result.get("pressed")
    floor = (result.get("spilled") or {}).get("disk_floor") or result.get("disk_floor")
    if not seen:
        return "the scratch is not readable here"
    if not result.get("tmpfs"):
        return "the scratch is not a tmpfs: moving it frees no RAM, so the relief keeps to its high mark"
    because = f", because admission is short ({pressed})" if pressed else ""
    if moved:
        return f"moved {gib(moved)} to disk this tick, toward {LOW_WATER:.0%}{because}"
    if floor:
        return (f"moves nothing: the disk has {gib(floor['free_bytes'] or 0)} free, under the "
                f"{gib(DISK_KEEP_FREE_BYTES)} kept for PostgreSQL")
    if float(seen.get("fraction") or 0.0) <= LOW_WATER:
        return f"moves nothing: under {LOW_WATER:.0%}{because}"
    if result.get("spilled") is not None:
        return f"moves nothing: nothing of the kinds it moves is left in RAM{because}"
    return (f"waits: under {HIGH_WATER:.0%} and admission is not short (no hold, no seed refused for memory in "
            f"the last {int(SHORT_SECONDS // 60)} minutes)")


def publish(repo, store, result: dict, *, now: float | None = None) -> dict:
    import json
    from graph_scale_dynamics.scheduling.memory_hold import SCRATCH_KEY
    clock = time.time() if now is None else float(now)
    seen = result.get("after") or result.get("usage") or {}
    row = {"contract": SCRATCH_RELIEF_CONTRACT, "at_epoch": clock, "at_utc": utc_now(), "tmpfs": tmpfs(store),
           "used_bytes": seen.get("used_bytes"), "total_bytes": seen.get("total_bytes"),
           "fraction": round(float(seen.get("fraction") or 0.0), 3),
           "moved_bytes": int((result.get("spilled") or {}).get("moved_bytes") or 0),
           "movable_bytes": movable_bytes(repo, store, seen), "pressed": result.get("pressed"),
           "relieving": bool(result.get("relieving")), "doing": doing(result)}
    repo.set_flag(SCRATCH_KEY, json.dumps(row, sort_keys=True))
    return row


def relieve(repo, store, *, at_start: bool = False, progress=None, relieving: bool = False,
            pressed: str | None = None) -> dict:
    root = Path(store.volatile_root)
    seen = usage(root)
    short = bool(pressed) and tmpfs(store)
    result = {"contract": SCRATCH_RELIEF_CONTRACT, "usage": seen, "spilled": None, "logs": None,
              "relieving": False, "tmpfs": tmpfs(store), "pressed": pressed if short else None}
    if seen is None:
        return result
    if at_start or seen["fraction"] > HIGH_WATER:
        result["logs"] = prune_dead_logs(root / "runtime" / "log")
    if (usage(root) or seen)["fraction"] > (LOW_WATER if (at_start or relieving or short) else HIGH_WATER):
        result["spilled"] = spill(repo, store, target_fraction=LOW_WATER,
                                  budget_bytes=None if at_start else TICK_BUDGET_BYTES, progress=progress)
        spilled = result["spilled"]
        result["relieving"] = bool(spilled["moved_bytes"]) and ((spilled.get("after") or {}).get(
            "fraction", 0.0) > LOW_WATER)
    result["after"] = usage(root)
    if not disk_room(store, 0):
        result["disk_floor"] = {"free_bytes": disk_free(store), "keep_free_bytes": DISK_KEEP_FREE_BYTES}
    return result


def brief(result: dict) -> dict:
    after = result.get("after") or result.get("usage") or {}
    spilled = result.get("spilled") or {}
    return {"used_bytes": after.get("used_bytes"), "total_bytes": after.get("total_bytes"),
            "fraction": round(float(after.get("fraction") or 0.0), 3),
            "moved_bytes": int(spilled.get("moved_bytes") or 0),
            "moved": {k: v["items"] for k, v in (spilled.get("moved") or {}).items()},
            "refused": spilled.get("refused") or {}, "logs_removed": int((result.get("logs") or {}).get("removed") or 0),
            "pressed": result.get("pressed")}


def findings(result: dict) -> list[dict]:
    after = result.get("after") or result.get("usage")
    if not after or not after.get("total_bytes"):
        return []
    floor = (result.get("spilled") or {}).get("disk_floor") or result.get("disk_floor")
    disk = ([{"key": "scratch:disk_floor", "severity": "error", "category": "scratch",
              "message": (f"the project disk has {gib(floor['free_bytes'] or 0)} free, under the "
                          f"{gib(floor['keep_free_bytes'])} kept for PostgreSQL: nothing more moves from the RAM "
                          "scratch to disk, so new simulations wait for room"), "detail": floor}]
            if floor else [])
    fraction = float(after["fraction"])
    detail = {"used_bytes": after["used_bytes"], "total_bytes": after["total_bytes"],
              "free_bytes": after["free_bytes"], "high_water": HIGH_WATER, "low_water": LOW_WATER}
    if after["free_bytes"] < reserve_bytes(after["total_bytes"], "simulation"):
        return disk + [{"key": "scratch:full", "severity": "error", "category": "scratch",
                        "message": (f"the RAM scratch is full ({gib(after['used_bytes'])} of "
                                    f"{gib(after['total_bytes'])}): no new simulation is claimed until the relief "
                                    "has moved enough to disk"), "detail": detail}]
    if fraction > HIGH_WATER:
        return disk + [{"key": "scratch:pressure", "severity": "warning", "category": "scratch",
                        "message": (f"the RAM scratch is {fraction:.0%} full; the relief is moving what waits "
                                    "longest to disk"), "detail": detail}]
    return disk


def render(result: dict, *, destination: str = "") -> list[str]:
    seen = result.get("usage")
    if not seen:
        return ["scratch: not readable here; the relief did nothing"]
    lines = [f"scratch: {gib(seen['used_bytes'])} of {gib(seen['total_bytes'])} in use ({seen['fraction']:.0%})"]
    logs = result.get("logs") or {}
    if logs.get("removed"):
        lines.append(f"scratch: removed {logs['removed']} log file(s) of ended processes ({gib(logs['bytes'])})")
    spilled = result.get("spilled")
    if spilled and spilled.get("moved"):
        parts = ", ".join(f"{v['items']:,} {WORDS[k]} ({gib(v['bytes'])})" for k, v in spilled["moved"].items())
        lines.append(f"scratch: moved to disk{(' ' + destination) if destination else ''}: {parts}")
    if spilled and spilled.get("refused"):
        lines.append(f"scratch: not moved: {spilled['refused']}")
    if spilled and spilled.get("disk_floor"):
        floor = spilled["disk_floor"]
        lines.append(f"scratch: the disk has {gib(floor['free_bytes'] or 0)} free, under the "
                     f"{gib(floor['keep_free_bytes'])} kept for PostgreSQL: stopped moving")
    after = result.get("after") or seen
    if after is not seen:
        lines.append(f"scratch: now {gib(after['used_bytes'])} ({after['fraction']:.0%}); the relief keeps it under "
                     f"{HIGH_WATER:.0%} while the fleet runs")
    return lines
