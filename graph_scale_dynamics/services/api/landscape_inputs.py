from __future__ import annotations

import json
import os
from pathlib import Path

from graph_scale_dynamics.domain.model import content_hash
from graph_scale_dynamics.observability.score_board import FLAG_PREFIX as SCORES_PREFIX

CONTRACT = "gsd-landscape-inputs-1"
TABLES = ("campaign_candidates", "campaigns", "candidate_specs", "engine_decisions", "engine_decisions_latest",
          "four_rung_phenotypes", "jobs", "measurements", "proposal_exposures", "rung_summaries")
WRITES_SQL = ("SELECT relname,n_tup_ins,n_tup_upd,n_tup_del FROM pg_stat_user_tables "
              "WHERE schemaname=current_schema() AND relname=ANY(?) ORDER BY relname")
SCORES_SQL = ("SELECT md5(string_agg(key || '=' || md5(value), ',' ORDER BY key)) AS digest FROM control "
              "WHERE key LIKE ?")


def stamp(conn) -> str:
    writes = [[str(row["relname"]), int(row["n_tup_ins"]), int(row["n_tup_upd"]), int(row["n_tup_del"])]
              for row in conn.execute(WRITES_SQL, (list(TABLES),)).fetchall()]
    scores = conn.execute(SCORES_SQL, (SCORES_PREFIX + "%",)).fetchone()
    return content_hash({"contract": CONTRACT, "writes": writes,
                         "scores": dict(scores).get("digest") if scores else None})[:20]


def read_now(open_repo, slots, note) -> str | None:
    if not slots.acquire(timeout=2.0):
        return None
    repo = None
    try:
        repo = open_repo()
        return stamp(repo.conn)
    except Exception as exc:  # noqa: BLE001
        note("landscape inputs", exc)
        return None
    finally:
        if repo is not None:
            repo.close()
        slots.release()


def recorded(meta_path: Path) -> str | None:
    try:
        found = json.loads(Path(meta_path).read_text(encoding="utf-8")).get("inputs")
    except (OSError, ValueError, AttributeError):
        return None
    return str(found) if found else None


def kept(inputs: str | None, body_path: Path, meta_path: Path) -> bool:
    if inputs is None or not Path(body_path).is_file() or recorded(meta_path) != inputs:
        return False
    try:
        os.utime(body_path)
    except OSError:
        return False
    return True


def argv(inputs: str | None) -> list[str]:
    return ["--inputs", inputs] if inputs else []
