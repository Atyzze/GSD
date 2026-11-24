#!/usr/bin/env python3
from __future__ import annotations

import gzip
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTRACT = "gsd-decision-index-1"
BATCH = 2000
COLUMNS = ("campaign_id", "candidate_id", "decision_id", "at_n", "action", "rule", "next_n")


def _number(value):
    return None if value is None else int(value)


class DecisionIndex:
    def __init__(self, root: Path, folder: Path | None = None):
        self.root = Path(root)
        self._folder = None if folder is not None else tempfile.TemporaryDirectory(prefix="gsd_decisions_")
        self.path = Path(folder if folder is not None else self._folder.name) / "decisions.sqlite"
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("PRAGMA journal_mode=OFF")
        self.conn.execute("PRAGMA synchronous=OFF")
        self.conn.execute("CREATE TABLE decisions (campaign_id TEXT, candidate_id TEXT, decision_id TEXT, at_n INTEGER, "
                          "action TEXT, rule TEXT, next_n INTEGER, row TEXT)")
        self.rows = self._fill()
        self.conn.execute("CREATE INDEX by_law ON decisions (campaign_id, candidate_id, decision_id)")
        self.conn.execute("CREATE INDEX by_size ON decisions (at_n, campaign_id, candidate_id, decision_id)")
        self.conn.execute("CREATE INDEX by_id ON decisions (campaign_id, decision_id)")
        self.conn.commit()

    def _fill(self) -> int:
        count, batch = 0, []
        with gzip.open(self.root / "tables" / "decisions.ndjson.gz", "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                batch.append((str(row.get("campaign_id")), str(row.get("candidate_id")), str(row.get("decision_id")),
                              _number(row.get("at_n")), row.get("action"), row.get("rule"),
                              _number(row.get("next_n")), line))
                if len(batch) >= BATCH:
                    self.conn.executemany("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?)", batch)
                    count += len(batch)
                    batch = []
        if batch:
            self.conn.executemany("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?)", batch)
            count += len(batch)
        return count

    def close(self) -> None:
        self.conn.close()
        if self._folder is not None:
            self._folder.cleanup()

    def __enter__(self) -> "DecisionIndex":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    @staticmethod
    def _campaigns(campaigns) -> tuple[str, list]:
        if campaigns is None:
            return "", []
        names = sorted(str(c) for c in campaigns)
        return f" AND campaign_id IN ({','.join('?' for _ in names)})", names

    def latest(self, campaigns=None, n: int | None = None):
        where, args = self._campaigns(campaigns)
        size = " AND at_n = ?" if n is not None else ""
        query = ("SELECT d.row FROM decisions d JOIN (SELECT campaign_id, candidate_id, at_n, MAX(decision_id) AS last "
                 f"FROM decisions WHERE at_n IS NOT NULL{where}{size} GROUP BY campaign_id, candidate_id, at_n) m "
                 "ON d.campaign_id = m.campaign_id AND d.candidate_id = m.candidate_id AND d.at_n = m.at_n "
                 "AND d.decision_id = m.last ORDER BY d.campaign_id, d.candidate_id, d.at_n")
        for (line,) in self.conn.execute(query, args + ([int(n)] if n is not None else [])):
            yield json.loads(line)

    def last_of_each_law(self, campaigns=None):
        where, args = self._campaigns(campaigns)
        query = ("SELECT d.row FROM decisions d JOIN (SELECT campaign_id, candidate_id, MAX(decision_id) AS last "
                 f"FROM decisions WHERE at_n IS NOT NULL{where} GROUP BY campaign_id, candidate_id) m "
                 "ON d.campaign_id = m.campaign_id AND d.candidate_id = m.candidate_id AND d.decision_id = m.last "
                 "ORDER BY d.campaign_id, d.candidate_id")
        for (line,) in self.conn.execute(query, args):
            yield json.loads(line)

    def by_law(self, campaigns=None, *, sized_only: bool = True):
        where, args = self._campaigns(campaigns)
        sized = " AND at_n IS NOT NULL" if sized_only else ""
        query = (f"SELECT campaign_id, candidate_id, row FROM decisions WHERE 1=1{where}{sized} "
                 "ORDER BY campaign_id, candidate_id, decision_id")
        key, rows = None, []
        for campaign, law, line in self.conn.execute(query, args):
            if (campaign, law) != key:
                if rows:
                    yield key, rows
                key, rows = (campaign, law), []
            rows.append(json.loads(line))
        if rows:
            yield key, rows

    def every(self, campaigns=None):
        where, args = self._campaigns(campaigns)
        for (line,) in self.conn.execute(f"SELECT row FROM decisions WHERE 1=1{where} ORDER BY decision_id", args):
            yield json.loads(line)

    def row(self, campaign_id, decision_id) -> dict | None:
        found = self.conn.execute("SELECT row FROM decisions WHERE campaign_id = ? AND decision_id = ? LIMIT 1",
                                  (str(campaign_id), str(decision_id))).fetchone()
        return json.loads(found[0]) if found else None

    def count(self, campaigns=None) -> int:
        where, args = self._campaigns(campaigns)
        return int(self.conn.execute(f"SELECT COUNT(*) FROM decisions WHERE 1=1{where}", args).fetchone()[0])


def json_of(value):
    if isinstance(value, str) and value[:1] in "{[":
        return json.loads(value)
    return value if isinstance(value, (dict, list)) else {}


__all__ = ["CONTRACT", "DecisionIndex", "json_of"]
