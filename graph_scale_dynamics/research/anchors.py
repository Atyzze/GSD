from __future__ import annotations

import json
import math

from graph_scale_dynamics.domain.model import utc_now

ANCHOR_CONTRACT = "anchor-1"
KEY_PREFIX = "anchor:"
STATUSES = ("watching", "probe_around", "marker")
DEFAULT_STATUS = "watching"
READING_KEYS = ("mean_degree", "connected_fraction", "d_s", "d_V", "d_B", "d_w",
                "degree_heterogeneity", "clustering")


def _mean(summary: dict, key: str):
    node = (summary or {}).get(key)
    value = node.get("mean") if isinstance(node, dict) else node
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def reading(n: int, summary: dict) -> dict:
    row = {"n": int(n)}
    for key in READING_KEYS:
        row[key] = _mean(summary, key)
    census = (summary or {}).get("census") or {}
    row["spectral_gap"] = _mean(census, "spectral_gap")
    row["diameter"] = _mean(census, "largest_component_diameter")
    return row


def make_anchor(*, candidate_id: str, campaign_id: str | None, spec: dict | None,
                readings: list[dict], reason: dict, origin: dict | None = None,
                status: str = DEFAULT_STATUS, note: str = "") -> dict:
    now = utc_now()
    return {"contract": ANCHOR_CONTRACT, "candidate_id": str(candidate_id),
            "campaign_id": campaign_id, "origin": dict(origin or {}),
            "spec": spec, "spec_complete": bool(spec) and "beta" in ((spec or {}).get("dynamics") or {}),
            "readings": sorted(readings, key=lambda r: r["n"]), "reason": reason,
            "status": status if status in STATUSES else DEFAULT_STATUS, "note": str(note or ""),
            "created_utc": now, "updated_utc": now}


def get(repo, candidate_id: str) -> dict | None:
    row = repo.conn.execute("SELECT document FROM anchors WHERE candidate_id=?", (str(candidate_id),)).fetchone()
    return json.loads(row["document"]) if row else None


def put(repo, anchor: dict) -> None:
    repo._write(
        "INSERT INTO anchors(candidate_id,campaign_id,status,document,created_utc,updated_utc) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET campaign_id=excluded.campaign_id, "
        "status=excluded.status, document=excluded.document, updated_utc=excluded.updated_utc",
        (str(anchor["candidate_id"]), anchor.get("campaign_id"), str(anchor.get("status") or DEFAULT_STATUS),
         json.dumps(anchor, sort_keys=True), str(anchor.get("created_utc") or utc_now()),
         str(anchor.get("updated_utc") or utc_now())))


def listing(repo) -> list[dict]:
    rows = repo.conn.execute("SELECT document FROM anchors ORDER BY created_utc DESC, candidate_id").fetchall()
    anchors = []
    for row in rows:
        try:
            anchors.append(json.loads(row["document"]))
        except (TypeError, ValueError):
            continue
    return anchors


def law_readings(conn, campaign_id: str, candidate_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT n, summary_json, analysis_version FROM rung_summaries WHERE campaign_id=? "
        "AND candidate_id=? ORDER BY analysis_version DESC, n", (str(campaign_id), str(candidate_id))).fetchall()
    newest = rows[0]["analysis_version"] if rows else None
    return [reading(int(r["n"]), json.loads(r["summary_json"]))
            for r in rows if r["analysis_version"] == newest]


def law_spec(conn, campaign_id: str, candidate_id: str) -> dict | None:
    row = conn.execute("SELECT spec_json FROM candidates WHERE campaign_id=? AND candidate_id=?",
                       (str(campaign_id), str(candidate_id))).fetchone()
    return json.loads(row["spec_json"]) if row else None
