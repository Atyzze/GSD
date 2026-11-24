from __future__ import annotations

from typing import Iterable, Sequence

RECOVERY_CONTRACT = "gsd-lifecycle-recovery-1"


DECISION_WAIT_ALERT_SECONDS = 600.0


LEARNING_TEXT = ("A law decides at a size once no law numbered before it can still change what it learns there (834): "
                 "a gate's share, or a known result repeats_a_known_result acts on. These wait for such laws, which own the work.")


def decision_backlog_alerts(backlog: dict, *, paused: bool, age_seconds, learning: int = 0) -> list[dict]:
    awaiting = int((backlog or {}).get("awaiting") or 0)
    since = (backlog or {}).get("oldest_since_utc")
    waited = age_seconds(since) if (awaiting and since) else 0.0
    if paused or not awaiting or waited < DECISION_WAIT_ALERT_SECONDS:
        return []
    minutes = int(waited // 60)
    if int(learning or 0) >= awaiting:
        return [{"severity": "info", "code": "DECISIONS_BEHIND",
                 "headline": f"{awaiting} law(s) wait for earlier laws to be decided, the oldest for {minutes} min",
                 "awaiting": awaiting, "learning": int(learning), "oldest_wait_seconds": round(float(waited), 1),
                 "explanation": LEARNING_TEXT, "contract": RECOVERY_CONTRACT}]
    return [{
        "severity": "warning",
        "code": "DECISIONS_BEHIND",
        "headline": f"{awaiting} law(s) await a decision, the oldest for {minutes} min",
        "awaiting": awaiting,
        "oldest_wait_seconds": round(float(waited), 1),
        "explanation": ("The controller decides a law on the pass after its rung's evidence lands, seconds apart. "
                        "Laws still waiting after ten minutes are laws it is not reaching: check the controller's "
                        "heartbeat and log. On the night of the 16th a limit hid every law behind 512 holds and "
                        "134 laws waited seven hours (462)."),
        "contract": RECOVERY_CONTRACT,
    }]


def summarize_stranded(rows: Iterable[dict], *, held: int = 0, learning: int = 0) -> dict:
    items = [dict(row or {}) for row in rows]
    by_state: dict[str, int] = {}
    for row in items:
        state = str(row.get("state") or "UNKNOWN")
        by_state[state] = by_state.get(state, 0) + 1
    held = max(0, int(held or 0))
    learning = min(len(items), max(0, int(learning or 0)))
    stranded = len(items) - learning
    beside = (f" · {held} held by the engine, waiting by design" if held else "") + (
        f" · {learning} waiting for earlier laws to be decided (pending: learning)" if learning else "")
    return {
        "contract": RECOVERY_CONTRACT,
        "stranded": stranded,
        "learning": learning,
        "held": held,
        "by_state": dict(sorted(by_state.items())),
        "headline": (f"{stranded} STRANDED · running with no queued or leased work{beside}"
                     if stranded else f"no stranded laws{beside}" if (held or learning)
                     else "no stranded scientific work"),
    }


def stranded_work_alerts(rows: Sequence[dict], codes: dict, age_seconds, learning: int = 0) -> list[dict]:
    stranded = [dict(row) for row in rows if not row.get("held")]
    held = max((int(row.get("held_total") or 0) for row in rows), default=0)
    for row in stranded:
        row["ensemble_code"] = codes.get(str(row.get("candidate_id")))
        row["candidate_state_age_seconds"] = round(age_seconds(row.get("updated_utc")), 1)
    summary = summarize_stranded(stranded, held=held, learning=learning)
    if not stranded and not held:
        return []
    return [{
        "severity": "warning" if summary["stranded"] else "info",
        "code": "STRANDED_SCIENTIFIC_WORK",
        "headline": summary["headline"],
        "stranded": summary["stranded"],
        "learning": summary["learning"],
        "held": summary["held"],
        "by_state": summary["by_state"],
        "candidates": stranded[:50],
        "explanation": (("These laws are running but own no queued or leased simulation, analysis or "
                         "evidence rebuild, and the engine is not holding them. The decider decides a law "
                         "on the controller pass after its rung's evidence lands, so a law still here after "
                         "that is not being decided: look for engine_decision_failed in the controller log. "
                         if summary["stranded"] else "")
                        + (f"{summary['learning']} of them the controller's last pass left pending: learning. "
                           + LEARNING_TEXT + " " if summary["learning"] else "")
                        + (f"{held} held law(s) own no work by design: the engine buys a held law's next rung "
                           "when the simulation queue is empty." if held else "")).strip(),
        "contract": RECOVERY_CONTRACT,
    }]
