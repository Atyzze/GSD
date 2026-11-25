from __future__ import annotations

from graph_scale_dynamics.observability import law_status

CONTRACT = "gsd-selection-ladder-1"
FIELDS = ("campaign_id", "candidate_id", "rungs", "word", "rule", "at_n", "next_n", "score", "score_n")
UNDER_WAY, WAITING, SETTLED, NOT_RUN = "under way", "waiting", "settled", "not started"


def _word(status: dict) -> str:
    word = str(status.get("word") or "")
    if word == law_status.RUNNING:
        return UNDER_WAY
    if word == law_status.WAITING:
        return WAITING
    if word.startswith(law_status.SETTLED):
        return SETTLED
    return NOT_RUN


def fact(campaign_id, candidate_id, rungs, row: dict, law_score: dict | None) -> list:
    status = law_status.of_row(dict(row, top_n=max(rungs) if rungs else None))
    score = law_score or {}
    return [str(campaign_id), str(candidate_id), sorted({int(n) for n in rungs}), _word(status), status.get("rule"),
            status.get("at_n"), (row.get("decision") or {}).get("next_n", row.get("next_n")),
            int(score.get("score") or 0), None if score.get("top_n") is None else int(score["top_n"])]


def facts(repo, campaign_ids) -> list[list]:
    from graph_scale_dynamics.observability import score_board
    from graph_scale_dynamics.reporting import study_tables
    out = []
    for cid in campaign_ids:
        cid = str(cid)
        rungs: dict[str, set] = {}
        version = repo.campaign_analysis_contract(cid)
        for row in repo.conn.execute(
                "SELECT DISTINCT candidate_id,n FROM rung_summaries WHERE campaign_id=? AND analysis_version=?",
                (cid, version)).fetchall():
            rungs.setdefault(str(row["candidate_id"]), set()).add(int(row["n"]))
        board = score_board.board(repo, cid)
        for row in repo.conn.execute(
                "SELECT c.candidate_id,c.state,c.state_reason,d.rule,d.action,d.at_n,d.next_n "
                "FROM campaign_candidates c LEFT JOIN engine_decisions_latest d "
                "ON d.campaign_id=c.campaign_id AND d.candidate_id=c.candidate_id "
                "WHERE c.campaign_id=? ORDER BY c.candidate_id", (cid,)).fetchall():
            law = str(row["candidate_id"])
            held = sorted(rungs.get(law, ()))
            decision = {"rule": row["rule"], "action": row["action"], "at_n": row["at_n"], "next_n": row["next_n"]}
            out.append(fact(cid, law, held, {"state": row["state"], "state_reason": row["state_reason"],
                                              "decision": decision},
                            study_tables.law_score_of(board, law, max(held) if held else None)))
    return out


def facts_of_rows(rows) -> list[list]:
    return [fact(row["campaign_id"], row["candidate_id"], row.get("rungs") or [], row, row.get("law_score"))
            for row in rows]


def ladder(found, keep=None) -> list[dict]:
    by: dict[int, dict] = {}

    def at(n) -> dict:
        return by.setdefault(int(n), {"n": int(n), "laws": 0, "under_way": 0, "settled": {}, "waiting": 0,
                                      "scoring": 0})

    for row in found:
        if keep is not None and (row[0], row[1]) not in keep:
            continue
        _c, _law, rungs, word, rule, at_n, next_n, score, score_n = row
        for n in rungs:
            at(n)["laws"] += 1
        if word == UNDER_WAY and next_n is not None:
            at(next_n)["under_way"] += 1
        elif word == SETTLED and at_n is not None:
            settled = at(at_n)["settled"]
            settled[rule or "a condition"] = settled.get(rule or "a condition", 0) + 1
        elif word == WAITING and at_n is not None:
            at(at_n)["waiting"] += 1
        if score > 0 and score_n is not None:
            at(score_n)["scoring"] += 1
    return [by[n] for n in sorted(by)]


__all__ = ["CONTRACT", "FIELDS", "facts", "facts_of_rows", "fact", "ladder"]
